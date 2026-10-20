"""Development-only manual tests against the unchanged inference backend."""

from __future__ import annotations

import ipaddress
import json
import shutil
import sqlite3
from pathlib import Path
from time import perf_counter
from uuid import UUID
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response

from app.collection import _encode_video
from app.dev_test_contract import TrialRequest, TrialReview
from app.dev_test_store import TrialStore, canonical, digest_bytes, export_csv, now, outcome, summarize
from app.validation import close_frames, decode_frames


def _runtime_identity(settings, backend, manifest):
    model_path = {"pytorch": settings.pytorch_model_path, "onnx": settings.onnx_model_path,
                  "coreml": settings.coreml_model_path}.get(backend.name)
    artifact_sha256 = None
    if manifest is not None:
        artifact_sha256 = manifest.artifact_sha256
    elif model_path and model_path.is_file():
        import hashlib
        hash_value = hashlib.sha256()
        with model_path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                hash_value.update(block)
        artifact_sha256 = hash_value.hexdigest()
    elif model_path and model_path.is_dir():
        from app.backends.coreml_artifact import package_hash
        artifact_sha256 = package_hash(model_path)
    labels = list(backend.labels)
    if "Không ký hiệu" not in labels:
        labels.append("Không ký hiệu")
    identity = {"backend": backend.name, "model_version": backend.model_version, "labels": labels,
                "artifact_sha256": artifact_sha256, "confidence_threshold": settings.confidence_threshold,
                "margin_threshold": settings.margin_threshold, "pipeline": "manual-server-uniform-center-square-v1",
                "device": settings.coreml_compute_units if backend.name == "coreml" else str(getattr(backend, "device", "unknown")),
                "mock": backend.is_mock, "candidate_labels_unverified": backend.candidate_labels_unverified}
    identity["runtime_key"] = digest_bytes(canonical(identity).encode())
    return identity


def create_dev_test_router(app):
    settings = app.state.settings
    repo = Path(__file__).resolve().parents[3]
    data_root = (repo / "ml/data").resolve()
    test_root = settings.dev_test_dir.resolve()
    if test_root.is_relative_to(data_root) and not test_root.is_relative_to(data_root / "dev-tests"):
        raise ValueError("Test storage overlaps protected repository datasets")
    protected = [settings.collection_dir, *[repo / "ml/data" / name for name in ("raw", "collected", "combined", "processed", "evaluation")],
                 repo / "ml/artifacts"]
    store = TrialStore(settings.dev_test_dir, protected)
    cached_backend, cached_settings, cached_identity = None, None, None

    def runtime_snapshot():
        nonlocal cached_backend, cached_settings, cached_identity
        if not app.state.deployment_ready:
            raise HTTPException(503, "Runtime has not confirmed the active pointer")
        backend, current_settings = app.state.backend, app.state.runtime_settings
        if backend is not cached_backend or current_settings is not cached_settings:
            cached_identity = _runtime_identity(current_settings, backend,
                app.state.model_manifest if settings.model_deployment_worker else None)
            cached_backend, cached_settings = backend, current_settings
        return backend, cached_identity

    async def local_only(request: Request):
        try:
            local = request.client and ipaddress.ip_address(request.client.host).is_loopback
        except ValueError:
            local = False
        origin = request.headers.get("origin")
        if not local or origin and origin not in settings.allowed_origins:
            raise HTTPException(403, "Local development access only")

    router = APIRouter(prefix="/dev-tests", dependencies=[Depends(local_only)])

    @router.get("/config")
    async def config():
        backend, identity = runtime_snapshot()
        return {**identity, "enabled": True, "mock": backend.is_mock,
                "candidate_labels_unverified": backend.candidate_labels_unverified, "frame_count": 16,
                "storage_role": "manual_test_only_never_train"}

    def save_trial(payload: TrialRequest, fingerprint: str, backend, identity):
        with store.lock:
            trial_id = str(payload.trial_id)
            existing = store.find(trial_id)
            if existing:
                if existing[0] != fingerprint:
                    raise HTTPException(409, "Trial ID already belongs to a different capture")
                return existing[1]
            if payload.expected_label not in identity["labels"]:
                raise HTTPException(422, "Expected label is not supported")
            if payload.runtime_key is not None and payload.runtime_key != identity["runtime_key"]:
                raise HTTPException(409, "Runtime changed; refresh before starting a new test")
            prediction, error_stage, inference_ms = None, None, None
            decoded, source = [], []
            folder = store.root / trial_id
            if folder.is_symlink():
                raise HTTPException(503, "Unsafe test evidence folder")
            video_available = False
            try:
                # A process interrupted before the DB commit can leave an uncounted folder.
                if folder.exists():
                    shutil.rmtree(folder)
                folder.mkdir()
                if payload.technical_error:
                    error_stage = "capture"
                else:
                    try:
                        source = decode_frames(payload.source_frames, settings.max_frame_bytes)
                        decoded = decode_frames(payload.frames, settings.max_frame_bytes)
                    except Exception:
                        error_stage = "decode"
                    if error_stage is None:
                        started = perf_counter()
                        try:
                            result = backend.predict(decoded, 0)
                            prediction = {"status": result.status.value, "label": result.label, "confidence": result.confidence,
                                          "top_k": [{"label": item.label, "confidence": item.confidence} for item in result.top_k]}
                        except Exception:
                            error_stage = "inference"
                        inference_ms = (perf_counter() - started) * 1000
                    if source:
                        try:
                            temporary = folder / "clip.tmp"
                            _encode_video(temporary, source, payload.duration_ms)
                            temporary.replace(folder / "clip.mp4")
                            video_available = True
                        except Exception as error:
                            raise HTTPException(503, "Video evidence could not be saved; retry the same capture") from error
                    (folder / "frames.json").write_text(canonical({"frames": payload.frames}), encoding="utf-8")
                record = {**payload.model_dump(mode="json", exclude={"frames", "source_frames", "runtime_key"}), **identity,
                          "saved_at": now(), "prediction": prediction, "outcome": "technical_error" if error_stage else outcome(payload.expected_label, prediction),
                          "error_stage": error_stage, "inference_ms": inference_ms, "video_available": video_available,
                          "source_frame_count": len(payload.source_frames),
                          "encoded_frames_sha256": digest_bytes(canonical(payload.frames).encode()), "never_train": True}
                store.save(fingerprint, record)
                return record
            except (HTTPException, OSError, sqlite3.Error) as error:
                shutil.rmtree(folder, ignore_errors=True)
                if isinstance(error, HTTPException):
                    raise
                raise HTTPException(503, "Test evidence could not be saved; retry the same capture")
            finally:
                close_frames(decoded)
                close_frames(source)
                if folder.exists():
                    (folder / "clip.tmp").unlink(missing_ok=True)

    @router.post("/trials")
    async def trial(request: Request):
        limit = settings.max_message_bytes * 2
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if not 0 <= int(content_length) <= limit:
                    raise ValueError()
            except ValueError:
                raise HTTPException(413, "Test capture exceeds body limit")
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > limit:
                raise HTTPException(413, "Test capture exceeds body limit")
            body.extend(chunk)
        try:
            payload = TrialRequest.model_validate_json(body)
        except ValueError:
            raise HTTPException(422, "Invalid manual test capture")
        fingerprint = digest_bytes(canonical(payload.model_dump(mode="json")).encode())
        async with app.state.inference_slots:
            backend, identity = runtime_snapshot()
            return await run_in_threadpool(save_trial, payload, fingerprint, backend, identity)

    @router.get("/trials")
    async def trials(session_id: Optional[UUID] = None):
        rows = await run_in_threadpool(store.rows, str(session_id) if session_id else None)
        return {"trials": rows}

    @router.get("/summary")
    async def summary(session_id: Optional[UUID] = None):
        rows = await run_in_threadpool(store.rows, str(session_id) if session_id else None)
        return summarize(rows)

    @router.put("/trials/{trial_id}/review")
    async def review(trial_id: UUID, payload: TrialReview):
        try:
            await run_in_threadpool(store.review, str(trial_id), payload.model_dump())
        except KeyError:
            raise HTTPException(404, "Unknown trial")
        return {"saved": True}

    @router.get("/trials/{trial_id}/video")
    async def video(trial_id: UUID):
        existing = await run_in_threadpool(store.find, str(trial_id))
        path = store.root / str(trial_id) / "clip.mp4"
        if not existing or not existing[1]["video_available"] or not path.is_file():
            raise HTTPException(404, "No video available for this trial")
        return FileResponse(path, media_type="video/mp4", headers={"Cache-Control": "no-store"})

    @router.get("/trials/{trial_id}/frames")
    async def frames(trial_id: UUID):
        if not await run_in_threadpool(store.find, str(trial_id)):
            raise HTTPException(404, "Unknown trial")
        path = store.root / str(trial_id) / "frames.json"
        if not path.is_file():
            raise HTTPException(404, "No inference frames for a capture failure")
        return json.loads(await run_in_threadpool(path.read_text, encoding="utf-8"))

    @router.get("/export")
    async def export(format: str = Query("json", pattern="^(json|csv)$"), session_id: Optional[UUID] = None):
        rows = await run_in_threadpool(store.rows, str(session_id) if session_id else None)
        data = canonical({"trials": rows, "summary": summarize(rows)}) if format == "json" else export_csv(rows)
        return Response(data, media_type="application/json" if format == "json" else "text/csv",
                        headers={"Content-Disposition": f'attachment; filename="vsign-manual-tests.{format}"', "Cache-Control": "no-store"})

    return router
