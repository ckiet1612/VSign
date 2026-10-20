from __future__ import annotations

import json
import os
import socket
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("target", ["backend", "web"])
def test_dev_test_launchers_isolate_ports_and_pin_feature_flags(tmp_path, target):
    repository = Path.cwd()
    project = tmp_path / "project"
    (project / "scripts").mkdir(parents=True)
    (project / "apps/web").mkdir(parents=True)
    (project / ".venv/bin").mkdir(parents=True)
    (project / ".venv/bin/python").symlink_to(repository / ".venv/bin/python")
    launcher = project / "scripts" / f"run_dev_test_{target}.sh"
    launcher.write_text((repository / "scripts" / launcher.name).read_text())
    receiver = tmp_path / "receiver.js"
    receiver.write_text('console.log(JSON.stringify({cwd:process.cwd(),args:process.argv.slice(2),env:process.env}));')
    fake = f'#!/bin/sh\nexec node "{receiver}" "$@"\n'
    (project / "scripts/run_coreml_local.sh").write_text(fake)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    (binaries / "npm").write_text(fake)
    (binaries / "npm").chmod(0o755)
    with socket.socket() as handle:
        handle.bind(("127.0.0.1", 0))
        port = handle.getsockname()[1]
    env = {**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}", "INFERENCE_HOST": "0.0.0.0",
           "APP_ENV": "production", "DEV_TEST_ENABLED": "false", "COLLECTION_ENABLED": "true",
           "VITE_PUBLIC_DEMO": "true", "INFERENCE_PORT": str(port), "DEV_TEST_WEB_PORT": "5174"}
    result = subprocess.run(["bash", str(launcher)], env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    runtime = json.loads(result.stdout)
    if target == "backend":
        assert runtime["env"]["APP_ENV"] == "development"
        assert runtime["env"]["DEV_TEST_ENABLED"] == "true"
        assert runtime["env"]["COLLECTION_ENABLED"] == "false"
        assert runtime["env"]["INFERENCE_HOST"] == "127.0.0.1"
        assert runtime["env"]["INFERENCE_PORT"] == str(port)
        assert runtime["env"]["DEV_TEST_DIR"] == str(project / "ml/data/dev-tests/manual")
        assert runtime["env"]["ALLOWED_ORIGINS"] == "http://localhost:5174,http://127.0.0.1:5174"
    else:
        assert runtime["cwd"] == str(project / "apps/web")
        assert runtime["env"]["VITE_PUBLIC_DEMO"] == "false"
        assert runtime["env"]["VITE_INFERENCE_HTTP_URL"] == f"http://127.0.0.1:{port}"
        assert runtime["args"] == ["run", "dev", "--", "--host", "127.0.0.1", "--port", "5174", "--strictPort"]
