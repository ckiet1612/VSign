from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

from contracts.v1.sales_vocabulary import SALES_30_LABELS


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} phải là một số") from exc
    if not 0 <= parsed <= 1:
        raise RuntimeError(f"{name} phải nằm trong khoảng 0..1")
    return parsed


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} phải là số nguyên") from exc
    if parsed <= 0:
        raise RuntimeError(f"{name} phải lớn hơn 0")
    return parsed


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} phải là true hoặc false")


def _ice_servers_env() -> Tuple[dict, ...]:
    """WebRTC ICE servers for counter displays, as the JSON list RTCPeerConnection accepts.

    The default STUN server is enough on one counter network; across networks set a TURN server here,
    because the HTTPS tunnel does not carry the UDP media path.
    """
    raw = os.getenv("DISPLAY_ICE_SERVERS", "").strip()
    if not raw:
        return ({"urls": ["stun:stun.l.google.com:19302"]},)
    import json
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("DISPLAY_ICE_SERVERS phải là JSON list") from exc
    if not isinstance(value, list) or not all(
        isinstance(item, dict) and isinstance(item.get("urls"), (str, list))
        and all(isinstance(url, str) and re.match(r"^(stun|stuns|turn|turns):", url)
                for url in ([item["urls"]] if isinstance(item["urls"], str) else item["urls"]))
        and set(item) <= {"urls", "username", "credential"}
        for item in value
    ):
        raise RuntimeError("DISPLAY_ICE_SERVERS chỉ nhận urls (stun:/turn:), username và credential")
    return tuple(value)


def _workspace_id_env() -> str:
    value = os.getenv("WORKSPACE_ID", "local").strip() or "local"
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", value) is None:
        raise RuntimeError("WORKSPACE_ID chỉ được chứa chữ, số, dấu chấm, gạch dưới hoặc gạch ngang")
    return value


def _workspace_name_env() -> str:
    value = os.getenv("WORKSPACE_NAME", "VSign workspace").strip() or "VSign workspace"
    if len(value) > 120:
        raise RuntimeError("WORKSPACE_NAME không được vượt quá 120 ký tự")
    return value


def _integration_key_env() -> Optional[str]:
    value=os.getenv("INTEGRATION_ENCRYPTION_KEY", "").strip()
    if value:
        return value
    path=os.getenv("INTEGRATION_ENCRYPTION_KEY_FILE", "").strip()
    if not path:
        return None
    try:
        target=Path(path).expanduser()
        if target.is_symlink() or not target.is_file() or target.stat().st_size>128:
            return None
        return target.read_text(encoding="ascii").strip() or None
    except (OSError,UnicodeError):
        return None


def _inference_token_secret_env() -> Optional[str]:
    value = os.getenv("INFERENCE_TOKEN_SECRET", "").strip()
    path = os.getenv("INFERENCE_TOKEN_SECRET_FILE", "").strip()
    if not value and path:
        try:
            target = Path(path).expanduser()
            if target.is_symlink() or not target.is_file() or target.stat().st_size > 256:
                raise RuntimeError("INFERENCE_TOKEN_SECRET_FILE không hợp lệ")
            value = target.read_text(encoding="ascii").strip()
        except (OSError, UnicodeError) as exc:
            raise RuntimeError("Không đọc được INFERENCE_TOKEN_SECRET_FILE") from exc
    if not value:
        return None
    if len(value) < 32:
        raise RuntimeError("INFERENCE_TOKEN_SECRET phải dài ít nhất 32 ký tự")
    return value


@dataclass(frozen=True)
class Settings:
    inference_backend: str = "mock"
    model_version: str = "mock-common-20-v1"
    onnx_model_path: Optional[Path] = None
    pytorch_model_path: Optional[Path] = None
    pytorch_device: str = "auto"
    coreml_model_path: Optional[Path] = None
    model_manifest_path: Optional[Path] = None
    coreml_compute_units: str = "ALL"
    input_framing: str = "center-square"
    decision_policy_path: Optional[Path] = None
    label_map_path: Optional[Path] = None
    labels_verified: bool = False
    confidence_threshold: float = 0.70
    margin_threshold: float = 0.15
    allowed_origins: Tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:5175",
        "http://127.0.0.1:5175",
        "http://localhost:8080",
    )
    max_frame_bytes: int = 256 * 1024
    max_message_bytes: int = 6 * 1024 * 1024
    collection_enabled: bool = False
    collection_dir: Path = Path("ml/data/collected/sales30")
    collection_labels: Tuple[str, ...] = SALES_30_LABELS
    collection_target_per_hand: int = 50
    openai_api_key: Optional[str] = field(default=None, repr=False)
    openai_model: Optional[str] = None
    sentence_rules: str = "expanded"
    app_environment: str = "production"
    workspace_id: str = "local"
    workspace_name: str = "VSign workspace"
    database_url: str = "sqlite:///:memory:"
    database_auto_create: bool = True
    auth_required: bool = False
    local_admin_enabled: bool = False
    local_admin_role: str = "admin"
    auth_cookie_secure: bool = False
    auth_session_ttl_seconds: int = 8 * 60 * 60
    bootstrap_admin_email: Optional[str] = None
    bootstrap_admin_password: Optional[str] = field(default=None, repr=False)
    bootstrap_admin_name: str = "Workspace Admin"
    dev_test_enabled: bool = False
    dev_test_dir: Path = Path("ml/data/dev-tests/manual")
    model_registry_roots: Tuple[Path, ...] = (Path("ml/artifacts"),)
    model_evaluation_roots: Tuple[Path, ...] = (Path("ml/evaluations"),)
    model_deployment_worker: bool = False
    model_deployment_target: str = "production-local"
    model_deployment_runtime_url: str = "http://127.0.0.1:8002"
    integration_encryption_key: Optional[str] = field(default=None, repr=False)
    display_ice_servers: Tuple[dict, ...] = ({"urls": ["stun:stun.l.google.com:19302"]},)
    # "inference_only" serves just /health, /metadata and /ws/inference, authorized by signed
    # inference tokens instead of the platform database (used by the Modal GPU runtime).
    runtime_role: str = "full"
    inference_token_secret: Optional[str] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.runtime_role not in {"full", "inference_only"}:
            raise RuntimeError("RUNTIME_ROLE chỉ hỗ trợ full hoặc inference_only")
        if self.runtime_role == "inference_only" and not self.inference_token_secret:
            raise RuntimeError("RUNTIME_ROLE=inference_only cần INFERENCE_TOKEN_SECRET")
        if self.local_admin_role not in {"admin", "system_admin"}:
            raise RuntimeError("LOCAL_ADMIN_ROLE chỉ hỗ trợ admin hoặc system_admin")
        if self.local_admin_enabled and (self.app_environment != "development" or self.auth_required):
            raise RuntimeError("LOCAL_ADMIN_ENABLED chỉ dùng với APP_ENV=development và AUTH_REQUIRED=false")

    @classmethod
    def from_env(cls) -> "Settings":
        environment = os.getenv("APP_ENV", "production").strip().lower()
        if environment not in {"development", "production"}:
            raise RuntimeError("APP_ENV must be development or production")
        auth_required = _bool_env("AUTH_REQUIRED", False)
        sentence_rules = os.getenv("SENTENCE_RULES", "expanded").strip().lower() or "expanded"
        if sentence_rules not in {"expanded", "legacy"}:
            raise RuntimeError("SENTENCE_RULES chỉ hỗ trợ expanded hoặc legacy")
        backend = os.getenv("INFERENCE_BACKEND", "mock").strip().lower()
        if backend not in {"mock", "onnx", "pytorch", "coreml"}:
            raise RuntimeError(
                "INFERENCE_BACKEND chỉ hỗ trợ 'mock', 'onnx', 'pytorch' hoặc 'coreml'"
            )

        model_path = os.getenv("ONNX_MODEL_PATH", "").strip()
        pytorch_model_path = os.getenv("PYTORCH_MODEL_PATH", "").strip()
        coreml_model_path = os.getenv("COREML_MODEL_PATH", "").strip()
        model_manifest_path = os.getenv("MODEL_MANIFEST_PATH", "").strip()
        coreml_compute_units = os.getenv("COREML_COMPUTE_UNITS", "ALL").strip().upper()
        if backend == "coreml" and coreml_compute_units not in {"ALL", "CPU_ONLY", "CPU_AND_GPU", "CPU_AND_NE"}:
            raise RuntimeError("COREML_COMPUTE_UNITS chỉ hỗ trợ ALL, CPU_ONLY, CPU_AND_GPU hoặc CPU_AND_NE")
        decision_policy_path = os.getenv("DECISION_POLICY_PATH", "").strip()
        input_framing = os.getenv("INPUT_FRAMING", "center-square").strip().lower() or "center-square"
        if input_framing not in {"center-square", "trim-bodycrop-v1"}:
            raise RuntimeError("INPUT_FRAMING chỉ hỗ trợ center-square hoặc trim-bodycrop-v1")
        pytorch_device = os.getenv("PYTORCH_DEVICE", "auto").strip().lower()
        if pytorch_device not in {"auto", "cpu", "cuda"}:
            raise RuntimeError("PYTORCH_DEVICE chỉ hỗ trợ auto, cpu hoặc cuda")
        label_path = os.getenv("LABEL_MAP_PATH", "").strip()
        origins = tuple(
            origin.strip()
            for origin in os.getenv(
                "ALLOWED_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174,http://localhost:5175,http://127.0.0.1:5175,http://localhost:8080",
            ).split(",")
            if origin.strip()
        )
        if not origins:
            raise RuntimeError("ALLOWED_ORIGINS không được để trống")

        default_versions = {
            "mock": "mock-common-20-v1",
            "onnx": "onnx-v1",
            "pytorch": "multivsl-mvitv2-s-1000-official",
            "coreml": "coreml-v1",
        }
        default_version = default_versions[backend]
        return cls(
            inference_backend=backend,
            model_version=os.getenv("MODEL_VERSION", default_version).strip() or default_version,
            onnx_model_path=Path(model_path).expanduser() if model_path else None,
            pytorch_model_path=(
                Path(pytorch_model_path).expanduser() if pytorch_model_path else None
            ),
            pytorch_device=pytorch_device,
            coreml_model_path=Path(coreml_model_path).expanduser() if coreml_model_path else None,
            model_manifest_path=Path(model_manifest_path).expanduser() if model_manifest_path else None,
            coreml_compute_units=coreml_compute_units,
            input_framing=input_framing,
            decision_policy_path=Path(decision_policy_path).expanduser() if decision_policy_path else None,
            label_map_path=Path(label_path).expanduser() if label_path else None,
            labels_verified=_bool_env("LABELS_VERIFIED", False),
            confidence_threshold=_float_env("CONFIDENCE_THRESHOLD", 0.70),
            margin_threshold=_float_env("MARGIN_THRESHOLD", 0.15),
            allowed_origins=origins,
            max_frame_bytes=_int_env("MAX_FRAME_BYTES", 256 * 1024),
            max_message_bytes=_int_env("MAX_MESSAGE_BYTES", 6 * 1024 * 1024),
            collection_enabled=_bool_env("COLLECTION_ENABLED", False),
            collection_dir=Path(
                os.getenv("COLLECTION_DIR", "ml/data/collected/sales30")
            ).expanduser(),
            collection_target_per_hand=_int_env("COLLECTION_TARGET_PER_HAND", 50),
            openai_api_key=os.getenv("OPENAI_API_KEY", "").strip() or None,
            openai_model=os.getenv("OPENAI_MODEL", "").strip() or None,
            sentence_rules=sentence_rules,
            app_environment=environment,
            workspace_id=_workspace_id_env(),
            workspace_name=_workspace_name_env(),
            database_url=os.getenv("DATABASE_URL", "sqlite:///./data/vsign-platform.db").strip()
            or "sqlite:///./data/vsign-platform.db",
            database_auto_create=_bool_env("DATABASE_AUTO_CREATE", environment == "development"),
            auth_required=auth_required,
            local_admin_enabled=_bool_env("LOCAL_ADMIN_ENABLED", environment == "development" and not auth_required),
            local_admin_role=os.getenv("LOCAL_ADMIN_ROLE", "admin").strip(),
            auth_cookie_secure=_bool_env("AUTH_COOKIE_SECURE", environment == "production"),
            auth_session_ttl_seconds=_int_env("AUTH_SESSION_TTL_SECONDS", 8 * 60 * 60),
            bootstrap_admin_email=os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip().casefold() or None,
            bootstrap_admin_password=os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "").strip() or None,
            bootstrap_admin_name=os.getenv("BOOTSTRAP_ADMIN_NAME", "Workspace Admin").strip()
            or "Workspace Admin",
            dev_test_enabled=_bool_env("DEV_TEST_ENABLED", False),
            dev_test_dir=Path(os.getenv("DEV_TEST_DIR", "ml/data/dev-tests/manual")).expanduser(),
            model_registry_roots=tuple(Path(p.strip()).expanduser() for p in os.getenv("MODEL_REGISTRY_ROOTS", "ml/artifacts").split(",") if p.strip()),
            model_evaluation_roots=tuple(Path(p.strip()).expanduser() for p in os.getenv("MODEL_EVALUATION_ROOTS", "ml/evaluations").split(",") if p.strip()),
            model_deployment_worker=_bool_env("MODEL_DEPLOYMENT_WORKER", False),
            model_deployment_target=os.getenv("MODEL_DEPLOYMENT_TARGET", "production-local").strip(),
            model_deployment_runtime_url=os.getenv("MODEL_DEPLOYMENT_RUNTIME_URL", "http://127.0.0.1:8002").strip(),
            integration_encryption_key=_integration_key_env(),
            display_ice_servers=_ice_servers_env(),
            runtime_role=os.getenv("RUNTIME_ROLE", "full").strip().lower() or "full",
            inference_token_secret=_inference_token_secret_env(),
        )
