"""Seated/personal head training with explicit evaluation-only standing data."""

from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path

import torch
from torch import nn
from torch.nn import functional as F

from ml.personal_finetune import IDLE_LABEL, evaluate_features, expand_head, load_feature_cache, regression_gate
from ml.scripts.finetune_sales30_personal import write_json


def select_rows(rows, labels):
    if len(labels) != 31 or labels[-1] != IDLE_LABEL or len(set(labels)) != 31:
        raise ValueError("Expected the original 30 words followed by idle")
    selected, indices = [], []
    for index, row in enumerate(rows):
        source, split = row["source"], row["split"]
        if source == "personal" and split != "train":
            raise ValueError("Personal session must remain train-only")
        if source == "seated" and (split not in {"train", "validation"}
                or (split == "validation" and row["person"] != "Như")
                or (split == "train" and row["person"] not in {"HA", "Nhi"})):
            raise ValueError("Seated signer split changed")
        if source not in {"standing", "seated", "personal"}:
            raise ValueError("Unknown dataset source")
        if source == "standing" and split != "test":
            continue
        if not 0 <= int(row["label_id"]) < 31 or labels[int(row["label_id"])] != row["label"]:
            raise ValueError("Label order mismatch")
        selected.append(dict(row))
        indices.append(index)
    hash_splits, group_splits, paths = {}, {}, set()
    for row in selected:
        if row["path"] in paths:
            raise ValueError("Duplicate path")
        paths.add(row["path"])
        for seen, key in [(hash_splits, "sha256"), (group_splits, "group_id")]:
            if seen.setdefault(row[key], row["split"]) != row["split"]:
                raise ValueError("Cross-split leakage")
    train_classes = {int(r["label_id"]) for r in selected if r["split"] == "train"}
    validation_classes = {int(r["label_id"]) for r in selected if r["split"] == "validation"}
    if train_classes != set(range(31)) or validation_classes != set(range(30)):
        raise ValueError("Missing training/validation word coverage")
    return selected, indices


def sample_weights(rows, class_count):
    counts = Counter((int(r["label_id"]), r["source"]) for r in rows)
    sources = Counter(label for label, _ in counts)
    if set(sources) != set(range(class_count)):
        raise ValueError("Missing training class")
    weights = torch.tensor([1. / (sources[int(r["label_id"])] * counts[int(r["label_id"]), r["source"]])
                            for r in rows])
    return weights / weights.mean()


def reuse_features(path, identity, original_rows, selected_rows, width):
    if not path.is_file() or path.is_symlink():
        raise ValueError("Missing sealed feature cache")
    cache = load_feature_cache(path, identity, len(original_rows), width)
    by_path = {row["path"]: (index, row) for index, row in enumerate(original_rows)}
    indices = []
    for row in selected_rows:
        original = by_path.get(row["path"])
        if original is None or any(str(original[1][key]) != str(value) for key, value in row.items()):
            raise ValueError("Feature cache row identity changed")
        index = original[0]
        if not cache["completed"][index]:
            raise ValueError("Feature cache is not complete")
        indices.append(index)
    return cache["features"][indices].clone()


def evaluate(head, features, targets, labels):
    report = evaluate_features(head, features, targets, labels, positive_class_count=len(labels) - 1)
    with torch.inference_mode():
        probabilities = head(features).softmax(dim=1)
        scores, ids = probabilities.topk(2, dim=1)
        predicted = ids[:, 0]
        accepted = (scores[:, 0] >= .70) & (scores[:, 0] - scores[:, 1] >= .15) & (predicted != len(labels) - 1)
    for label_id, label in enumerate(labels):
        mask = targets == label_id
        count = int(mask.sum())
        correct = int((mask & accepted & (predicted == targets)).sum())
        wrong = int((mask & accepted & (predicted != targets)).sum())
        uncertain = int((mask & ~accepted).sum())
        report["per_class"][label].update({
            "correct_accept_count": correct, "wrong_accept_count": wrong, "uncertain_count": uncertain,
            "correct_accept_rate": correct / count if count else None,
            "wrong_accept_rate": wrong / count if count else None,
            "uncertain_rate": uncertain / count if count else None,
            "confusions": dict(Counter(labels[int(i)] for i in predicted[mask & accepted & (predicted != targets)])),
            "top1_confusions": dict(Counter(labels[int(i)] for i in predicted[mask & (predicted != targets)])),
        })
    return report


def negative_fit_gate(report):
    idle = report["per_class"][IDLE_LABEL]
    return (idle["samples"] > 0 and idle["recall"] >= .9
            and idle["wrong_accept_count"] * 50 <= idle["samples"])


def train_head(features, rows, baseline_head, current_head, labels, epochs, learning_rate, output):
    if any(r["source"] == "standing" and r["split"] == "train" for r in rows):
        raise ValueError("Standing samples may not enter optimization")
    selected, _ = select_rows(rows, labels)
    if selected != rows:
        raise ValueError("Training manifest contains excluded rows")
    targets = torch.tensor([int(r["label_id"]) for r in rows])
    partitions = {split: torch.tensor([i for i, r in enumerate(rows) if r["split"] == split])
                  for split in ("train", "validation", "test")}
    train_ids, validation_ids = partitions["train"], partitions["validation"]
    personal_ids = torch.tensor([i for i, r in enumerate(rows) if r["source"] == "personal"])
    weights = sample_weights([rows[int(i)] for i in train_ids], len(labels))
    head = expand_head(baseline_head)
    teacher = copy.deepcopy(baseline_head).requires_grad_(False)
    current_head = copy.deepcopy(current_head).eval().requires_grad_(False)
    with torch.inference_mode():
        teacher_probabilities = teacher(features[train_ids]).softmax(dim=1)
    seated_mask = torch.tensor([rows[int(i)]["source"] == "seated" for i in train_ids])
    baseline_validation = evaluate(current_head, features[validation_ids], targets[validation_ids], labels)
    baseline_personal = evaluate(current_head, features[personal_ids], targets[personal_ids], labels)
    write_json(output / "baseline_validation.json", baseline_validation)
    optimizer = torch.optim.AdamW(head.parameters(), lr=learning_rate, weight_decay=.01)
    history, best_score, best_state, best_epoch = [], float("-inf"), None, None
    for epoch in range(1, epochs + 1):
        order = torch.randperm(len(train_ids))
        loss_sum = 0.
        for offset in range(0, len(order), 128):
            local = order[offset:offset + 128]
            ids = train_ids[local]
            logits = head(features[ids])
            loss = (F.cross_entropy(logits, targets[ids], reduction="none") * weights[local]).mean()
            replay = seated_mask[local]
            if replay.any():
                loss = loss + .5 * F.kl_div(logits[replay, :30].log_softmax(dim=1),
                    teacher_probabilities[local][replay], reduction="batchmean")
            loss = loss + .01 * ((head.weight[:30] - teacher.weight).square().mean()
                                + (head.bias[:30] - teacher.bias).square().mean())
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(head.parameters(), 5.)
            optimizer.step()
            loss_sum += float(loss.detach()) * len(ids)
        head.eval()
        validation = evaluate(head, features[validation_ids], targets[validation_ids], labels)
        personal = evaluate(head, features[personal_ids], targets[personal_ids], labels)
        eligible = regression_gate(baseline_validation, validation) and negative_fit_gate(personal)
        history.append({"epoch": epoch, "loss": loss_sum / len(train_ids), "eligible": eligible,
                        "validation": validation, "personal_training_only": personal})
        if eligible and validation["macro_f1"] > best_score:
            best_score, best_epoch, best_state = validation["macro_f1"], epoch, copy.deepcopy(head.state_dict())
        print(json.dumps({"event": "epoch", "epoch": epoch, "eligible": eligible,
              "accuracy": validation["accuracy"], "macro_f1": validation["macro_f1"],
              "negative_training_recognition": personal["negative_recognition_rate"],
              "negative_training_false_accept": personal["negative_false_accept_rate"]}), flush=True)
    write_json(output / "history.json", history)
    if best_state is None:
        write_json(output / "summary.json", {"event": "training_failed", "deployment_gate_passed": False,
                   "reason": "No eligible seated-validation/negative-fit checkpoint", "runtime_changed": False})
        raise RuntimeError("No eligible candidate; current model is unchanged")
    head.load_state_dict(best_state)
    # Standing test is evaluated once, after validation-only checkpoint selection.
    comparisons = {}
    for name, ids in [("seated_validation", validation_ids), ("standing_test", partitions["test"]),
                      ("personal_training_only", personal_ids)]:
        comparisons[name] = {"baseline": evaluate(current_head, features[ids], targets[ids], labels),
                             "candidate": evaluate(head, features[ids], targets[ids], labels)}
    comparisons.update({"deployment_gate_passed": regression_gate(
        comparisons["standing_test"]["baseline"], comparisons["standing_test"]["candidate"]),
        "independent_negative_evaluation": False, "development_only": True,
        "regression_tolerance_absolute": .02, "baseline_personal_training_only": baseline_personal})
    write_json(output / "comparison.json", comparisons)
    return head, best_epoch, comparisons
