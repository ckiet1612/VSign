"""Fit and evaluate the per-word, sentence-context decision policy for a Sales30 head.

Logits come from the run's sealed feature cache, so nothing re-runs the backbone.
Validation clips are split into 5 folds by repetition/group; every reported number is
on clips the policy was not fitted on. Standing test stays untouched until the final
check. Sentence results are simulated: rule-valid sentences whose words are replaced
by real held-out clips, with each word's context being what the policy accepted so far.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/inference"))

from app.decision import IDLE_LABEL, DecisionPolicy, labels_digest  # noqa: E402
from app.sentence_rules import REPEATED, UNCLEAR, expanded_sentence  # noqa: E402
from ml.scripts.compare_sales30_framing import load_side  # noqa: E402

FOLDS = 5
MIN_FIT_SUPPORT = 8
THRESHOLD_GRID = [round(value, 2) for value in np.arange(0.60, 0.96, 0.05)]
PENALTY_GRID = [1.0, 0.5, 0.1]
FLOOR_GRID = [None, 0.5, 0.4]
WRONG_COST = 3.0

PRODUCTS = ["Điện thoại", "Laptop", "Tivi", "Tủ lạnh", "Máy giặt", "Nồi cơm điện", "Gạo", "Sữa", "Cà phê"]
INSTITUTIONS = ["Siêu thị", "Ngân hàng"]
ACTIONS = ["Mua", "Xem", "Thử", "Sử dụng"]
QUALITIES = ["Mới", "Cũ", "Rẻ", "Đắt"]
DESIRES = ["Muốn", "Cần"]


def fold_of(row: dict) -> int:
    match = re.search(r"_rep(\d+)", row["path"])
    if match:
        return int(match.group(1)) % FOLDS
    return int(hashlib.sha256(row["group_id"].encode("utf-8")).hexdigest(), 16) % FOLDS


def softmax(logits: np.ndarray) -> np.ndarray:
    shifted = np.exp(logits - logits.max(axis=1, keepdims=True))
    return shifted / shifted.sum(axis=1, keepdims=True)


def fit_calibration(probabilities: np.ndarray, targets: np.ndarray, labels: list[str], strength: float = 0.05):
    """Temperature plus per-word bias on log-probabilities, with L2 pull toward identity."""
    counts = Counter(targets.tolist())
    free = torch.tensor([labels[index] != IDLE_LABEL and counts[index] >= MIN_FIT_SUPPORT
                         for index in range(len(labels))], dtype=torch.bool)
    log_p = torch.log(torch.tensor(probabilities, dtype=torch.float64).clamp_min(1e-12))
    target = torch.tensor(targets)
    bias = torch.zeros(len(labels), dtype=torch.float64, requires_grad=True)
    log_temperature = torch.zeros((), dtype=torch.float64, requires_grad=True)
    optimizer = torch.optim.LBFGS([bias, log_temperature], max_iter=200, line_search_fn="strong_wolfe")

    def loss():
        optimizer.zero_grad()
        used = torch.where(free, bias, torch.zeros_like(bias))
        value = torch.nn.functional.cross_entropy((log_p + used) / log_temperature.exp(), target)
        value = value + strength * used.square().sum() + strength * log_temperature.square()
        value.backward()
        return value

    optimizer.step(loss)
    used = torch.where(free, bias, torch.zeros_like(bias)).detach().numpy()
    temperature = float(log_temperature.exp().clamp(0.25, 4.0))
    return temperature, {labels[index]: float(used[index]) for index in range(len(labels)) if free[index] and abs(used[index]) > 1e-4}


CONFUSER_GRID = [0.002, 0.003, 0.005, 0.0075, 0.01, 0.015, 0.02, 0.03, 0.05, 0.075, 0.1, 0.15, 0.2]
MIN_CONFUSIONS = 3


def fit_confusers(policy: DecisionPolicy, probabilities: np.ndarray, targets: np.ndarray) -> dict[str, dict[str, float]]:
    """Per (winner, true word) pair seen wrongly accepted at least MIN_CONFUSIONS times, the
    look-alike probability above which the winner is refused, maximizing 3×wrong caught − correct lost."""
    calibrated = np.stack([policy.calibrate(row) for row in probabilities])
    top1 = calibrated.argmax(axis=1)
    pairs = Counter((int(winner), int(target)) for winner, target in zip(top1, targets)
                    if winner != target and policy.labels[target] != IDLE_LABEL)
    confusers: dict[str, dict[str, float]] = {}
    for (winner, other), wrong in pairs.items():
        if wrong < MIN_CONFUSIONS or policy.labels[winner] == IDLE_LABEL:
            continue
        mine = top1 == winner
        # Fitting data is mostly one signer; a veto may cost at most ~5% of the word's correct accepts.
        allowed_loss = max(1, int(0.05 * int((mine & (targets == winner)).sum())))
        best, best_gain = None, 0.0
        for limit in CONFUSER_GRID:
            caught = mine & (calibrated[:, other] >= limit)
            lost = int((caught & (targets == winner)).sum())
            gain = WRONG_COST * int((caught & (targets == other)).sum()) - lost
            if lost <= allowed_loss and gain > best_gain:
                best, best_gain = limit, gain
        if best is not None:
            confusers.setdefault(policy.labels[winner], {})[policy.labels[other]] = best
    return confusers


def fit_policy(probabilities: np.ndarray, targets: np.ndarray, labels: list[str]) -> DecisionPolicy:
    from dataclasses import replace
    temperature, bias = fit_calibration(probabilities, targets, labels)
    policy = DecisionPolicy(labels=tuple(labels), temperature=temperature, bias=bias)
    policy = replace(policy, confusers=fit_confusers(policy, probabilities, targets))
    return replace(policy, thresholds=fit_thresholds(policy, probabilities, targets))


def fit_thresholds(policy: DecisionPolicy, probabilities: np.ndarray, targets: np.ndarray) -> dict[str, float]:
    """Per predicted word, the threshold maximizing correct − WRONG_COST × wrong accepts (lowest on ties)."""
    calibrated = np.stack([policy.calibrate(row) for row in probabilities])
    order = np.argsort(calibrated, axis=1)[:, ::-1]
    top1, top2 = order[:, 0], order[:, 1]
    confidence = calibrated[np.arange(len(calibrated)), top1]
    margin = confidence - calibrated[np.arange(len(calibrated)), top2]
    # Clips already refused by a look-alike veto do not count against a word's threshold.
    vetoed = np.array([any(row[policy.labels.index(other)] >= limit
                           for other, limit in policy.confusers.get(policy.labels[winner], {}).items())
                       for row, winner in zip(calibrated, top1)])
    thresholds = {}
    for index, label in enumerate(policy.labels):
        mine = (top1 == index) & (margin >= policy.margin_threshold) & ~vetoed
        if label == IDLE_LABEL or mine.sum() < MIN_FIT_SUPPORT:
            continue
        best, best_value = None, None
        for threshold in THRESHOLD_GRID:
            accepted = mine & (confidence >= threshold)
            value = int((accepted & (targets == index)).sum()) - WRONG_COST * int((accepted & (targets != index)).sum())
            if best_value is None or value > best_value:
                best, best_value = threshold, value
        thresholds[label] = best
    return thresholds


def outcome(policy: DecisionPolicy, probabilities: np.ndarray, label: str, context: tuple[str, ...] = ()):
    prediction, adjusted = policy.decide(probabilities, context)
    if prediction.label is None:
        return "uncertain", None, adjusted
    return ("correct" if prediction.label == label else "wrong"), prediction.label, adjusted


def isolated(policy: DecisionPolicy, probabilities: np.ndarray, labels: list[str], targets: np.ndarray) -> Counter:
    counts = Counter()
    for row, target in zip(probabilities, targets):
        counts[outcome(policy, row, labels[target])[0]] += 1
    return counts


def sentence_bank(seed: int, count: int) -> list[list[str]]:
    rng = random.Random(seed)
    templates = [
        lambda: ["Chào"], lambda: ["Tôi", "Cảm ơn"],
        lambda: ["Tôi", rng.choice(DESIRES), rng.choice(ACTIONS), rng.choice(PRODUCTS)] + rng.choice([[], [rng.choice(QUALITIES)]]),
        lambda: ["Tôi", rng.choice(DESIRES), rng.choice(PRODUCTS)] + rng.choice([[], [rng.choice(QUALITIES)]]),
        lambda: ["Cho", "Tôi"] + rng.choice([[], [rng.choice(["Xem", "Thử", "Sử dụng"])]]) + [rng.choice(PRODUCTS)],
        lambda: ["Tôi", "Cho", rng.choice(PRODUCTS)],
        lambda: [rng.choice(INSTITUTIONS), rng.choice(["Có", "Cung cấp"]), rng.choice(PRODUCTS)],
        lambda: ["Tôi", rng.choice(DESIRES), "Mua bán", rng.choice(PRODUCTS)],
        lambda: ["Tôi", rng.choice(DESIRES), "Thay đổi", rng.choice(INSTITUTIONS)],
        lambda: ["Tôi", "Từ chối"] + rng.choice([[], ["Mua"]]) + [rng.choice(PRODUCTS)],
        lambda: [rng.choice(PRODUCTS), rng.choice(QUALITIES)],
    ]
    sentences = []
    while len(sentences) < count:
        words = rng.choice(templates)()
        if rng.random() < 0.25:
            words = ["Chào"] + words
        if rng.random() < 0.2:
            words = words + ["Cảm ơn"]
        _, warnings = expanded_sentence(words)
        if UNCLEAR not in warnings and REPEATED not in warnings:
            sentences.append(words)
    return sentences


def sentences(policy: DecisionPolicy, pool: dict[str, list[np.ndarray]], bank: list[list[str]], seed: int) -> Counter:
    rng = random.Random(seed)
    counts = Counter()
    for words in bank:
        if any(not pool.get(word) for word in words):
            continue
        context: list[str] = []
        whole = True
        for word in words:
            result, accepted, _ = outcome(policy, rng.choice(pool[word]), word, tuple(context))
            counts[result] += 1
            whole &= result == "correct"
            if accepted:
                context.append(accepted)
        counts["sentences"] += 1
        counts["sentences_all_correct"] += whole
    return counts


def score(counts: Counter) -> float:
    return counts["correct"] - WRONG_COST * counts["wrong"]


def variants(base: DecisionPolicy, calibrated: DecisionPolicy, penalty: float, floor):
    from dataclasses import replace
    return {
        "baseline": base,
        "calibrated": calibrated,
        "context": replace(base, context_penalty=penalty, context_floor=floor),
        "calibrated+context": replace(calibrated, context_penalty=penalty, context_floor=floor),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, default=Path("ml/artifacts/sales30_personal_v3_bodycrop_curated"))
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--sentences", type=int, default=3000)
    args = parser.parse_args(argv)
    from dataclasses import replace

    rows, features, head, checkpoint = load_side(args.artifact_dir)
    labels = list(checkpoint["labels"])
    with torch.inference_mode():
        probabilities = head(features).softmax(dim=1).double().numpy()
    targets = np.array([int(row["label_id"]) for row in rows])
    # Every non-training clip (seated Nhu + standing validation/test) is pooled and
    # cross-validated by repetition/group, so the policy sees several signers yet
    # each number is still on clips it was not fitted on.
    pooled = [index for index, row in enumerate(rows) if row["split"] in {"validation", "test"}]
    folds = np.array([fold_of(rows[index]) for index in pooled])
    groups = {index: rows[index]["source"] for index in pooled}
    base = DecisionPolicy.baseline(labels, 0.70, 0.15)
    bank = sentence_bank(20261019, args.sentences)

    def pools(indices):
        by_group = defaultdict(lambda: defaultdict(list))
        for index in indices:
            by_group[groups[index]][labels[targets[index]]].append(probabilities[index])
        return by_group

    per_fold = defaultdict(lambda: defaultdict(Counter))
    per_word_cv = defaultdict(lambda: defaultdict(Counter))
    choices = []
    for fold in range(FOLDS):
        fit = np.array(pooled)[folds != fold]
        held = np.array(pooled)[folds == fold]
        calibrated = fit_policy(probabilities[fit], targets[fit], labels)
        fit_pools = pools(fit)
        # Context settings are chosen on the fitting folds only.
        best = max(((penalty, floor) for penalty in PENALTY_GRID for floor in FLOOR_GRID),
                   key=lambda item: sum(score(sentences(variants(base, calibrated, *item)["calibrated+context"], pool, bank, fold))
                                        for pool in fit_pools.values()))
        choices.append(best)
        held_pools = pools(held)
        for name, policy in variants(base, calibrated, *best).items():
            for group in ("seated", "standing"):
                mine = [index for index in held if groups[index] == group]
                per_fold[name][f"{group}:isolated"] += isolated(policy, probabilities[mine], labels, targets[mine])
                per_fold[name][f"{group}:sentences"] += sentences(policy, held_pools[group], bank, 100 + fold)
            for index in held:
                word = labels[targets[index]]
                per_word_cv[name][word][outcome(policy, probabilities[index], word)[0]] += 1

    # Final policy: fitted on every pooled clip, context settings by majority of folds.
    calibrated = fit_policy(probabilities[pooled], targets[pooled], labels)
    penalty, floor = Counter(choices).most_common(1)[0][0]
    per_word = {name: {word: dict(value) for word, value in words.items()} for name, words in per_word_cv.items()}
    cross_validated = {name: {kind: dict(counts) for kind, counts in kinds.items()} for name, kinds in per_fold.items()}

    def utility(counts):
        return counts.get("correct", 0) - WRONG_COST * counts.get("wrong", 0)

    def total(name, kind, key):
        return sum(counts.get(key, 0) for group, counts in cross_validated[name].items() if group.endswith(kind))

    def passes(name):
        # Planned gate: wrong accepts never rise, total correct accepts rise, and no word
        # loses more than two correct accepts on held-out folds.
        never_worse = all(cross_validated[name][kind].get("wrong", 0) <= cross_validated["baseline"][kind].get("wrong", 0)
                          for kind in cross_validated["baseline"])
        correct_up = (total(name, "isolated", "correct") + total(name, "sentences", "correct")
                      > total("baseline", "isolated", "correct") + total("baseline", "sentences", "correct"))
        word_loss = max(per_word_cv["baseline"][word]["correct"] - per_word_cv[name][word]["correct"]
                        for word in per_word_cv["baseline"])
        return {"passed": never_worse and correct_up and word_loss <= 2, "wrong_never_rises": never_worse,
                "total_correct_rises": correct_up, "max_word_correct_loss": int(word_loss)}

    gates = {name: passes(name) for name in ("context", "calibrated", "calibrated+context")}
    gate = gates["calibrated+context"]["passed"] or gates["context"]["passed"]
    report = {
        "artifact": str(args.artifact_dir), "model_version": checkpoint["model_version"],
        "cross_validated": cross_validated,
        "per_word_note": "Per-word isolated counts on cross-validated held-out folds (seated + standing).",
        "per_word": per_word, "fold_context_choices": choices,
        "deployment_gate_passed": gate, "gates": gates,
        "limits": ("Seated validation (Nhu) also selected the checkpoint; standing test is now pooled into "
                   "cross-validation, so no split stays fully untouched. Sentences are simulated from "
                   "sentence_rules with real held-out clips; no real signed sentences exist. Mua has no held-out clips."),
    }
    policy_payload = {
        "model_version": checkpoint["model_version"], "labels_sha256": labels_digest(labels),
        "temperature": calibrated.temperature, "bias": dict(calibrated.bias),
        "thresholds": dict(calibrated.thresholds), "confusers": {word: dict(pairs) for word, pairs in calibrated.confusers.items()},
        "default_threshold": 0.70, "margin_threshold": 0.15,
        "context_penalty": penalty, "context_floor": floor,
        "fitted_on": "validation + standing test (seated Nhu + standing), curated v1", "report": str(args.report_dir),
    }
    # The context-only policy keeps every isolated decision and adds the sentence step.
    context_payload = {**policy_payload, "temperature": 1.0, "bias": {}, "thresholds": {}, "confusers": {},
                       "variant": "context"}
    policy_payload["variant"] = "calibrated+context"
    args.report_dir.mkdir(parents=True, exist_ok=True)
    (args.report_dir / "calibration_context.json").write_text(
        json.dumps(context_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.report_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.report_dir / "calibration.json").write_text(json.dumps(policy_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cross_validated": cross_validated, "context": [penalty, floor],
                      "temperature": round(calibrated.temperature, 3), "thresholds": calibrated.thresholds,
                      "confusers": calibrated.confusers,
                      "gates": gates}, ensure_ascii=False, indent=1))
    return 0 if gate else 2


if __name__ == "__main__":
    raise SystemExit(main())
