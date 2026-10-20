"""Benchmark Sales30 head recipes on the owner's Personal clips by cross-validation.

Every Personal clip is training data for the deployed heads, so each recipe is re-fitted
per fold with one block of Personal clips held out, then scored on that block:

- Each word's 100 clips (and the 100 Không ký hiệu clips) are split by capture time into
  five consecutive blocks, so held-out clips are not the neighbours of training clips.
- The recipe is the deployed one: same features, rows, teacher, loss and learning rate,
  trained for the run's selected epoch count. Nothing is selected on Nhu.

All Personal clips come from one session (same day, lighting and clothes), so this is an
optimistic estimate of a new session.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import torch
from torch import nn

from ml.personal_finetune import IDLE_LABEL, load_feature_cache
from ml.scripts.finetune_sales30_personal import head_epochs

FOLDS = 5
LEARNING_RATE = 5e-4
SEED = 20261009
BASELINE = Path("ml/artifacts/sales30_seated_v3/training/best.pt")
CONFIDENCE, MARGIN = 0.70, 0.15
# Sentence prefixes a non-sign movement may follow in automatic mode.
NEGATIVE_CONTEXTS = [[], ["Tôi"], ["Tôi", "Muốn"], ["Tôi", "Muốn", "Mua"], ["Cho", "Tôi"], ["Chào"]]


def personal_folds(rows: list[dict]) -> dict[int, int]:
    """Row index → fold: consecutive capture-time blocks within each label."""
    by_label = defaultdict(list)
    for index, row in enumerate(rows):
        if row["source"] == "personal":
            metadata = json.loads(Path(row["path"]).with_suffix(".json").read_text(encoding="utf-8"))
            by_label[row["label"]].append((metadata["captured_at"], index))
    folds = {}
    for items in by_label.values():
        items.sort()
        for rank, (_, index) in enumerate(items):
            folds[index] = rank * FOLDS // len(items)
    return folds


def decide(probabilities: torch.Tensor, idle: int) -> tuple[torch.Tensor, torch.Tensor]:
    top = probabilities.topk(2, dim=1)
    accepted = (top.values[:, 0] >= CONFIDENCE) & (top.values[:, 0] - top.values[:, 1] >= MARGIN) & (top.indices[:, 0] != idle)
    return top.indices[:, 0], accepted


def benchmark(run: Path, teacher: nn.Linear) -> dict:
    with (run / "manifest.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    identity = json.loads((run / "run_identity.json").read_text(encoding="utf-8"))
    checkpoint = torch.load(run / "best.pt", map_location="cpu", weights_only=True)
    labels, epochs = checkpoint["labels"], int(checkpoint["epoch"])
    width = checkpoint["state_dict"]["head.1.weight"].shape[1]
    features = load_feature_cache(run / "features.pt", identity, len(rows), width)["features"]
    mirrored = None
    if identity.get("augmentation") == "hflip":
        mirrored = load_feature_cache(run / "features_hflip.pt", {**identity, "view": "hflip"}, len(rows), width)["features"]
    targets = torch.tensor([int(row["label_id"]) for row in rows])
    folds = personal_folds(rows)
    idle = labels.index(IDLE_LABEL)
    per_word = defaultdict(Counter)
    negatives = Counter()
    by_action = defaultdict(Counter)
    policy = None
    if (run / "calibration.json").exists():
        import sys
        sys.path.insert(0, str(Path("services/inference").resolve()))
        from app.decision import DecisionPolicy
        policy = DecisionPolicy.load(run / "calibration.json", labels, checkpoint["model_version"])
    policy_negatives = Counter()
    for fold in range(FOLDS):
        held = [index for index, value in folds.items() if value == fold]
        train = [index for index, row in enumerate(rows) if row["split"] == "train" and folds.get(index) != fold]
        old_train = torch.tensor([rows[index]["source"] != "personal" for index in train])
        pool, pool_targets = features, targets
        train_ids = torch.tensor(train)
        if mirrored is not None:
            # Mirrored copies of the same training clips, as in the hflip recipe.
            pool = torch.cat([features, mirrored])
            pool_targets = torch.cat([targets, targets])
            train_ids = torch.cat([train_ids, train_ids + len(rows)])
            old_train = torch.cat([old_train, old_train])
        torch.manual_seed(SEED + fold)
        for _, head, _ in head_epochs(pool, pool_targets, train_ids, old_train, teacher, len(labels), epochs, LEARNING_RATE):
            pass
        with torch.inference_mode():
            probabilities = head(features[held]).softmax(dim=1)
            predicted, accepted = decide(probabilities, idle)
        if policy is not None:
            for row_index, row_probabilities in zip(held, probabilities.double().numpy()):
                if rows[row_index]["label"] != IDLE_LABEL:
                    continue
                for context in NEGATIVE_CONTEXTS:
                    decided, _ = policy.decide(row_probabilities, context)
                    policy_negatives[" ".join(context) or "(trống)"] += decided.label is not None
        for row_index, guess, ok in zip(held, predicted.tolist(), accepted.tolist()):
            label = rows[row_index]["label"]
            if label == IDLE_LABEL:
                negatives["clips"] += 1
                negatives["false_accept"] += ok
                negatives["idle_top1"] += guess == idle
                action = json.loads(Path(rows[row_index]["path"]).with_suffix(".json").read_text(encoding="utf-8"))["negative_action"]
                by_action[action]["clips"] += 1
                if ok:
                    by_action[action][f"accepted:{labels[guess]}"] += 1
            else:
                per_word[label]["correct" if ok and labels[guess] == label else "wrong" if ok else "uncertain"] += 1
    totals = Counter()
    for counts in per_word.values():
        totals.update(counts)
    return {"run": str(run), "model_version": checkpoint["model_version"], "epochs": epochs,
            "augmentation": identity.get("augmentation"), "preprocessing": identity["preprocessing"],
            "positives": dict(totals), "negatives": dict(negatives),
            "negatives_by_action": {action: dict(counts) for action, counts in sorted(by_action.items())},
            "negatives_accepted_with_deployed_policy_by_context": dict(policy_negatives) if policy else None,
            "per_word": {word: dict(counts) for word, counts in sorted(per_word.items())}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, nargs="+", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    state = torch.load(BASELINE, map_location="cpu", weights_only=True)["state_dict"]
    teacher = nn.Linear(state["head.1.weight"].shape[1], state["head.1.weight"].shape[0])
    teacher.load_state_dict({"weight": state["head.1.weight"], "bias": state["head.1.bias"]})
    results = [benchmark(run, teacher.eval()) for run in args.runs]
    report = {"folds": FOLDS, "thresholds": {"confidence": CONFIDENCE, "margin": MARGIN}, "results": results,
              "limits": "One Personal session; held-out blocks share day, lighting and clothes with training blocks. "
                        "Only the 13 Personal words and Không ký hiệu are covered."}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for result in results:
        positives, negatives = result["positives"], result["negatives"]
        print(json.dumps({"model": result["model_version"], "positives": positives,
                          "negatives": negatives}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
