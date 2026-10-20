import hashlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("failure", [None, "gate", "hash", "version", "time_wait", "busy"])
def test_launcher_isolated_from_default_backend_and_rejects_unverified_artifacts(tmp_path, failure):
    repository = Path.cwd()
    script = repository / "scripts/run_seated_personal_local.sh"
    assert script.is_file(), "The isolated seated candidate launcher is missing"
    project = tmp_path / "project"
    candidate = project / "candidate"
    for path in [project / "scripts", project / ".venv/bin", candidate]:
        path.mkdir(parents=True)
    (project / "scripts/run_seated_personal_local.sh").write_text(script.read_text())
    python = project / ".venv/bin/python"
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    python.chmod(0o755)
    runner = project / "scripts/run_coreml_local.sh"
    runner.write_text('#!/bin/sh\nprintf "%s\\n" "$INFERENCE_PORT" "$INFERENCE_HOST" "$PERSONAL_MODEL_DIR" "$APP_ENV" "$DEV_TEST_ENABLED" "$COLLECTION_ENABLED"\n')
    old = project / "original.pt"
    old.write_bytes(b"old checkpoint")
    (candidate / "best.pt").write_bytes(b"new checkpoint")
    labels = json.loads((repository / "contracts/v1/sales30.labels.json").read_text()) + ["Không ký hiệu"]
    (candidate / "labels.json").write_text(json.dumps(labels))
    (candidate / "summary.json").write_text(json.dumps({
        "deployment_gate_passed": failure != "gate", "source_files_unchanged": True,
        "model_version": "wrong" if failure == "version" else "sales30-mvitv2s-seated-personal-v1-head-epoch33",
        "best_sha256": "wrong" if failure == "hash" else hashlib.sha256(b"new checkpoint").hexdigest(),
    }))
    with socket.socket() as handle:
        handle.bind(("127.0.0.1", 0))
        port = handle.getsockname()[1]
    listener = None
    if failure in {"time_wait", "busy"}:
        listener = socket.socket()
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", port))
        listener.listen()
        if failure == "time_wait":
            client = socket.socket()
            client.connect(("127.0.0.1", port))
            accepted, _ = listener.accept()
            accepted.close()
            assert client.recv(1) == b""
            client.close()
            listener.close()
    env = {**os.environ, "SEATED_PERSONAL_MODEL_DIR": str(candidate), "INFERENCE_PORT": str(port),
           "PYTHONPATH": f"{repository}/services/inference:{repository}"}
    result = subprocess.run(["bash", str(project / "scripts/run_seated_personal_local.sh")],
                            env=env, capture_output=True, text=True, timeout=20)
    if listener:
        listener.close()
    if failure in {None, "time_wait"}:
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == [str(port), "127.0.0.1", str(candidate), "development", "true", "false"]
    else:
        assert result.returncode != 0
        assert result.stdout == ""
    assert old.read_bytes() == b"old checkpoint"
