from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import signal
import shlex
import time
from pathlib import Path

import pytest


@pytest.mark.parametrize("failure", [None, "artifact", "startup", "managed_startup", "missing_runtime", "terminate", "interrupt", "repeated_stop"])
def test_coreml_launcher_pins_measured_settings_and_falls_back_to_original(tmp_path, failure) -> None:
    from ml.scripts.personal_coreml import package_hash, verify_source

    repository = Path.cwd()
    project = tmp_path / "project"
    original = project / "original"
    candidate = project / "candidate"
    for directory in [project / "scripts", project / ".venv/bin", project / ".venv-coreml/bin",
                      project / "contracts/v1", project / "services/inference", original, candidate / "benchmark_r2"]:
        directory.mkdir(parents=True, exist_ok=True)
    (project / "ml").symlink_to(repository / "ml", target_is_directory=True)
    (project / "services/inference/app").symlink_to(repository / "services/inference/app", target_is_directory=True)
    labels = json.loads((repository / "contracts/v1/sales30.labels.json").read_text())
    (project / "contracts/v1/sales30.labels.json").write_text(json.dumps(labels))
    (original / "labels.json").write_text(json.dumps(labels + ["Không ký hiệu"]))
    (original / "best.pt").write_bytes(b"original-model")
    (original / "summary.json").write_text(json.dumps({"deployment_gate_passed": True,
        "model_version": "verified-personal", "best_sha256": hashlib.sha256(b"original-model").hexdigest()}))
    source = verify_source(original)
    package = candidate / "model.mlpackage"
    package.mkdir()
    (package / "weights").write_bytes(b"converted-model")
    digest = package_hash(package)
    (candidate / "labels.json").write_text((original / "labels.json").read_text())
    (candidate / "conversion.json").write_text(json.dumps({"passed": True,
        "source_unchanged": True, "source": source, "package_sha256": digest}))
    (candidate / "benchmark_r2/benchmark.json").write_text(json.dumps({"deployment_gate_passed": True,
        "source_unchanged": True, "source": source, "package_sha256": digest, "selected_compute_units": "ALL",
        "fixture_sha256": "a" * 64,
        "baseline_for_gate": {"median_ms": 800., "p95_ms": 1000.},
        "selected_timing": {"median_ms": 400., "p95_ms": 500.},
        "results": [{"backend": "coreml", "compute_units": "ALL", "parity_passed": True,
                     "median_ms": 400., "p95_ms": 500., "source": source, "fixture_sha256": "a" * 64},
                    {"backend": "pytorch", "parity_passed": True, "median_ms": 800., "p95_ms": 1000., "source": source, "fixture_sha256": "a" * 64},
                    {"backend": "pytorch", "parity_passed": True, "median_ms": 850., "p95_ms": 1100., "source": source, "fixture_sha256": "a" * 64}]}))
    for name in ["run_coreml_local.sh", "run_personal_local.sh"]:
        (project / "scripts" / name).write_text((repository / "scripts" / name).read_text())
    python = project / ".venv/bin/python"
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    python.chmod(0o755)
    old_uvicorn = project / ".venv/bin/uvicorn"
    old_uvicorn.write_text('#!/bin/sh\nprintf "pytorch:%s:%s:%s\\n" "$MODEL_VERSION" "$CONFIDENCE_THRESHOLD" "$MARGIN_THRESHOLD"\n')
    old_uvicorn.chmod(0o755)
    coreml_uvicorn = project / ".venv-coreml/bin/uvicorn"
    if failure != "missing_runtime":
        coreml_uvicorn.write_text('#!/bin/sh\nprintf "coreml:%s:%s:%s:%s\\n" "$MODEL_VERSION" "$COREML_COMPUTE_UNITS" "$CONFIDENCE_THRESHOLD" "$MARGIN_THRESHOLD"\n'
                                 + ('exit 50\n' if failure in {"startup", "managed_startup"} else 'exit 0\n'))
        coreml_uvicorn.chmod(0o755)
    if failure in {"terminate", "interrupt", "repeated_stop"}:
        native_code = ('import os,signal,sys,time; from pathlib import Path; '
                       'signal.signal(signal.SIGTERM,lambda *_:sys.exit(0)); '
                       'Path(os.environ["RUNTIME_PID_PATH"]).write_text(str(os.getpid()))\n'
                       'while True: time.sleep(.05)\n')
        coreml_uvicorn.write_text(f'#!/bin/sh\nexec "{sys.executable}" -c {shlex.quote(native_code)}\n')
        coreml_uvicorn.chmod(0o755)
        if failure == "repeated_stop":
            native_code = ('import os,signal,sys,time; from pathlib import Path\n'
                           'def stop(*_):\n'
                           ' signal.signal(signal.SIGTERM,signal.SIG_IGN)\n'
                           ' Path(os.environ["STOP_READY_PATH"]).touch()\n'
                           ' time.sleep(1)\n'
                           ' sys.exit(0)\n'
                           'signal.signal(signal.SIGTERM,stop)\n'
                           'Path(os.environ["RUNTIME_PID_PATH"]).write_text(str(os.getpid()))\n'
                           'while True: time.sleep(.05)\n')
            coreml_uvicorn.write_text(f'#!/bin/sh\nexec "{sys.executable}" -c {shlex.quote(native_code)}\n')
    if failure == "artifact":
        (package / "weights").write_bytes(b"corrupt")
    env = {**os.environ, "PERSONAL_MODEL_DIR": str(original), "COREML_MODEL_DIR": str(candidate),
           "COREML_COMPUTE_UNITS": "CPU_ONLY", "CONFIDENCE_THRESHOLD": ".01", "MARGIN_THRESHOLD": ".01"}
    if failure == "managed_startup":
        env["MODEL_DEPLOYMENT_WORKER"]="true"
    if failure in {"terminate", "interrupt", "repeated_stop"}:
        pid_path = tmp_path / "runtime.pid"
        env["RUNTIME_PID_PATH"] = str(pid_path)
        stop_path = tmp_path / "stopping"
        env["STOP_READY_PATH"] = str(stop_path)
        launcher = subprocess.Popen(["bash", str(project / "scripts/run_coreml_local.sh")], env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            for _ in range(100):
                if pid_path.exists():
                    break
                time.sleep(.05)
            assert pid_path.exists(), "Native runtime did not start"
            child_pid = int(pid_path.read_text())
            launcher.send_signal(signal.SIGINT if failure == "interrupt" else signal.SIGTERM)
            if failure == "repeated_stop":
                for _ in range(100):
                    if stop_path.exists():
                        break
                    time.sleep(.01)
                assert stop_path.exists()
                launcher.send_signal(signal.SIGINT)
                time.sleep(.1)
                assert launcher.poll() is None, "Launcher exited before native child shutdown"
            launcher.wait(timeout=5)
            for _ in range(40):
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(.05)
            else:
                pytest.fail("Stopping launcher left its runtime child running")
            assert (original / "best.pt").read_bytes() == b"original-model"
        finally:
            try:
                os.killpg(launcher.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            launcher.wait(timeout=5)
        return
    result = subprocess.run(["bash", str(project / "scripts/run_coreml_local.sh")],
                            env=env, capture_output=True, text=True, timeout=30)
    if failure == "managed_startup":
        assert result.returncode != 0
        assert "pytorch:" not in result.stdout
        assert (original / "best.pt").read_bytes() == b"original-model"
        return
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    if failure is None:
        assert lines == ["coreml:verified-personal:ALL:0.40:0.0"]
    elif failure == "startup":
        assert lines == ["coreml:verified-personal:ALL:0.40:0.0", "pytorch:verified-personal:0.40:0.0"]
    else:
        assert lines == ["pytorch:verified-personal:0.40:0.0"]
    assert (original / "best.pt").read_bytes() == b"original-model"
