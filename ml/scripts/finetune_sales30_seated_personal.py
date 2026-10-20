"""Train a separate seated + personal candidate without changing active artifacts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import time
from collections import Counter
from pathlib import Path

import torch
from torch import nn

from ml.candidate_manifest import candidate_training_guard, publish_candidate_manifest
from ml.personal_finetune import (IDLE_LABEL, MANIFEST_FIELDS, prepare_rows, sha256_file,
                                  validate_output, verify_baseline_manifest)
from ml.seated_personal import reuse_features, select_rows, train_head
from ml.scripts.finetune_sales30_personal import write_json


def head_from_state(state):
    weight, bias = state["head.1.weight"], state["head.1.bias"]
    head = nn.Linear(weight.shape[1], weight.shape[0])
    head.load_state_dict({"weight": weight, "bias": bias})
    return head


@candidate_training_guard
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--learning-rate", type=float, default=.0005)
    args = parser.parse_args(argv)
    if args.epochs < 1 or not 0 < args.learning_rate < 1:
        parser.error("Invalid training schedule")
    torch.set_num_threads(4)
    root = args.root.resolve()
    output = (args.output_dir or root / "ml/artifacts/sales30_seated_personal_v1").absolute()
    baseline_dir = root / "ml/artifacts/sales30_seated_v3"
    current_dir = root / "ml/artifacts/sales30_personal_v1"
    baseline_path, current_path = baseline_dir / "training/best.pt", current_dir / "best.pt"
    batch = root / "ml/data/collected/sales30/batches/personal-100"
    validate_output(output, baseline_dir / "labels.json", root / "ml/data")
    validate_output(output, current_path, batch)
    if output.exists():
        raise FileExistsError("Use a new candidate output directory")
    labels = json.loads((root / "contracts/v1/sales30.labels.json").read_text())
    checkpoint = torch.load(baseline_path, map_location="cpu", weights_only=True)
    current = torch.load(current_path, map_location="cpu", weights_only=True)
    summary = json.loads((current_dir / "summary.json").read_text())
    if (checkpoint["labels"] != labels or current["labels"] != labels + [IDLE_LABEL]
            or checkpoint["input_shape"] != [1, 3, 16, 224, 224]
            or current["input_shape"] != checkpoint["input_shape"]
            or sha256_file(current_path) != summary["best_sha256"]
            or summary["deployment_gate_passed"] is not True):
        raise ValueError("Baseline/current checkpoint identity mismatch")
    for key, tensor in checkpoint["state_dict"].items():
        if not key.startswith("head.1.") and not torch.equal(tensor, current["state_dict"][key]):
            raise ValueError("Cached features cannot be reused with a changed backbone")
    manifest = root / "ml/data/combined/sales30_seated_v3/manifest.csv"
    verify_baseline_manifest(manifest, checkpoint)
    original_rows, original_audit = prepare_rows(root, manifest, batch, labels)
    all_labels = labels + [IDLE_LABEL]
    rows, _ = select_rows(original_rows, all_labels)
    counts = Counter(r["split"] for r in rows)
    if counts != {"train": 2560, "validation": 600, "test": 351}:
        raise ValueError(f"Approved dataset changed: {counts}")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=MANIFEST_FIELDS)
    writer.writeheader()
    writer.writerows(original_rows)
    source_identity = json.loads((current_dir / "run_identity.json").read_text())
    if (hashlib.sha256(buffer.getvalue().encode()).hexdigest() != source_identity["manifest_sha256"]
            or sha256_file(baseline_path) != source_identity["baseline_sha256"]
            or source_identity["preprocessing"] != "uniform16-224-imagenet-eval-v1"
            or source_identity["labels"] != all_labels):
        raise ValueError("Feature cache provenance mismatch")
    initial_head = head_from_state(checkpoint["state_dict"])
    current_head = head_from_state(current["state_dict"])
    features = reuse_features(current_dir / "features.pt", source_identity,
                              original_rows, rows, initial_head.in_features)
    preserved = {str(path.relative_to(root)): sha256_file(path) for path in
                 (baseline_path, current_path, current_dir / "labels.json", manifest, current_dir / "features.pt")}
    output.mkdir(parents=True, exist_ok=False)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=MANIFEST_FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    content = buffer.getvalue().encode()
    (output / "manifest.csv").write_bytes(content)
    identity = {"baseline_sha256": sha256_file(baseline_path), "comparison_sha256": sha256_file(current_path),
                "manifest_sha256": hashlib.sha256(content).hexdigest(), "labels": all_labels,
                "preprocessing": source_identity["preprocessing"], "epochs": args.epochs,
                "learning_rate": args.learning_rate, "seed": 20261011,
                "training": "seated-personal-frozen-backbone-class-source-balanced-v1"}
    audit = {"splits": dict(counts), "training_sources": dict(Counter(r["source"] for r in rows if r["split"] == "train")),
             "standing_train_samples": 0, "feature_cache_reused": True, "source_cache_identity": source_identity,
             "personal_sessions": original_audit["personal_sessions"], "personal_labels": original_audit["personal_labels"],
             "personal_posture_verified": False, "personal_semantic_labels_reviewed": False,
             "validation_is_development_only": True, "independent_negative_evaluation": False,
             "preserved_files": preserved}
    write_json(output / "run_identity.json", identity)
    write_json(output / "audit.json", audit)
    write_json(output / "labels.json", all_labels)
    torch.manual_seed(identity["seed"])
    print(json.dumps({"event": "dataset_ready", **audit}, ensure_ascii=False), flush=True)
    started = time.monotonic()
    head, epoch, comparison = train_head(features, rows, initial_head, current_head,
                                         all_labels, args.epochs, args.learning_rate, output)
    state = dict(checkpoint["state_dict"])
    state.update({"head.1.weight": head.weight.detach().clone(), "head.1.bias": head.bias.detach().clone()})
    version = f"sales30-mvitv2s-seated-personal-v1-head-epoch{epoch}"
    payload = {"architecture": "mvit_v2_s", "state_dict": state, "labels": all_labels,
               "input_shape": [1, 3, 16, 224, 224], "epoch": epoch, "model_version": version,
               "run_identity": identity, "training_scope": "linear_head_only", "development_only": True}
    torch.save(payload, output / "best.pt")
    unchanged = all(sha256_file(root / relative) == digest for relative, digest in preserved.items())
    result = {"event": "training_complete", "model_version": version, "best_epoch": epoch,
              "epochs": args.epochs, "learning_rate": args.learning_rate,
              "deployment_gate_passed": comparison["deployment_gate_passed"] and unchanged,
              "training_seconds": time.monotonic() - started, "backbone_unchanged": True,
              "changed_tensors": ["head.1.weight", "head.1.bias"], "source_files_unchanged": unchanged,
              "best_sha256": sha256_file(output / "best.pt"), "runtime_changed": False,
              "independent_negative_evaluation": False, "development_only": True}
    write_json(output / "summary.json", result)
    if unchanged:
        publish_candidate_manifest(output, labels=payload["labels"], model_version=version,
                                   source_run_id=sha256_file(output / "run_identity.json"))
    print(json.dumps(result), flush=True)
    return 0 if result["deployment_gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
