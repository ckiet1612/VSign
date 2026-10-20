"""A/B: deployed personal head on its own preprocessing vs the trim-bodycrop-v1 head.

Both candidates are evaluated from their sealed feature caches over the same manifest
rows, so each side sees exactly the input it was trained for.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import torch
from torch import nn

from ml.personal_finetune import IDLE_LABEL, evaluate_features, load_feature_cache

GROUPS = {
    "validation_seated": lambda row: row["split"] == "validation" and row["source"] == "seated",
    "validation_standing": lambda row: row["split"] == "validation" and row["source"] == "standing",
    "test_standing": lambda row: row["split"] == "test",
}


def load_side(directory: Path) -> tuple[list[dict], torch.Tensor, nn.Linear, dict]:
    with (directory / "manifest.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    identity = json.loads((directory / "run_identity.json").read_text(encoding="utf-8"))
    checkpoint = torch.load(directory / "best.pt", map_location="cpu", weights_only=True)
    weight, bias = checkpoint["state_dict"]["head.1.weight"], checkpoint["state_dict"]["head.1.bias"]
    head = nn.Linear(weight.shape[1], weight.shape[0])
    head.load_state_dict({"weight": weight, "bias": bias})
    cache = load_feature_cache(directory / "features.pt", identity, len(rows), weight.shape[1])
    if not bool(cache["completed"].all()):
        raise ValueError(f"Incomplete feature cache: {directory}")
    return rows, cache["features"], head.eval(), checkpoint


def outcomes(head: nn.Linear, features: torch.Tensor, targets: torch.Tensor, idle_id: int) -> dict:
    with torch.inference_mode():
        probabilities = head(features).softmax(dim=1)
    top = probabilities.topk(2, dim=1)
    predicted = top.indices[:, 0]
    accepted = (top.values[:, 0] >= .70) & (top.values[:, 0] - top.values[:, 1] >= .15) & (predicted != idle_id)
    correct = accepted & (predicted == targets)
    wrong = accepted & (predicted != targets)
    count = len(targets)
    return {"correct_accept": int(correct.sum()), "wrong_accept": int(wrong.sum()),
            "uncertain": count - int(accepted.sum()),
            "correct_accept_rate": float(correct.float().mean()), "wrong_accept_rate": float(wrong.float().mean()),
            "predicted": predicted.tolist(), "accepted": accepted.tolist()}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=Path("ml/artifacts/sales30_personal_v1"))
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mirrored", action="store_true",
                        help="Also score both heads on the candidate's mirrored (hflip) clips; needs one shared preprocessing")
    args = parser.parse_args(argv)
    baseline_rows, baseline_features, baseline_head, baseline_checkpoint = load_side(args.baseline)
    candidate_rows, candidate_features, candidate_head, candidate_checkpoint = load_side(args.candidate)
    # A curated candidate may drop clips; compare both sides on the candidate's rows only.
    baseline_index = {(row["path"], row["sha256"], row["label_id"]): index for index, row in enumerate(baseline_rows)}
    try:
        order = [baseline_index[(row["path"], row["sha256"], row["label_id"])] for row in candidate_rows]
    except KeyError as error:
        raise ValueError("Candidate has clips the baseline never saw") from error
    baseline_features = baseline_features[torch.tensor(order)]
    baseline_rows = candidate_rows
    labels = baseline_checkpoint["labels"]
    if candidate_checkpoint["labels"] != labels:
        raise ValueError("Label order differs")
    idle_id = labels.index(IDLE_LABEL)
    targets = torch.tensor([int(row["label_id"]) for row in baseline_rows])
    report = {"baseline": baseline_checkpoint["model_version"], "candidate": candidate_checkpoint["model_version"],
              "rows": len(candidate_rows),
              "candidate_input_framing": candidate_checkpoint.get("input_framing"),
              "thresholds": {"confidence": .70, "margin": .15}, "groups": {}, "per_word": {}}
    for name, keep in GROUPS.items():
        ids = torch.tensor([index for index, row in enumerate(baseline_rows) if keep(row)])
        group = {}
        for side, head, features in (("baseline", baseline_head, baseline_features),
                                     ("candidate", candidate_head, candidate_features)):
            metrics = evaluate_features(head, features[ids], targets[ids], labels, positive_class_count=30)
            result = outcomes(head, features[ids], targets[ids], idle_id)
            per_word = {}
            for label_id, label in enumerate(labels[:30]):
                mask = targets[ids] == label_id
                if mask.any():
                    accepted = torch.tensor(result["accepted"])[mask]
                    predicted = torch.tensor(result["predicted"])[mask]
                    per_word[label] = {"samples": int(mask.sum()),
                                       "correct_accept": int((accepted & (predicted == label_id)).sum()),
                                       "wrong_accept": int((accepted & (predicted != label_id)).sum())}
            report["per_word"].setdefault(name, {})[side] = per_word
            group[side] = {key: metrics[key] for key in ("samples", "accuracy", "macro_f1", "top3_accuracy")}
            group[side].update({key: value for key, value in result.items() if key not in ("predicted", "accepted")})
        report["groups"][name] = group
    if args.mirrored:
        # Same frozen backbone and framing, so one mirrored cache serves both heads.
        candidate_identity = json.loads((args.candidate / "run_identity.json").read_text(encoding="utf-8"))
        baseline_identity = json.loads((args.baseline / "run_identity.json").read_text(encoding="utf-8"))
        if baseline_identity.get("preprocessing") != candidate_identity.get("preprocessing"):
            raise ValueError("Mirrored comparison needs both heads on the same preprocessing")
        mirrored = load_feature_cache(args.candidate / "features_hflip.pt", {**candidate_identity, "view": "hflip"},
                                      len(candidate_rows), candidate_features.shape[1])
        report["mirrored_groups"] = {}
        for name, keep in GROUPS.items():
            ids = torch.tensor([index for index, row in enumerate(candidate_rows) if keep(row)])
            if not bool(mirrored["completed"][ids].all()):
                raise ValueError("Mirrored cache is incomplete")
            report["mirrored_groups"][name] = {
                side: {key: value for key, value in outcomes(head, mirrored["features"][ids], targets[ids], idle_id).items()
                       if key not in ("predicted", "accepted")}
                for side, head in (("baseline", baseline_head), ("candidate", candidate_head))}
        personal = torch.tensor([index for index, row in enumerate(candidate_rows) if row["source"] == "personal"
                                 and row["label"] != IDLE_LABEL])
        report["mirrored_personal_training_clips"] = {
            side: {key: value for key, value in outcomes(head, mirrored["features"][personal], targets[personal], idle_id).items()
                   if key not in ("predicted", "accepted")}
            for side, head in (("baseline", baseline_head), ("candidate", candidate_head))}
    report["development_only"] = True
    report["limits"] = ("Seated validation (Nhu) selected the checkpoint for both sides; it is not an independent "
                        "test. Standing test is the only held-out split. No live camera, segmentation or new signer.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name, group in report["groups"].items():
        print(name, {side: {key: round(value, 4) if isinstance(value, float) else value
                            for key, value in group[side].items()} for side in group})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
