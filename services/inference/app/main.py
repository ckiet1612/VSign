from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import unicodedata
from typing import Any, Callable, Literal, Optional
from threading import Lock
from contextlib import asynccontextmanager
from uuid import uuid4

from argon2 import PasswordHasher
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.backends import InferenceBackend, create_backend
from app.backends.base import BackendPrediction
from app.collection import (
    CollectionConflict, PERSONAL_COLLECTION_TARGET, collection_root,
    sample_counts, save_collection_sample,
)
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
    SentenceComposeRequest,
    SentenceComposeResponse,
    SUPPORTED_MIME_TYPES,
    FramesMessage,
)
from app.model_manifest import load_model_manifest
from app.platform_db import create_database
from app.platform_auth import SESSION_COOKIE_NAME, bootstrap_platform, resolve_principal
from app.inference_token import verify_inference_token
from app.platform_router import create_platform_router
from app.display_hub import DisplayHub
from app.display_router import create_display_socket
from app.sentence import SentenceComposer, create_sentence_composer
from contracts.v1.workspace import WORKSPACE_API_VERSION


COLLECTION_EXTRA_LABELS = ("Không ký hiệu",)
from app.validation import FrameValidationError, close_frames, decode_frames


def _label_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip().casefold()


logger = logging.getLogger("vsign.inference")
_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


def _safe_sequence(payload: Any) -> int:
    if isinstance(payload, dict):
        value = payload.get("sequence")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return 0


def _load_decision_policy(settings: Settings, backend: InferenceBackend):
    """(model_version, policy) for the configured policy file, or None to keep fixed thresholds."""
    if settings.decision_policy_path is None:
        return None
    from app.decision import DecisionPolicy

    try:
        policy = DecisionPolicy.load(settings.decision_policy_path, backend.labels, backend.model_version)
    except (OSError, ValueError, KeyError) as exc:
        # A stale or broken policy must never block recognition; fall back to fixed thresholds.
        logger.error("Decision policy rejected (%s): %s", type(exc).__name__, exc)
        return None
    return backend.model_version, policy


def _apply_decision_policy(app_state, backend: InferenceBackend, result: BackendPrediction,
                           context_words: list[str]) -> tuple[BackendPrediction, tuple[str, ...]]:
    loaded = getattr(app_state, "decision_policy", None)
    if loaded is None or result.probabilities is None or loaded[0] != backend.model_version:
        return result, ()
    return loaded[1].decide(result.probabilities, context_words)


def _response_from_backend(
    sequence: int, model_version: str, result: BackendPrediction, adjusted: tuple[str, ...] = (),
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
        adjusted=list(adjusted),
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
    sentence_composer: Optional[SentenceComposer] = None,
    runtime_backend_factory: Callable[[Settings], InferenceBackend] = create_backend,
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    resolved_backend = backend or create_backend(resolved_settings)
    resolved_sentence_composer = sentence_composer or create_sentence_composer(
        resolved_settings.openai_api_key,
        resolved_settings.openai_model,
        resolved_settings.sentence_rules,
    )
    model_manifest = load_model_manifest(resolved_settings.model_manifest_path)
    if model_manifest is not None:
        model_manifest.validate(
            app_environment=resolved_settings.app_environment,
            backend=resolved_backend.name,
            model_version=resolved_backend.model_version,
            labels=resolved_backend.labels,
            confidence_threshold=resolved_settings.confidence_threshold,
            margin_threshold=resolved_settings.margin_threshold,
        )
    password_hasher = PasswordHasher()
    inference_only = resolved_settings.runtime_role == "inference_only"

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        database = None
        deployment_worker = None
        if inference_only:
            # No platform database here: sockets are authorized by signed inference tokens.
            application.state.platform_database = None
            yield
            return
        try:
            try:
                database = create_database(resolved_settings.database_url)
                await run_in_threadpool(database.ensure_schema, resolved_settings.database_auto_create)
                await run_in_threadpool(bootstrap_platform, database, resolved_settings, password_hasher)
                application.state.platform_database = database
            except Exception as exc:
                logger.error("Platform database initialization failed (%s)", type(exc).__name__)
                if resolved_settings.model_deployment_worker:
                    raise RuntimeError("Managed runtime requires the deployment database") from exc
            if resolved_settings.model_deployment_worker:
                from app.model_registry import ModelRegistry
                from app.deployment_worker import DeploymentWorker
                deployment_worker = DeploymentWorker(application, ModelRegistry(database, resolved_settings), runtime_backend_factory)
                await deployment_worker.start()
            yield
        finally:
            if deployment_worker is not None:
                await deployment_worker.stop()
            if database is not None:
                database.dispose()
            application.state.platform_database = None

    app = FastAPI(title="VSign inference", version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved_settings
    app.state.backend = resolved_backend
    app.state.runtime_settings = resolved_settings
    app.state.deployment_ready = not resolved_settings.model_deployment_worker
    app.state.model_manifest = model_manifest
    app.state.decision_policy = _load_decision_policy(resolved_settings, resolved_backend)
    app.state.inference_slots = asyncio.Semaphore(1)
    app.state.collection_lock = Lock()
    app.state.platform_database = None
    app.state.password_hasher = password_hasher
    app.state.display_hub = DisplayHub()
    if not inference_only:
        app.include_router(
            create_platform_router(
                resolved_settings,
                app.state.password_hasher,
            )
        )

    async def authorize_runtime(token: Optional[str], permission: str) -> None:
        if not resolved_settings.auth_required:
            return
        database = app.state.platform_database
        if database is None:
            raise HTTPException(503, "Workspace chưa sẵn sàng")
        current = await run_in_threadpool(resolve_principal, database, token, resolved_settings.workspace_id)
        if current is None:
            raise HTTPException(401, "Đăng nhập để tiếp tục")
        if not current.can(permission):
            raise HTTPException(403, "Bạn không có quyền thực hiện thao tác này")

    @app.middleware("http")
    async def limit_inference_only_routes(request: Request, call_next: Any) -> Any:
        if inference_only and request.url.path not in {"/health", "/metadata"}:
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        return await call_next(request)

    @app.middleware("http")
    async def protect_runtime_requests(request: Request, call_next: Any) -> Any:
        permissions = {"/sentence/compose": "recognize:use", "/collection/summary": "data:use",
                       "/collection/samples": "data:use"}
        permission = permissions.get(request.url.path.rstrip("/"))
        if permission and request.method != "OPTIONS" and resolved_settings.auth_required:
            try:
                await authorize_runtime(request.cookies.get(SESSION_COOKIE_NAME), permission)
                if request.method not in {"GET", "HEAD"}:
                    origin = request.headers.get("origin")
                    if ((origin and origin not in resolved_settings.allowed_origins) or
                            (not origin and request.headers.get("sec-fetch-site") in {"cross-site", "same-site"})):
                        raise HTTPException(403, "Origin không được phép")
            except HTTPException as error:
                return JSONResponse(status_code=error.status_code, content={"detail": error.detail})
        return await call_next(request)

    @app.middleware("http")
    async def add_platform_headers(request: Request, call_next: Any) -> Any:
        candidate = request.headers.get("x-request-id", "").strip()
        request_id = candidate if _REQUEST_ID_PATTERN.fullmatch(candidate) else str(uuid4())
        if (request.headers.get("authorization") is not None and request.url.path.startswith("/api/v1/")
                and not request.url.path.startswith("/api/v1/integrations/")):
            # A service credential must never inherit local-admin or cookie permissions.
            response = JSONResponse(status_code=403, content={"detail":"Khóa API chỉ dùng trên API tích hợp được cấp quyền"})
        else:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-VSign-API-Version"] = WORKSPACE_API_VERSION
        if request.url.path.startswith("/api/v1/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.middleware("http")
    async def limit_small_platform_body(request: Request, call_next: Any) -> Any:
        is_models_write = request.method == "POST" and request.url.path.startswith("/api/v1/workspace/models")
        is_evaluation_write = request.method == "POST" and request.url.path.startswith("/api/v1/workspace/evaluations")
        is_integration_write = request.method == "POST" and request.url.path.startswith("/api/v1/workspace/integrations")
        is_team_write = request.method == 'POST' and request.url.path.startswith(('/api/v1/workspace/team', '/api/v1/invitations/'))
        is_settings_write = request.method == 'POST' and request.url.path.startswith(('/api/v1/workspace/settings', '/api/v1/displays'))
        is_data_write = request.method == "POST" and request.url.path.startswith("/api/v1/workspace/data")
        is_data_sample = is_data_write and request.url.path.endswith("/samples")
        if is_models_write or is_evaluation_write or is_integration_write or is_team_write or is_settings_write or is_data_write or request.url.path in {"/api/v1/auth/login", "/api/v1/workspace/audit/client-events"}:
            chunks = []
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                limit = resolved_settings.max_message_bytes if is_data_sample else 65536 if is_data_write else 8192 if is_models_write or is_evaluation_write or is_integration_write or is_team_write or is_settings_write else 4096
                if size > limit:
                    return JSONResponse(status_code=413, content={"detail": "Yêu cầu vượt giới hạn"})
                chunks.append(chunk)
            request._body = b"".join(chunks)
        return await call_next(request)

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

    # Wrap auth middleware too, so denied requests retain credentialed CORS headers.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT"] if resolved_settings.app_environment == "development" and resolved_settings.dev_test_enabled else ["GET", "POST"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-VSign-API-Version", "Retry-After"],
    )

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        if not app.state.deployment_ready:
            raise HTTPException(503, "Runtime chưa xác nhận active pointer")
        active_backend = app.state.backend
        return HealthResponse(
            backend=active_backend.name,
            model_version=active_backend.model_version,
        )

    @app.get("/metadata", response_model=MetadataResponse)
    async def metadata() -> MetadataResponse:
        if not app.state.deployment_ready:
            raise HTTPException(503, "Runtime chưa xác nhận active pointer")
        active_backend = app.state.backend
        runtime_settings = app.state.runtime_settings
        return MetadataResponse(
            backend=active_backend.name,
            gpu_name=getattr(active_backend, "gpu_name", None),
            model_version=active_backend.model_version,
            supported_image_formats=list(SUPPORTED_MIME_TYPES),
            confidence_threshold=runtime_settings.confidence_threshold,
            margin_threshold=runtime_settings.margin_threshold,
            labels=list(active_backend.labels),
            collection_labels=list(resolved_settings.collection_labels),
            candidate_labels_unverified=active_backend.candidate_labels_unverified,
            mock=active_backend.is_mock,
            collection_enabled=resolved_settings.collection_enabled,
            collection_target_per_hand=resolved_settings.collection_target_per_hand,
            sentence_ai_enabled=resolved_sentence_composer.enabled,
            input_framing=resolved_settings.input_framing,
        )

    @app.post("/sentence/compose", response_model=SentenceComposeResponse)
    async def compose_sentence(payload: SentenceComposeRequest) -> SentenceComposeResponse:
        allowed_labels = {
            _label_key(label): label for label in resolved_settings.collection_labels
        }
        normalized_words: list[str] = []
        for word in payload.words:
            label = allowed_labels.get(_label_key(word))
            if label is None:
                raise HTTPException(
                    status_code=422,
                    detail="Từ không thuộc bộ từ Sales30",
                )
            normalized_words.append(label)
        composition = await run_in_threadpool(
            resolved_sentence_composer.compose,
            normalized_words,
        )
        if len(composition.sentence) > 300:
            raise HTTPException(status_code=422, detail="Câu vượt giới hạn 300 ký tự · giữ nguyên từ để kiểm tra")
        return SentenceComposeResponse(
            sentence=composition.sentence,
            provider=composition.provider,
            model=composition.model,
            warnings=list(composition.warnings),
        )

    @app.get("/collection/summary", response_model=CollectionSummaryResponse)
    async def collection_summary(
        batch: Optional[Literal["personal-100"]] = None,
    ) -> CollectionSummaryResponse:
        if not resolved_settings.collection_enabled:
            return CollectionSummaryResponse(
                enabled=False,
                target_per_hand=resolved_settings.collection_target_per_hand,
                counts={},
                batch=batch,
                target_per_label=PERSONAL_COLLECTION_TARGET if batch else None,
            )
        collection_labels = list(resolved_settings.collection_labels) + [
            label
            for label in COLLECTION_EXTRA_LABELS
            if label not in resolved_settings.collection_labels
        ]
        counts = await run_in_threadpool(
            sample_counts,
            collection_root(resolved_settings.collection_dir, batch),
            collection_labels,
            committed_only=batch is not None,
        )
        return CollectionSummaryResponse(
            enabled=True,
            target_per_hand=resolved_settings.collection_target_per_hand,
            counts=counts,
            batch=batch,
            target_per_label=PERSONAL_COLLECTION_TARGET if batch else None,
        )

    @app.post("/collection/samples", response_model=CollectionSampleResponse)
    async def collection_sample(payload: CollectionSampleRequest) -> CollectionSampleResponse:
        active_backend = app.state.backend
        if not resolved_settings.collection_enabled:
            raise HTTPException(status_code=403, detail="Thu dữ liệu đang bị tắt")
        allowed_label_keys = {
            _label_key(label)
            for label in (
                *resolved_settings.collection_labels,
                *COLLECTION_EXTRA_LABELS,
            )
        }
        if _label_key(payload.expected_label) not in allowed_label_keys:
            raise HTTPException(
                status_code=422,
                detail="Nhãn mong đợi không thuộc bộ thu thập sales-30",
            )
        backend_label_keys = {_label_key(label) for label in active_backend.labels}
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
            root = collection_root(resolved_settings.collection_dir, payload.batch)
            fingerprint = hashlib.sha256(payload.model_dump_json().encode()).hexdigest()

            def save_capture() -> tuple[str, str, int, int]:
                # Quota check, commit and counts share a lock inside the worker thread.
                with app.state.collection_lock:
                    sample_id, relative_path, count = save_collection_sample(
                        root,
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
                        model_version=active_backend.model_version,
                        sample_key=payload.sample_key if payload.batch else None,
                        request_fingerprint=fingerprint,
                        target_per_label=PERSONAL_COLLECTION_TARGET if payload.batch else None,
                    )
                    counts = sample_counts(root, [payload.expected_label], committed_only=payload.batch is not None)
                    label_count = counts[payload.expected_label].right + counts[payload.expected_label].left
                    return sample_id, relative_path, count, label_count

            sample_id, relative_path, count, label_count = await run_in_threadpool(save_capture)
            if payload.batch:
                relative_path = f"batches/{payload.batch}/{relative_path}"
        except CollectionConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
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
            label_count=label_count,
        )

    @app.websocket("/ws/inference")
    async def inference(websocket: WebSocket) -> None:
        if not app.state.deployment_ready:
            await websocket.close(code=1013, reason="Runtime chưa xác nhận active pointer")
            return
        origin = websocket.headers.get("origin")
        allowed = resolved_settings.allowed_origins
        if origin and "*" not in allowed and origin not in allowed:
            await websocket.close(code=1008, reason="Origin không được phép")
            return
        token = websocket.cookies.get(SESSION_COOKIE_NAME)
        # The Mac issues signed tokens (POST /api/v1/inference/token) so a GPU runtime without
        # the platform database can still require a signed-in user.
        signed_token = websocket.query_params.get("token")
        token_claims = None
        if signed_token and resolved_settings.inference_token_secret:
            token_claims = verify_inference_token(
                resolved_settings.inference_token_secret, signed_token, resolved_settings.workspace_id
            )
        if token_claims is None and (inference_only or signed_token):
            await websocket.close(code=1008, reason="Đăng nhập để tiếp tục")
            return
        try:
            if token_claims is None:
                await authorize_runtime(token, "recognize:use")
        except HTTPException:
            await websocket.close(code=1008, reason="Đăng nhập để tiếp tục")
            return
        await websocket.accept()
        gpu_name = getattr(app.state.backend, "gpu_name", None)
        if gpu_name:
            await websocket.send_json({"type": "runtime_info", "gpu_name": gpu_name})
        try:
            while True:
                packet = await websocket.receive()
                if packet["type"] == "websocket.disconnect":
                    break
                # An open socket must not outlive a revoked or expired login session.
                try:
                    if token_claims is None:
                        await authorize_runtime(token, "recognize:use")
                    elif token_claims.expired():
                        raise HTTPException(401, "Phiên nhận dạng đã hết hạn")
                except HTTPException:
                    await websocket.close(code=1008, reason="Phiên đăng nhập đã hết hạn")
                    break
                raw_text = packet.get("text")
                if raw_text is None:
                    await websocket.send_json(
                        _error_response(0, app.state.backend.model_version).model_dump(mode="json")
                    )
                    continue
                if len(raw_text.encode("utf-8")) > resolved_settings.max_message_bytes:
                    await websocket.send_json(
                        _error_response(0, app.state.backend.model_version).model_dump(mode="json")
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
                        _error_response(sequence, app.state.backend.model_version).model_dump(mode="json")
                    )
                    continue

                slots = app.state.inference_slots
                if slots.locked():
                    await websocket.send_json(
                        _error_response(
                            request.sequence,
                            app.state.backend.model_version,
                            PredictionStatus.BUSY,
                        ).model_dump(mode="json")
                    )
                    continue

                await slots.acquire()
                active_backend = app.state.backend
                decoded = []
                try:
                    if not app.state.deployment_ready:
                        raise RuntimeError("Managed runtime is not ready")
                    decoded = await run_in_threadpool(
                        decode_frames, request.frames, resolved_settings.max_frame_bytes
                    )
                    result = await run_in_threadpool(
                        active_backend.predict, decoded, request.sequence
                    )
                    result, adjusted = await run_in_threadpool(
                        _apply_decision_policy, app.state, active_backend, result, request.context_words
                    )
                    response = _response_from_backend(
                        request.sequence, active_backend.model_version, result, adjusted
                    )
                except FrameValidationError:
                    response = _error_response(request.sequence, active_backend.model_version)
                except Exception as exc:
                    logger.error(
                        "Inference request failed for sequence=%s (%s)",
                        request.sequence,
                        type(exc).__name__,
                    )
                    response = _error_response(request.sequence, active_backend.model_version)
                finally:
                    close_frames(decoded)
                    slots.release()
                await websocket.send_json(response.model_dump(mode="json"))
        except WebSocketDisconnect:
            return

    if not inference_only:
        app.add_api_websocket_route("/ws/display/{display_id}", create_display_socket(resolved_settings))

    if not inference_only and resolved_settings.app_environment == "development" and resolved_settings.dev_test_enabled:
        from app.dev_test import create_dev_test_router
        app.include_router(create_dev_test_router(app))

    return app


app = create_app()
