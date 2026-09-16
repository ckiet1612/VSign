from __future__ import annotations

import asyncio
import json
import logging
import unicodedata
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.backends import InferenceBackend, create_backend
from app.backends.base import BackendPrediction
from app.collection import sample_counts, save_collection_sample
from app.config import Settings
from app.models import (
    CollectionSampleRequest,
    CollectionSampleResponse,
    CollectionSummaryResponse,
    HealthResponse,
    MetadataResponse,
    PredictionCandidate,
    PredictionMessage,
    PredictionStatus,
    SUPPORTED_MIME_TYPES,
    FramesMessage,
)


COLLECTION_EXTRA_LABELS = ("Không ký hiệu",)
from app.validation import FrameValidationError, close_frames, decode_frames


def _label_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip().casefold()


logger = logging.getLogger("vsign.inference")


def _safe_sequence(payload: Any) -> int:
    if isinstance(payload, dict):
        value = payload.get("sequence")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return 0


def _response_from_backend(
    sequence: int, model_version: str, result: BackendPrediction
) -> PredictionMessage:
    return PredictionMessage(
        sequence=sequence,
        status=result.status,
        label=result.label,
        confidence=result.confidence,
        top_k=[
            PredictionCandidate(label=item.label, confidence=item.confidence)
            for item in result.top_k
        ],
        model_version=model_version,
    )


def _error_response(
    sequence: int, model_version: str, status: PredictionStatus = PredictionStatus.ERROR
) -> PredictionMessage:
    return PredictionMessage(
        sequence=sequence,
        status=status,
        label=None,
        confidence=None,
        top_k=[],
        model_version=model_version,
    )


def create_app(
    settings: Optional[Settings] = None,
    backend: Optional[InferenceBackend] = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    resolved_backend = backend or create_backend(resolved_settings)
    app = FastAPI(title="VSign inference", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.state.settings = resolved_settings
    app.state.backend = resolved_backend
    app.state.inference_slots = asyncio.Semaphore(1)

    @app.middleware("http")
    async def limit_collection_body(request: Request, call_next: Any) -> Any:
        if request.url.path == "/collection/samples":
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    too_large = int(content_length) > resolved_settings.max_message_bytes
                except ValueError:
                    too_large = True
                if too_large:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": "Mẫu thu vượt giới hạn kích thước"},
                    )
        return await call_next(request)

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(
            backend=resolved_backend.name,
            model_version=resolved_backend.model_version,
        )

    @app.get("/metadata", response_model=MetadataResponse)
    async def metadata() -> MetadataResponse:
        return MetadataResponse(
            backend=resolved_backend.name,
            model_version=resolved_backend.model_version,
            supported_image_formats=list(SUPPORTED_MIME_TYPES),
            confidence_threshold=resolved_settings.confidence_threshold,
            margin_threshold=resolved_settings.margin_threshold,
            labels=list(resolved_backend.labels),
            candidate_labels_unverified=resolved_backend.candidate_labels_unverified,
            mock=resolved_backend.is_mock,
            collection_enabled=resolved_settings.collection_enabled,
            collection_target_per_hand=resolved_settings.collection_target_per_hand,
        )

    @app.get("/collection/summary", response_model=CollectionSummaryResponse)
    async def collection_summary() -> CollectionSummaryResponse:
        if not resolved_settings.collection_enabled:
            return CollectionSummaryResponse(
                enabled=False,
                target_per_hand=resolved_settings.collection_target_per_hand,
                counts={},
            )
        collection_labels = list(resolved_backend.labels) + [
            label
            for label in COLLECTION_EXTRA_LABELS
            if label not in resolved_backend.labels
        ]
        counts = await run_in_threadpool(
            sample_counts,
            resolved_settings.collection_dir,
            collection_labels,
        )
        return CollectionSummaryResponse(
            enabled=True,
            target_per_hand=resolved_settings.collection_target_per_hand,
            counts=counts,
        )

    @app.post("/collection/samples", response_model=CollectionSampleResponse)
    async def collection_sample(payload: CollectionSampleRequest) -> CollectionSampleResponse:
        if not resolved_settings.collection_enabled:
            raise HTTPException(status_code=403, detail="Thu dữ liệu đang bị tắt")
        allowed_label_keys = {
            _label_key(label)
            for label in (*resolved_backend.labels, *COLLECTION_EXTRA_LABELS)
        }
        if _label_key(payload.expected_label) not in allowed_label_keys:
            raise HTTPException(status_code=422, detail="Nhãn mong đợi không thuộc model hiện tại")
        backend_label_keys = {_label_key(label) for label in resolved_backend.labels}
        if (
            payload.predicted_label is not None
            and _label_key(payload.predicted_label) not in backend_label_keys
        ):
            raise HTTPException(status_code=422, detail="Nhãn dự đoán không thuộc model hiện tại")

        decoded = []
        try:
            decoded = await run_in_threadpool(
                decode_frames,
                payload.frames,
                resolved_settings.max_frame_bytes,
            )
            sample_id, relative_path, count = await run_in_threadpool(
                save_collection_sample,
                resolved_settings.collection_dir,
                frames=decoded,
                session_id=payload.session_id,
                captured_at=payload.captured_at,
                duration_ms=payload.duration_ms,
                expected_label=payload.expected_label,
                hand=payload.hand,
                predicted_label=payload.predicted_label,
                predicted_confidence=payload.predicted_confidence,
                distance=payload.distance,
                lighting=payload.lighting,
                negative_action=payload.negative_action,
                model_version=resolved_backend.model_version,
            )
        except FrameValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except HTTPException:
            raise
        except Exception as error:
            logger.error("Saving collection sample failed (%s)", type(error).__name__)
            raise HTTPException(status_code=500, detail="Không thể lưu mẫu video") from error
        finally:
            close_frames(decoded)
        return CollectionSampleResponse(
            sample_id=sample_id,
            expected_label=payload.expected_label,
            hand=payload.hand,
            relative_video_path=relative_path,
            label_hand_count=count,
        )

    @app.websocket("/ws/inference")
    async def inference(websocket: WebSocket) -> None:
        origin = websocket.headers.get("origin")
        allowed = resolved_settings.allowed_origins
        if origin and "*" not in allowed and origin not in allowed:
            await websocket.close(code=1008, reason="Origin không được phép")
            return
        await websocket.accept()
        try:
            while True:
                packet = await websocket.receive()
                if packet["type"] == "websocket.disconnect":
                    break
                raw_text = packet.get("text")
                if raw_text is None:
                    await websocket.send_json(
                        _error_response(0, resolved_backend.model_version).model_dump(mode="json")
                    )
                    continue
                if len(raw_text.encode("utf-8")) > resolved_settings.max_message_bytes:
                    await websocket.send_json(
                        _error_response(0, resolved_backend.model_version).model_dump(mode="json")
                    )
                    continue

                payload: Any = None
                sequence = 0
                try:
                    payload = json.loads(raw_text)
                    sequence = _safe_sequence(payload)
                    request = FramesMessage.model_validate(payload)
                except (json.JSONDecodeError, ValidationError):
                    await websocket.send_json(
                        _error_response(sequence, resolved_backend.model_version).model_dump(mode="json")
                    )
                    continue

                slots = app.state.inference_slots
                if slots.locked():
                    await websocket.send_json(
                        _error_response(
                            request.sequence,
                            resolved_backend.model_version,
                            PredictionStatus.BUSY,
                        ).model_dump(mode="json")
                    )
                    continue

                await slots.acquire()
                decoded = []
                try:
                    decoded = await run_in_threadpool(
                        decode_frames, request.frames, resolved_settings.max_frame_bytes
                    )
                    result = await run_in_threadpool(
                        resolved_backend.predict, decoded, request.sequence
                    )
                    response = _response_from_backend(
                        request.sequence, resolved_backend.model_version, result
                    )
                except FrameValidationError:
                    response = _error_response(request.sequence, resolved_backend.model_version)
                except Exception as exc:
                    logger.error(
                        "Inference request failed for sequence=%s (%s)",
                        request.sequence,
                        type(exc).__name__,
                    )
                    response = _error_response(request.sequence, resolved_backend.model_version)
                finally:
                    close_frames(decoded)
                    slots.release()
                await websocket.send_json(response.model_dump(mode="json"))
        except WebSocketDisconnect:
            return

    return app


app = create_app()
