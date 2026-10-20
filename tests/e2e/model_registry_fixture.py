"""Disposable real-ONNX runtime for workspace_models.mjs; never imports real artifacts."""

from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import secrets

import onnx
from onnx import TensorProto, helper
from PIL import Image

from app.backends import create_backend
from app.backends.base import DecodedFrame
from app.config import Settings
from app.model_gate import evaluate_gate
from app.model_manifest import labels_digest
from app.registry_artifacts import PREPROCESSING_VERSION, RegistryManifest, sha256_file
from app.platform_auth import bootstrap_platform
from app.platform_db import Membership, create_database
from argon2 import PasswordHasher
from sqlalchemy import select


def write_json(path: Path, body: object) -> None:
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def constant_onnx(path: Path, logits: list[float]) -> None:
    output = helper.make_tensor("constant_logits", TensorProto.FLOAT, [1, 2], logits)
    graph = helper.make_graph(
        [helper.make_node("Constant", [], ["logits"], value=output)],
        path.stem,
        [helper.make_tensor_value_info("clip", TensorProto.FLOAT, [1, 3, 16, 224, 224])],
        [helper.make_tensor_value_info("logits", TensorProto.FLOAT, [1, 2])],
    )
    model = helper.make_model(graph, producer_name="vsign-isolated-models-e2e", opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    onnx.save(model, path)


def prepare(output: Path, runtime_url: str, origin: str) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    registry = output / "registry"
    reports = output / "evaluation"
    # A repeated run must get a new fixture directory, not overwrite a registered artifact.
    registry.mkdir()
    reports.mkdir()
    labels = ["Hello", "Bye"]
    labels_path = registry / "labels.json"
    write_json(labels_path, labels)
    tag = secrets.token_hex(6)
    manifests = {}
    for name, logits in (("baseline", [8.0, -8.0]), ("candidate", [-8.0, 8.0])):
        artifact = registry / f"{name}.onnx"
        constant_onnx(artifact, logits)
        manifest = RegistryManifest(
            model_version=f"e2e-{name}-{tag}", backend="onnx",
            artifact_sha256=sha256_file(artifact), labels_sha256=labels_digest(labels),
            labels_file_sha256=sha256_file(labels_path),
            protocol_version="1.0", frame_count=16, frame_size=224,
            preprocessing_version=PREPROCESSING_VERSION, confidence_threshold=0.7, margin_threshold=0.15,
            source_run_id="observed-baseline" if name == "baseline" else f"synthetic-e2e-{tag}",
            status="production" if name == "baseline" else "candidate",
        )
        write_json(registry / f"{name}.manifest.json", manifest.model_dump())
        manifests[name] = manifest

    baseline, candidate = manifests["baseline"], manifests["candidate"]
    metrics = {
        "macro_f1": 0.95, "false_accept_rate": 0.01, "latency_p95_ms": 100.0,
        "per_class": [{"label": label, "support": 10, "recall": 0.95} for label in labels],
    }
    report = {
        "schema_version": "1", "candidate_artifact_sha256": candidate.artifact_sha256,
        "baseline_artifact_sha256": baseline.artifact_sha256, "labels_sha256": candidate.labels_sha256,
        "source_run_id": candidate.source_run_id, "preprocessing_version": candidate.preprocessing_version,
        "protocol_version": candidate.protocol_version, "confidence_threshold": candidate.confidence_threshold,
        "margin_threshold": candidate.margin_threshold, "baseline_confidence_threshold": baseline.confidence_threshold,
        "baseline_margin_threshold": baseline.margin_threshold,
        "dataset_snapshot_sha256": hashlib.sha256(b"synthetic-e2e-only-no-real-evaluation-dataset").hexdigest(),
        "held_out": True, "positive_count": 20, "independent_negatives": True, "negative_count": 10,
        "baseline": metrics, "candidate": metrics,
        "fixture_only": True, "evidence_note": "Synthetic gate input, not measured accuracy or independent evaluation.",
    }
    assert evaluate_gate(report, candidate, baseline, labels)["passed"]
    write_json(reports / "passing.json", report)
    failing = {**report, "held_out": False, "independent_negatives": False, "negative_count": 0}
    assert not evaluate_gate(failing, candidate, baseline, labels)["passed"]
    write_json(reports / "failing.json", failing)
    (reports / "invalid.json").write_text("{broken", encoding="utf-8")

    settings = Settings(
        inference_backend="onnx", model_version=baseline.model_version,
        onnx_model_path=registry / "baseline.onnx", label_map_path=labels_path, labels_verified=True,
        model_manifest_path=registry / "baseline.manifest.json", confidence_threshold=0.7, margin_threshold=0.15,
        app_environment="development", workspace_id=f"models-e2e-{tag}", workspace_name="VSign models E2E",
        database_url=f"sqlite:///{output / 'platform.db'}", database_auto_create=True,
        allowed_origins=(origin,), auth_required=False, auth_cookie_secure=False,
        bootstrap_admin_email=f"models-{tag}@example.com", bootstrap_admin_password=f"Models-{secrets.token_urlsafe(24)}",
        bootstrap_admin_name="Isolated Models Owner", collection_enabled=False, collection_labels=tuple(labels),
        collection_dir=output / "unused-collection", dev_test_enabled=False, dev_test_dir=output / "unused-dev-test",
        openai_api_key=None, model_registry_roots=(registry,), model_evaluation_roots=(reports,),
        model_deployment_worker=True, model_deployment_target=f"e2e-production-{tag}", model_deployment_runtime_url=runtime_url,
    )
    database = create_database(settings.database_url)
    database.create_schema()
    bootstrap_platform(database, settings, PasswordHasher())
    with database.session() as session:
        session.scalar(select(Membership)).role = "model_admin"
        session.commit()
    database.dispose()
    backend_checks = []
    with Image.new("RGB", (224, 224), color="white") as image:
        frames = [DecodedFrame(image=image, encoded_bytes=b"") for _ in range(16)]
        for name, expected in (("baseline", "Hello"), ("candidate", "Bye")):
            backend = create_backend(replace(settings, model_version=manifests[name].model_version,
                                             onnx_model_path=registry / f"{name}.onnx", model_manifest_path=None))
            prediction = backend.predict(frames, 0)
            assert backend.name == "onnx" and not backend.is_mock and not backend.candidate_labels_unverified
            assert prediction.label == expected
            backend_checks.append({"model": name, "version": backend.model_version, "label": prediction.label,
                                   "backend_class": type(backend).__name__, "input_shape": [1, 3, 16, 224, 224], "output_shape": [1, 2]})

    config = {
        "output": str(output), "runtime_url": runtime_url, "web_origin": origin,
        "workspace_id": settings.workspace_id, "workspace_name": settings.workspace_name,
        "target_id": settings.model_deployment_target,
        "email": settings.bootstrap_admin_email, "password": settings.bootstrap_admin_password,
        "database_path": str(output / "platform.db"), "registry_root": str(registry), "evaluation_root": str(reports),
        "labels_path": str(labels_path), "labels": labels,
        "baseline": {"version": baseline.model_version, "artifact_path": str(registry / "baseline.onnx"),
                     "manifest_path": str(registry / "baseline.manifest.json"), "sha256": baseline.artifact_sha256},
        "candidate": {"version": candidate.model_version, "artifact_path": str(registry / "candidate.onnx"),
                      "manifest_path": str(registry / "candidate.manifest.json"), "sha256": candidate.artifact_sha256},
        "reports": {"passing": str(reports / "passing.json"), "failing": str(reports / "failing.json"),
                    "invalid": str(reports / "invalid.json"), "missing": str(reports / "missing.json")},
        "backend_checks": backend_checks,
        "limits": "Temporary ONNX constants and synthetic gate input only; no real camera, dataset, training, production model or live service.",
    }
    config_path = output / "config.json"
    write_json(config_path, config)
    config_path.chmod(0o600)
    print(json.dumps({"config": str(config_path), "runtime_url": runtime_url, "prepared": True}), flush=True)
    return {"config": config, "settings": settings}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--prepare", action="store_true", help="Generate and check fixtures without starting a server")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535 or args.port in (8000, 8002, 8003):
        parser.error("Use an ephemeral non-production port")
    output = args.output.expanduser().resolve()
    if output == Path(__file__).resolve().parents[2] or output.is_relative_to(Path(__file__).resolve().parents[2]):
        parser.error("Fixture output must be outside the repository")
    fixture = prepare(output, f"http://127.0.0.1:{args.port}", args.origin)
    if args.prepare:
        return
    # main.py also constructs a module-level app; keep even that unused instance on disposable ONNX paths.
    settings = fixture["settings"]
    os.environ.update(
        APP_ENV="development", INFERENCE_BACKEND="onnx", MODEL_VERSION=settings.model_version,
        ONNX_MODEL_PATH=str(settings.onnx_model_path), LABEL_MAP_PATH=str(settings.label_map_path), LABELS_VERIFIED="true",
        MODEL_MANIFEST_PATH="", OPENAI_API_KEY="", MODEL_DEPLOYMENT_WORKER="false", COLLECTION_ENABLED="false",
        COLLECTION_DIR=str(settings.collection_dir), DEV_TEST_DIR=str(settings.dev_test_dir), DEV_TEST_ENABLED="false",
        MODEL_REGISTRY_ROOTS=str(output / "registry"), MODEL_EVALUATION_ROOTS=str(output / "evaluation"),
        MODEL_DEPLOYMENT_RUNTIME_URL=fixture["config"]["runtime_url"], DATABASE_URL=settings.database_url,
        WORKSPACE_ID=settings.workspace_id, WORKSPACE_NAME=settings.workspace_name, ALLOWED_ORIGINS=args.origin,
        CONFIDENCE_THRESHOLD="0.7", MARGIN_THRESHOLD="0.15", AUTH_REQUIRED="false", AUTH_COOKIE_SECURE="false",
        BOOTSTRAP_ADMIN_EMAIL="", BOOTSTRAP_ADMIN_PASSWORD="",
    )
    import uvicorn
    from app.main import create_app

    app = create_app(settings, runtime_backend_factory=create_backend)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info", access_log=False)


if __name__ == "__main__":
    main()
