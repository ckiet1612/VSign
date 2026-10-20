"""Benchmark the verified personal model in fresh CPU processes and a worker thread."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

import numpy as np


def timing_summary(values: list[float]) -> dict:
    if not values or any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("Timing samples must be finite and nonnegative")
    return {"samples": len(values), "median_ms": float(np.median(values)),
            "p95_ms": float(np.percentile(values, 95))}


def prediction_delta(reference: dict, actual: dict, tolerance: float = 1e-5) -> float:
    if any(reference[key] != actual[key] for key in ("status", "label")):
        raise ValueError("Prediction decision changed")
    if [item["label"] for item in reference["top_k"]] != [item["label"] for item in actual["top_k"]]:
        raise ValueError("Prediction suggestions changed")
    pairs = [(reference["confidence"], actual["confidence"])]
    pairs.extend((old["confidence"], new["confidence"])
                 for old, new in zip(reference["top_k"], actual["top_k"]))
    deltas = []
    for old, new in pairs:
        if old is None or new is None:
            if old != new:
                raise ValueError("Prediction confidence missing")
            continue
        if not math.isfinite(old) or not math.isfinite(new):
            raise ValueError("Prediction confidence is not finite")
        deltas.append(abs(old - new))
    delta = max(deltas, default=0.)
    if delta > tolerance:
        raise ValueError(f"Prediction probability changed by {delta}")
    return delta


def run_worker(args) -> dict:
    # Import torch only after the parent sets OMP_NUM_THREADS for this process.
    import torch
    from app.backends.pytorch import PyTorchInferenceBackend
    from app.config import Settings
    from app.validation import close_frames, decode_frames
    from ml.scripts.smoke_personal_runtime import encode_frames, validate_metadata

    summary = json.loads((args.artifact_dir / "summary.json").read_text(encoding="utf-8"))
    labels = json.loads((args.artifact_dir / "labels.json").read_text(encoding="utf-8"))
    baseline = json.loads(args.baseline_json.read_text(encoding="utf-8"))
    digest = hashlib.sha256((args.artifact_dir / "best.pt").read_bytes()).hexdigest()
    if not summary["deployment_gate_passed"] or digest != summary["best_sha256"]:
        raise ValueError("Unverified personal checkpoint")
    if not baseline.get("passed") or not baseline.get("samples"):
        raise ValueError("A successful nonempty baseline replay is required")
    validate_metadata(baseline["metadata"], summary["model_version"], labels)
    encoded = [encode_frames(Path(sample["path"])) for sample in baseline["samples"]]
    max_frame_bytes = Settings().max_frame_bytes
    startup = perf_counter()
    backend = PyTorchInferenceBackend(
        args.artifact_dir / "best.pt", args.artifact_dir / "labels.json",
        summary["model_version"], .7, .15, device="cpu", labels_verified=True,
    )
    startup_ms = (perf_counter() - startup) * 1000

    def infer(index: int):
        started = perf_counter()
        frames = decode_frames(encoded[index], max_frame_bytes)
        decoded = perf_counter()
        try:
            prediction = backend.predict(frames, index)
            finished = perf_counter()
            return asdict(prediction), {
                **backend.last_timings_ms,
                "decode_ms": (decoded - started) * 1000,
                "request_ms": (finished - started) * 1000,
            }, torch.get_num_threads()
        finally:
            close_frames(frames)

    measurements = []
    max_delta = 0.
    worker_threads = None
    with ThreadPoolExecutor(max_workers=1) as pool:
        for index in range(2):
            pool.submit(infer, index % len(encoded)).result()
        for round_index in range(args.rounds):
            for index, sample in enumerate(baseline["samples"]):
                actual, timings, worker_threads = pool.submit(infer, index).result()
                max_delta = max(max_delta, prediction_delta(sample["reply"], actual))
                measurements.append({"round": round_index, "path": sample["path"],
                                     "timings_ms": timings, "prediction": actual})
    if worker_threads != args.threads[0]:
        raise ValueError(f"Worker uses {worker_threads} threads instead of {args.threads[0]}")
    return {"threads": worker_threads, "startup_with_warmup_ms": startup_ms,
            "model_version": summary["model_version"], "checkpoint_sha256": digest,
            "prediction_parity_passed": True, "max_probability_delta": max_delta,
            "stages": {key: timing_summary([item["timings_ms"][key] for item in measurements])
                       for key in measurements[0]["timings_ms"]}, "measurements": measurements}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, default=Path("ml/artifacts/sales30_personal_v1"))
    parser.add_argument("--baseline-json", type=Path, required=True)
    parser.add_argument("--threads", type=int, nargs="+", default=[1, 2, 4, 8])
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.rounds < 1 or any(value < 1 or value > 64 for value in args.threads):
        parser.error("Use positive rounds and 1-64 CPU threads")
    if args.worker:
        print(json.dumps(run_worker(args), ensure_ascii=False))
        return 0
    if args.output_json is None or args.output_json.exists():
        parser.error("Use a new --output-json path")
    results = []
    for threads in args.threads:
        env = {**os.environ, "OMP_NUM_THREADS": str(threads)}
        env["PYTHONPATH"] = "services/inference:." + os.pathsep + env.get("PYTHONPATH", "")
        command = [sys.executable, "-m", "ml.scripts.benchmark_personal_cpu", "--worker",
                   "--artifact-dir", str(args.artifact_dir), "--baseline-json", str(args.baseline_json),
                   "--threads", str(threads), "--rounds", str(args.rounds)]
        completed = subprocess.run(command, env=env, capture_output=True, text=True,
                                   check=True, timeout=1200)
        result = json.loads(completed.stdout)
        if completed.stderr:
            print(completed.stderr, file=sys.stderr, end="")
        results.append(result)
        print(json.dumps({"threads": threads, "request": result["stages"]["request_ms"],
                          "parity": result["prediction_parity_passed"]}), flush=True)
    best = min(results, key=lambda item: item["stages"]["request_ms"]["median_ms"])
    report = {"recommended_threads": best["threads"], "results": results,
              "baseline_json": str(args.baseline_json),
              "baseline_sha256": hashlib.sha256(args.baseline_json.read_bytes()).hexdigest(),
              "environment": {"platform": sys.platform, "python": sys.version},
              "limits": "Serial warmed worker-thread replay; excludes camera, segmentation, encode, queue and network. Training clips verify parity, not independent accuracy. P95 is descriptive for this small sample."}
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    with args.output_json.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"recommended_threads": best["threads"], "output": str(args.output_json)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
