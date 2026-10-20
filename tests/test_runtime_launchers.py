from pathlib import Path

import hashlib
import json
import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("threads,expected", [(None, "8"), ("4", "4"), ("1", "1"), ("64", "64"), ("0", None), ("65", None), ("bad", None)])
def test_personal_launcher_applies_measured_thread_default_and_validates_overrides(tmp_path, threads, expected) -> None:
    project = tmp_path / "project"
    model = project / "model"
    for directory in [project / "scripts", project / ".venv/bin", project / "contracts/v1", model]:
        directory.mkdir(parents=True)
    labels_content = Path("contracts/v1/sales30.labels.json").read_text(encoding="utf-8")
    (project / "contracts/v1/sales30.labels.json").write_text(labels_content, encoding="utf-8")
    script = project / "scripts/run_personal_local.sh"
    script.write_text(Path("scripts/run_personal_local.sh").read_text(encoding="utf-8"), encoding="utf-8")
    (project / ".venv/bin/python").symlink_to(Path(sys.executable).resolve())
    uvicorn = project / ".venv/bin/uvicorn"
    uvicorn.write_text('#!/bin/sh\nprintf "%s\\n" "$OMP_NUM_THREADS"\n')
    uvicorn.chmod(0o755)
    (model / "best.pt").write_bytes(b"verified-model")
    (model / "labels.json").write_text(json.dumps(json.loads(labels_content) + ["Không ký hiệu"]))
    (model / "summary.json").write_text(json.dumps({"deployment_gate_passed": True,
        "best_sha256": hashlib.sha256(b"verified-model").hexdigest(), "model_version": "verified-version"}))
    env = {key: value for key, value in os.environ.items() if key != "OMP_NUM_THREADS"}
    env["PERSONAL_MODEL_DIR"] = str(model)
    if threads is not None:
        env["OMP_NUM_THREADS"] = threads
    result = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=20)
    if expected is None:
        assert result.returncode != 0
        assert "OMP_NUM_THREADS" in result.stderr
        assert not result.stdout
    else:
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == expected



@pytest.mark.parametrize("declared,expected", [(None, "center-square"), ("trim-bodycrop-v1", "trim-bodycrop-v1"), ("stretch", None)])
def test_personal_launcher_exports_checkpoint_input_framing(tmp_path, declared, expected) -> None:
    project = tmp_path / "project"
    model = project / "model"
    for directory in [project / "scripts", project / ".venv/bin", project / "contracts/v1", model]:
        directory.mkdir(parents=True)
    labels_content = Path("contracts/v1/sales30.labels.json").read_text(encoding="utf-8")
    (project / "contracts/v1/sales30.labels.json").write_text(labels_content, encoding="utf-8")
    script = project / "scripts/run_personal_local.sh"
    script.write_text(Path("scripts/run_personal_local.sh").read_text(encoding="utf-8"), encoding="utf-8")
    (project / ".venv/bin/python").symlink_to(Path(sys.executable).resolve())
    uvicorn = project / ".venv/bin/uvicorn"
    uvicorn.write_text('#!/bin/sh\nprintf "%s:%s\\n" "$MODEL_VERSION" "$INPUT_FRAMING"\n')
    uvicorn.chmod(0o755)
    (model / "best.pt").write_bytes(b"verified-model")
    (model / "labels.json").write_text(json.dumps(json.loads(labels_content) + ["Không ký hiệu"]))
    summary = {"deployment_gate_passed": True, "best_sha256": hashlib.sha256(b"verified-model").hexdigest(),
               "model_version": "verified-version"}
    if declared is not None:
        summary["input_framing"] = declared
    (model / "summary.json").write_text(json.dumps(summary))
    env = {key: value for key, value in os.environ.items() if key not in {"OMP_NUM_THREADS", "INPUT_FRAMING"}}
    env["PERSONAL_MODEL_DIR"] = str(model)
    result = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=20)
    if expected is None:
        assert result.returncode != 0
        assert not result.stdout
    else:
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == f"verified-version:{expected}"

def test_onnx_launcher_defaults_to_accepted_seated_v3_epoch5_artifact() -> None:
    script = Path("scripts/run_onnx_local.sh").read_text(encoding="utf-8")
    env_example = Path(".env.example").read_text(encoding="utf-8")
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert 'model_dir="${project_dir}/ml/artifacts/sales30_seated_v3"' in script
    assert (
        'MODEL_VERSION="${MODEL_VERSION:-sales30-mvitv2s-seated-v3-epoch5}"'
        in script
    )
    assert 'if [[ ! -f "${model_path}.data" ]]' not in script

    assert "MODEL_VERSION=sales30-mvitv2s-seated-v3-epoch5" in env_example
    assert "ONNX_MODEL_PATH=ml/artifacts/sales30_seated_v3/model.onnx" in env_example
    assert "LABEL_MAP_PATH=ml/artifacts/sales30_seated_v3/labels.json" in env_example

    assert "MODEL_VERSION:-sales30-mvitv2s-seated-v3-epoch5" in compose
    assert "./ml/artifacts/sales30_seated_v3:/models:ro" in compose
