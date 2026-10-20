"""Compare warmed CPU/Core ML replay in serial, isolated processes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

from ml.scripts.benchmark_personal_cpu import prediction_delta, timing_summary
from ml.scripts.personal_coreml import deployment_gate, package_hash, verify_source

# FP16 rounds every activation, so only probabilities get slack; decisions and top-3 stay exact.
PARITY_TOLERANCE = {"fp32": 1e-5, "fp16": 1e-2}


def select_candidate(baselines: list[dict], candidates: list[dict]):
    # Require a win against the faster observed CPU run, not thermal drift.
    baseline = {key: min(item[key] for item in baselines) for key in ("median_ms", "p95_ms")}
    eligible = [item for item in candidates if deployment_gate(baseline, item)]
    return min(eligible, key=lambda item: item["median_ms"]) if eligible else None, baseline


def run_worker(args) -> dict:
    from app.backends.coreml import CoreMLInferenceBackend
    from app.backends.pytorch import PyTorchInferenceBackend
    from app.validation import close_frames, decode_frames
    import torch

    identity = verify_source(args.artifact_dir)
    baseline = json.loads(args.baseline_json.read_text(encoding="utf-8"))
    fixture_data = args.fixture.read_bytes()
    fixture = json.loads(fixture_data)
    if fixture["baseline_sha256"] != hashlib.sha256(args.baseline_json.read_bytes()).hexdigest():
        raise ValueError("Benchmark fixture does not match the baseline")
    if [item["path"] for item in fixture["samples"]] != [item["path"] for item in baseline["samples"]]:
        raise ValueError("Benchmark samples changed")
    precision = "fp32"
    if args.backend == "coreml":
        precision = json.loads((args.coreml_dir / "conversion.json").read_text(encoding="utf-8"))["precision"]
    tolerance = PARITY_TOLERANCE[precision]
    startup = perf_counter()
    if args.backend == "pytorch":
        backend = PyTorchInferenceBackend(args.artifact_dir / "best.pt", args.artifact_dir / "labels.json",
            identity["model_version"], .7, .15, device="cpu", labels_verified=True)
    else:
        backend = CoreMLInferenceBackend(args.coreml_dir / "model.mlpackage", args.coreml_dir / "labels.json",
            identity["model_version"], .7, .15, compute_units=args.compute_units, labels_verified=True)
    startup_ms = (perf_counter() - startup) * 1000

    def infer(index):
        started = perf_counter()
        frames = decode_frames(fixture["samples"][index]["frames"], 256 * 1024)
        decoded = perf_counter()
        try:
            prediction = backend.predict(frames, index)
            finished = perf_counter()
            return asdict(prediction), {**backend.last_timings_ms,
                "decode_ms": (decoded - started) * 1000, "request_ms": (finished - started) * 1000}
        finally:
            close_frames(frames)

    measurements, errors = [], []
    max_delta = 0.
    with ThreadPoolExecutor(max_workers=1) as pool:
        for index in range(2):
            pool.submit(infer, index % len(fixture["samples"])).result()
        for round_index in range(args.rounds):
            for index, sample in enumerate(baseline["samples"]):
                actual, timings = pool.submit(infer, index).result()
                try:
                    max_delta = max(max_delta, prediction_delta(sample["reply"], actual, tolerance=tolerance))
                except ValueError as error:
                    errors.append({"path": sample["path"], "error": str(error)})
                measurements.append({"round": round_index, "path": sample["path"],
                                     "prediction": actual, "timings_ms": timings})
    stages = {key: timing_summary([item["timings_ms"][key] for item in measurements])
              for key in measurements[0]["timings_ms"]}
    return {"backend": args.backend, "compute_units": args.compute_units if args.backend == "coreml" else None,
            "precision": precision, "parity_tolerance": tolerance,
            "parity_passed": not errors, "parity_errors": errors, "max_probability_delta": max_delta,
            "median_ms": stages["request_ms"]["median_ms"], "p95_ms": stages["request_ms"]["p95_ms"],
            "stages": stages, "measurements": measurements, "startup_ms": startup_ms,
            "fixture_sha256": hashlib.sha256(fixture_data).hexdigest(), "source": identity,
            "environment": {"platform": platform.platform(), "python": sys.version,
                            "torch": torch.__version__, "omp_threads": os.environ["OMP_NUM_THREADS"]}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, default=Path("ml/artifacts/sales30_personal_v1"))
    parser.add_argument("--coreml-dir", type=Path, required=True)
    parser.add_argument("--baseline-json", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--coreml-python", type=Path, default=Path(".venv-coreml/bin/python"))
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--backend", choices=("pytorch", "coreml"), default="pytorch")
    parser.add_argument("--compute-units", choices=("ALL", "CPU_AND_GPU", "CPU_ONLY", "CPU_AND_NE"), default="ALL")
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--candidates", default="ALL,CPU_AND_GPU,CPU_ONLY,CPU_AND_NE",
                        help="Comma-separated Core ML compute units to bracket between the PyTorch runs")
    args = parser.parse_args(argv)
    if args.rounds < 1:
        parser.error("Use positive rounds")
    candidates = [item.strip() for item in args.candidates.split(",") if item.strip()]
    if not candidates or len(set(candidates)) != len(candidates) or any(
            item not in {"ALL", "CPU_AND_GPU", "CPU_ONLY", "CPU_AND_NE"} for item in candidates):
        parser.error("candidates must be distinct Core ML compute units")
    if args.worker:
        print(json.dumps(run_worker(args), ensure_ascii=False))
        return 0
    if args.output_dir is None or args.output_dir.exists():
        parser.error("Use a fresh output directory")
    from ml.scripts.smoke_personal_runtime import encode_frames, validate_metadata
    identity = verify_source(args.artifact_dir)
    before = json.loads(args.baseline_json.read_text(encoding="utf-8"))
    if before.get("passed") is not True or not before.get("samples"):
        raise ValueError("Need a successful nonempty baseline replay")
    validate_metadata(before["metadata"], identity["model_version"], identity["labels"])
    args.output_dir.mkdir(parents=True, exist_ok=False)
    args.fixture = args.output_dir / "fixture.json"
    fixture = {"baseline_sha256": hashlib.sha256(args.baseline_json.read_bytes()).hexdigest(),
               "samples": [{"path": item["path"], "frames": encode_frames(Path(item["path"]))} for item in before["samples"]]}
    with args.fixture.open("x", encoding="utf-8") as handle:
        json.dump(fixture, handle, ensure_ascii=False)
    results, failures = [], []
    configurations = [("pytorch", "ALL"), *(("coreml", units) for units in candidates), ("pytorch", "ALL")]
    for index, (backend, compute_units) in enumerate(configurations):
        # Resolving the venv's python symlink loses its site-packages.
        python = sys.executable if backend == "pytorch" else str(args.coreml_python.absolute())
        env = {**os.environ, "OMP_NUM_THREADS": "8", "PYTHONPATH": "services/inference:."}
        command = [python, "-u", "-m", "ml.scripts.benchmark_personal_coreml", "--worker",
                   "--artifact-dir", str(args.artifact_dir), "--coreml-dir", str(args.coreml_dir),
                   "--baseline-json", str(args.baseline_json), "--fixture", str(args.fixture),
                   "--backend", backend, "--compute-units", compute_units, "--rounds", str(args.rounds)]
        print(json.dumps({"starting": backend, "compute_units": compute_units}), flush=True)
        try:
            completed = subprocess.run(command, env=env, capture_output=True, text=True, timeout=1200)
            (args.output_dir / f"worker_{index}.log").write_text(completed.stderr, encoding="utf-8")
            if completed.returncode != 0:
                raise RuntimeError(completed.stderr[-4000:])
            result = json.loads(completed.stdout)
            with (args.output_dir / f"worker_{index}.json").open("x", encoding="utf-8") as handle:
                json.dump(result, handle, ensure_ascii=False, indent=2)
            results.append(result)
            print(json.dumps({key: result[key] for key in ("backend", "compute_units", "median_ms", "p95_ms", "parity_passed")}), flush=True)
        except Exception as error:
            failures.append({"backend": backend, "compute_units": compute_units,
                             "error": str(error), "traceback": traceback.format_exc()})
            print(json.dumps(failures[-1]), flush=True)
    baselines = [item for item in results if item["backend"] == "pytorch"]
    candidates = [item for item in results if item["backend"] == "coreml"]
    selected, gate_baseline = select_candidate(baselines, candidates) if len(baselines) == 2 and all(item["parity_passed"] for item in baselines) else (None, None)
    source_unchanged = verify_source(args.artifact_dir) == identity
    report = {"deployment_gate_passed": selected is not None and source_unchanged,
              "selected_compute_units": selected["compute_units"] if selected else None,
              "baseline_for_gate": gate_baseline,
              "selected_timing": {key: selected[key] for key in ("median_ms", "p95_ms")} if selected else None,
              "source": identity, "source_unchanged": source_unchanged,
              "package_sha256": package_hash(args.coreml_dir / "model.mlpackage"),
              "fixture_sha256": hashlib.sha256(args.fixture.read_bytes()).hexdigest(),
              "failures": failures, "results": [{key: value for key, value in item.items() if key != "measurements"} for item in results],
              "limits": "Serial warmed worker-thread replay: 20 training clips, two rounds per configuration. No camera, encoding, network, segmentation, load or independent-session accuracy claim. Each worker uses byte-identical encoded frames; CPU runs bracket Core ML runs."}
    with (args.output_dir / "benchmark.json").open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({key: report[key] for key in ("deployment_gate_passed", "selected_compute_units", "selected_timing")}), flush=True)
    return 0 if report["deployment_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
