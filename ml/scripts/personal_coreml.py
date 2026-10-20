"""Convert the verified personal checkpoint without changing the PyTorch runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import traceback
from pathlib import Path
from time import perf_counter

from app.backends.coreml_artifact import package_hash


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def verify_source(root: Path) -> dict:
    summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    labels = json.loads((root / "labels.json").read_text(encoding="utf-8"))
    expected = json.loads((PROJECT_ROOT / "contracts/v1/sales30.labels.json").read_text(encoding="utf-8"))
    if summary.get("deployment_gate_passed") is not True:
        raise ValueError("Source checkpoint has not passed its regression gate")
    if labels != expected + ["Không ký hiệu"]:
        raise ValueError("Source labels do not match the verified 31-label order")
    digest = hashlib.sha256((root / "best.pt").read_bytes()).hexdigest()
    if digest != summary["best_sha256"]:
        raise ValueError("Source checkpoint checksum changed")
    return {"model_version": summary["model_version"], "checkpoint_sha256": digest,
            "labels": labels, "labels_sha256": hashlib.sha256((root / "labels.json").read_bytes()).hexdigest()}


def deployment_gate(baseline: dict, candidate: dict) -> bool:
    if candidate.get("parity_passed") is not True:
        return False
    values = [baseline.get("median_ms"), baseline.get("p95_ms"),
              candidate.get("median_ms"), candidate.get("p95_ms")]
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0
           for value in values):
        return False
    return candidate["median_ms"] <= baseline["median_ms"] * .95 and candidate["p95_ms"] <= baseline["p95_ms"]


def finalize_conversion(report: dict, artifact_dir: Path) -> None:
    try:
        report["source_unchanged"] = verify_source(artifact_dir) == report["source"]
    except Exception as error:
        report["source_unchanged"] = False
        report["preservation_error"] = {"type": type(error).__name__, "message": str(error)}
    if not report["source_unchanged"] or "error" in report:
        report["passed"] = False


def verify_deployment(artifact_dir: Path, coreml_dir: Path, benchmark_path: Path) -> tuple[str, str]:
    source = verify_source(artifact_dir)
    conversion = json.loads((coreml_dir / "conversion.json").read_text(encoding="utf-8"))
    digest = package_hash(coreml_dir / "model.mlpackage")
    labels = json.loads((coreml_dir / "labels.json").read_text(encoding="utf-8"))
    if (conversion.get("passed") is not True or conversion.get("source_unchanged") is not True
            or conversion.get("source") != source or conversion.get("package_sha256") != digest
            or labels != source["labels"]):
        raise ValueError("Core ML artifact identity or conversion gate failed")
    report = json.loads(benchmark_path.read_text(encoding="utf-8"))
    units = report.get("selected_compute_units")
    brackets = [item for item in report.get("results", []) if item.get("backend") == "pytorch"]
    if len(brackets) != 2 or any(item.get("parity_passed") is not True or item.get("source") != source
                                 for item in brackets):
        raise ValueError("Core ML benchmark needs two verified PyTorch brackets")
    bracket_timings = [item.get(key) for item in brackets for key in ("median_ms", "p95_ms")]
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) or value <= 0 for value in bracket_timings):
        raise ValueError("Core ML benchmark has invalid baseline timings")
    recomputed_baseline = {key: min(item.get(key, 0) for item in brackets) for key in ("median_ms", "p95_ms")}
    if report.get("baseline_for_gate") != recomputed_baseline:
        raise ValueError("Core ML benchmark baseline does not match its PyTorch brackets")
    selected = [item for item in report.get("results", [])
                if item.get("backend") == "coreml" and item.get("compute_units") == units]
    fixture_digest = report.get("fixture_sha256")
    if (not isinstance(fixture_digest, str) or len(fixture_digest) != 64
            or any(char not in "0123456789abcdef" for char in fixture_digest)
            or any(item.get("fixture_sha256") != fixture_digest for item in brackets + selected)):
        raise ValueError("Core ML benchmark fixture identity does not match across workers")
    if (report.get("deployment_gate_passed") is not True or report.get("source_unchanged") is not True
            or report.get("source") != source or report.get("package_sha256") != digest
            or units not in {"ALL", "CPU_AND_GPU", "CPU_ONLY", "CPU_AND_NE"}
            or len(selected) != 1 or selected[0].get("source") != source or report.get("selected_timing") != {
                key: selected[0].get(key) for key in ("median_ms", "p95_ms")}
            or not deployment_gate(report.get("baseline_for_gate", {}), selected[0])):
        raise ValueError("Core ML benchmark gate failed; keep PyTorch")
    version = source["model_version"]
    if not isinstance(version, str) or not version or any(char in version for char in "\t\r\n"):
        raise ValueError("Invalid model version")
    return version, units


def _export_pool_forward(self, x, thw):
    import torch
    tensor_dim = x.dim()
    if tensor_dim == 3:
        x = x.unsqueeze(1)
    elif tensor_dim != 4:
        raise ValueError("Unexpected Pool tensor rank")
    # The sole split point in torchvision Pool is the leading class token.
    class_token, x = x[:, :, :1, :], x[:, :, 1:, :]
    x = x.transpose(2, 3)
    batch, heads, channels = x.shape[:3]
    x = x.reshape((batch * heads, channels) + thw).contiguous()
    if self.norm_before_pool and self.norm_act is not None:
        x = self.norm_act(x)
    x = self.pool(x)
    temporal, height, width = x.shape[2:]
    x = x.reshape(batch, heads, channels, -1).transpose(2, 3)
    x = torch.cat((class_token, x), dim=2)
    if not self.norm_before_pool and self.norm_act is not None:
        x = self.norm_act(x)
    if tensor_dim == 3:
        x = x.squeeze(1)
    return x, (temporal, height, width)


def prepare_export_model(model) -> None:
    from types import MethodType
    from torchvision.models.video.mvit import Pool
    for module in model.modules():
        if isinstance(module, Pool):
            module.forward = MethodType(_export_pool_forward, module)


def export_add_rel_pos(attn, q, q_thw, k_thw, rel_pos_h, rel_pos_w, rel_pos_t):
    import torch
    from torchvision.models.video.mvit import _interpolate

    qt, qh, qw = q_thw
    kt, kh, kw = k_thw
    embeddings = []
    for query_size, key_size, embedding in (
        (qh, kh, rel_pos_h), (qw, kw, rel_pos_w), (qt, kt, rel_pos_t)
    ):
        query_ratio = max(key_size / query_size, 1.)
        key_ratio = max(query_size / key_size, 1.)
        distance = torch.arange(query_size)[:, None] * query_ratio - (
            torch.arange(key_size)[None, :] + (1. - key_size)
        ) * key_ratio
        embeddings.append(_interpolate(embedding, int(2 * max(query_size, key_size) - 1))[distance.long()])
    rh, rw, rt = embeddings
    batch, heads, _, channels = q.shape
    combined = batch * heads
    queries = qt * qh * qw
    # Fold batch and heads: all reshape/matmul intermediates have rank <= 5.
    grid = q[:, :, 1:].reshape(combined, qt, qh, qw, channels)
    h_query = grid.permute(0, 2, 1, 3, 4).reshape(combined, qh, qt * qw, channels)
    h_relative = torch.matmul(h_query, rh.transpose(1, 2)).reshape(combined, qh, qt, qw, kh)
    h_relative = h_relative.permute(0, 2, 1, 3, 4).reshape(combined, queries, kh)
    w_query = grid.permute(0, 3, 1, 2, 4).reshape(combined, qw, qt * qh, channels)
    w_relative = torch.matmul(w_query, rw.transpose(1, 2)).reshape(combined, qw, qt, qh, kw)
    w_relative = w_relative.permute(0, 2, 3, 1, 4).reshape(combined, queries, kw)
    t_query = grid.reshape(combined, qt, qh * qw, channels)
    t_relative = torch.matmul(t_query, rt.transpose(1, 2)).reshape(combined, queries, kt)
    # Gather each key's axis contribution without the original rank-8 broadcast.
    key_indices = torch.arange(kt * kh * kw)
    relative = (h_relative.index_select(2, ((key_indices // kw) % kh).to(torch.int32))
                + w_relative.index_select(2, (key_indices % kw).to(torch.int32))
                + t_relative.index_select(2, (key_indices // (kh * kw)).to(torch.int32)))
    attn[:, :, 1:, 1:] += relative.reshape(batch, heads, queries, kt * kh * kw)
    return attn


def convert(args) -> int:
    identity = verify_source(args.artifact_dir)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    report = {"passed": False, "source": identity, "precision": args.precision,
              "platform": platform.platform(), "stage": "load", "runtime_switched": False}
    try:
        import coremltools as ct
        import numpy as np
        import torch
        from unittest.mock import patch
        from app.backends.pytorch import PyTorchInferenceBackend

        report["versions"] = {"torch": torch.__version__, "coremltools": ct.__version__}
        backend = PyTorchInferenceBackend(
            args.artifact_dir / "best.pt", args.artifact_dir / "labels.json",
            identity["model_version"], .7, .15, device="cpu", labels_verified=True,
        )
        example = torch.zeros((1, 3, 16, 224, 224))
        with torch.inference_mode():
            original_output = backend._model(example)
        prepare_export_model(backend._model)
        report["export_rewrites"] = ["Pool.tensor_split_to_slices", "relative_position_rank_le_5"]
        report["stage"] = "trace"
        with torch.inference_mode(), patch("torchvision.models.video.mvit._add_rel_pos", export_add_rel_pos):
            traced = torch.jit.trace(backend._model, example, check_trace=False)
            torch.testing.assert_close(traced(example), original_output, rtol=1e-5, atol=1e-5)
        report["stage"] = "convert"
        model = ct.convert(
            traced, source="pytorch", convert_to="mlprogram",
            inputs=[ct.TensorType(name="frames", shape=(1, 3, 16, 224, 224), dtype=np.float32)],
            outputs=[ct.TensorType(name="logits", dtype=np.float32)],
            minimum_deployment_target=ct.target.macOS13,
            compute_precision=ct.precision.FLOAT32 if args.precision == "fp32" else ct.precision.FLOAT16,
            compute_units=ct.ComputeUnit.ALL,
            skip_model_load=True,
        )
        report["stage"] = "save"
        model.user_defined_metadata["vsign_model_version"] = identity["model_version"]
        model.user_defined_metadata["vsign_checkpoint_sha256"] = identity["checkpoint_sha256"]
        model.user_defined_metadata["vsign_labels_sha256"] = identity["labels_sha256"]
        package = args.output_dir / "model.mlpackage"
        model.save(str(package))
        report.update(package_sha256=package_hash(package),
                      input_shape=[1, 3, 16, 224, 224], input_name="frames", output_name="logits")
        (args.output_dir / "labels.json").write_text(
            (args.artifact_dir / "labels.json").read_text(encoding="utf-8"), encoding="utf-8")
        report.update(passed=True, stage="converted")
    except Exception as error:
        report["error"] = {"type": type(error).__name__, "message": str(error),
                           "traceback": traceback.format_exc()}
        print(f"Core ML failed at {report['stage']}: {type(error).__name__}: {error}", flush=True)
    finally:
        finalize_conversion(report, args.artifact_dir)
        report["elapsed_seconds"] = perf_counter() - started
        with (args.output_dir / "conversion.json").open("x", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    print(json.dumps({key: report[key] for key in ("passed", "stage", "source_unchanged", "elapsed_seconds")}), flush=True)
    return 0 if report["passed"] else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, default=Path("ml/artifacts/sales30_personal_v1"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--precision", choices=("fp32", "fp16"), default="fp32")
    args = parser.parse_args(argv)
    if args.output_dir.exists():
        parser.error("Use a new output directory; never overwrite model artifacts")
    return convert(args)


if __name__ == "__main__":
    raise SystemExit(main())
