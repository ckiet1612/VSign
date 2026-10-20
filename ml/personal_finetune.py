"""Contracts for reversible personal fine-tuning of the accepted Sales30 model."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

import torch
from torch import nn

from ml.candidate_manifest import sha256_file, validate_candidate_output


IDLE_LABEL = "Không ký hiệu"
MANIFEST_FIELDS = ["path", "label_id", "label", "split", "source", "person", "group_id", "sha256"]


def verify_baseline_manifest(manifest: Path, checkpoint: dict[str, Any]) -> None:
    if sha256_file(manifest) != checkpoint.get("combined_manifest_sha256"):
        raise ValueError("Accepted baseline manifest hash mismatch")
    with manifest.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if (Counter(row["split"] for row in rows) != {"train": 2425, "validation": 744, "test": 351}
            or Counter(row["source"] for row in rows) != {"standing": 1760, "seated": 1760}):
        raise ValueError("Accepted baseline manifest counts mismatch")


def checked_path(root: Path, relative: str) -> Path:
    path = root / relative
    if (Path(relative).is_absolute() or ".." in Path(relative).parts
            or "\\" in relative or root.resolve() not in path.resolve().parents
            or any(part.is_symlink() for part in (path, *path.parents))):
        raise ValueError(f"Unsafe source path: {relative}")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def validate_output(output: Path, baseline: Path, batch: Path) -> None:
    validate_candidate_output(output)
    resolved = output.resolve()
    for protected in (baseline.parent.resolve(), batch.resolve()):
        if resolved == protected or resolved in protected.parents or protected in resolved.parents:
            raise ValueError("Output overlaps baseline or source data")


def prepare_rows(
    root: Path, manifest: Path, batch: Path, labels: Sequence[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(labels) != 30 or len(set(labels)) != 30 or IDLE_LABEL in labels:
        raise ValueError("Baseline must retain exactly 30 unique labels")
    with manifest.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("Empty baseline manifest")
    old_count = len(rows)
    label_ids = {label: index for index, label in enumerate([*labels, IDLE_LABEL])}
    sessions: Counter[str] = Counter()
    personal_labels: Counter[str] = Counter()
    negative_actions: Counter[str] = Counter()
    paired: set[Path] = set()
    for metadata_path in sorted(batch.rglob("*.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        label = metadata.get("expected_label")
        if label not in label_ids or unicodedata.normalize("NFC", label) != label:
            raise ValueError(f"Invalid personal label: {label}")
        video = metadata_path.with_suffix(".mp4")
        if (metadata.get("video_file") != video.name or metadata.get("sample_id") != video.stem
                or not 8 <= metadata.get("frame_count", 0) <= 42
                or (metadata.get("width"), metadata.get("height")) != (224, 224)
                or not 650 <= metadata.get("duration_ms", 0) <= 3150):
            raise ValueError(f"Invalid metadata: {metadata_path}")
        session = metadata.get("session_id")
        if not isinstance(session, str) or not session:
            raise ValueError(f"Missing session: {metadata_path}")
        if label == IDLE_LABEL and not metadata.get("negative_action"):
            raise ValueError(f"Missing negative action: {metadata_path}")
        relative = video.relative_to(root).as_posix()
        checked_path(root, relative)
        paired.add(video)
        sessions[session] += 1
        personal_labels[label] += 1
        if metadata.get("negative_action"):
            negative_actions[metadata["negative_action"]] += 1
        rows.append({
            "path": relative, "label_id": label_ids[label], "label": label,
            "split": "train", "source": "personal", "person": "unknown",
            "group_id": f"personal:{session}", "sha256": sha256_file(video),
        })
    if not paired or set(batch.rglob("*.mp4")) != paired:
        raise ValueError("Empty personal batch or unpaired MP4")
    paths: set[str] = set()
    hash_splits: dict[str, str] = {}
    group_splits: dict[str, str] = {}
    for row in rows:
        path, split, digest, group = (row[field] for field in ("path", "split", "sha256", "group_id"))
        if row["label"] not in label_ids or int(row["label_id"]) != label_ids[row["label"]]:
            raise ValueError(f"Manifest label mismatch: {path}")
        if split not in {"train", "validation", "test"} or not group:
            raise ValueError(f"Invalid split/group: {path}")
        if path in paths:
            raise ValueError(f"Duplicate path: {path}")
        source = checked_path(root, path)
        if digest != sha256_file(source):
            raise ValueError(f"SHA256 mismatch: {path}")
        if digest in hash_splits and hash_splits[digest] != split:
            raise ValueError(f"SHA256 leaks across split: {path}")
        if group in group_splits and group_splits[group] != split:
            raise ValueError(f"Group leaks across split: {group}")
        paths.add(path)
        hash_splits[digest] = split
        group_splits[group] = split
    audit = {
        "total": len(rows), "baseline_rows": old_count,
        "splits": dict(Counter(row["split"] for row in rows)),
        "sources": dict(Counter(row["source"] for row in rows)),
        "personal_labels": dict(personal_labels), "personal_sessions": dict(sessions),
        "negative_actions": dict(negative_actions),
        "independent_negative_evaluation": False, "semantic_labels_reviewed": False,
        "split_protocol": "All personal samples train-only; old validation/test unchanged",
    }
    return rows, audit


def clip_signer(row: dict[str, Any]) -> str:
    """Seated clip files are named ``<signer>_repNN.mp4``; other sources have no signer id."""
    return Path(row["path"]).name.split("_")[0] if row["source"] == "seated" else row["source"]


def apply_curation(
    rows: Sequence[dict[str, Any]], curation: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Drop clips the owner ruled out (sign variant or wrong signing) from every split."""
    rules = curation.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ValueError("Curation needs at least one rule")
    labels = {row["label"] for row in rows}
    for rule in rules:
        if rule.get("label") not in labels or not rule.get("drop_sources") or not rule.get("reason"):
            raise ValueError(f"Invalid curation rule: {rule}")

    def dropped_by(row: dict[str, Any]) -> int | None:
        for index, rule in enumerate(rules):
            if (row["label"] == rule["label"] and row["source"] in rule["drop_sources"]
                    and rule.get("signer") in (None, clip_signer(row))):
                return index
        return None

    kept, dropped = [], Counter()
    for row in rows:
        index = dropped_by(row)
        if index is None:
            kept.append(row)
        else:
            dropped[(index, row["split"], row["source"])] += 1
    if not dropped:
        raise ValueError("Curation removed no clips")
    summary = {"version": curation.get("version"), "rules": rules,
               "dropped": [{"rule": index, "label": rules[index]["label"], "split": split, "source": source,
                            "clips": count} for (index, split, source), count in sorted(dropped.items())]}
    return kept, summary


def expand_head(old: nn.Linear) -> nn.Linear:
    expanded = nn.Linear(old.in_features, old.out_features + 1).to(old.weight)
    with torch.no_grad():
        expanded.weight[:old.out_features].copy_(old.weight)
        expanded.bias[:old.out_features].copy_(old.bias)
        expanded.weight[-1].zero_()
        expanded.bias[-1].copy_(old.bias.min() - 6)
    return expanded


def decode_uniform_frames(path: Path, sample_count: int = 16):
    import av
    from ml.visignlanguage import decode_video, temporal_indices

    selected = {}
    result = None
    try:
        with av.open(str(path)) as container:
            advertised = container.streams.video[0].frames
            if advertised > 0:
                indices = temporal_indices(advertised, sample_count, False).tolist()
                wanted = set(indices)
                decoded = 0
                for index, frame in enumerate(container.decode(video=0)):
                    decoded += 1
                    if index in wanted:
                        selected[index] = frame.to_image().convert("RGB")
                if decoded == advertised and set(selected) == wanted:
                    result = [selected[index].copy() for index in indices]
    finally:
        for image in selected.values():
            image.close()
    if result is not None:
        return result
    # Missing/inaccurate container counts must keep the original sampling result.
    frames = decode_video(path)
    try:
        return [frames[int(index)].copy() for index in temporal_indices(len(frames), sample_count, False)]
    finally:
        for image in frames:
            image.close()


def load_feature_cache(
    path: Path, identity: dict[str, Any], count: int, width: int,
) -> dict[str, Any]:
    if not path.exists():
        return {"identity": identity, "features": torch.zeros(count, width),
                "completed": torch.zeros(count, dtype=torch.bool)}
    cache = torch.load(path, map_location="cpu", weights_only=True)
    if cache.get("identity") != identity:
        raise ValueError("Feature cache identity mismatch")
    features, completed = cache.get("features"), cache.get("completed")
    if (not isinstance(features, torch.Tensor) or features.shape != (count, width)
            or features.dtype != torch.float32 or not isinstance(completed, torch.Tensor)
            or completed.shape != (count,) or completed.dtype != torch.bool
            or not torch.isfinite(features[completed]).all()):
        raise ValueError("Invalid feature cache tensors")
    if cache.get("integrity_sha256") != feature_cache_digest(cache):
        raise ValueError("Feature cache integrity mismatch")
    return cache


def feature_cache_digest(cache: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    header = {"identity": cache["identity"], "shape": list(cache["features"].shape)}
    digest.update(json.dumps(header, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    completed = cache["completed"]
    digest.update(completed.cpu().contiguous().numpy().tobytes())
    digest.update(cache["features"][completed].detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def save_cache(path: Path, cache: dict[str, Any]) -> None:
    cache["integrity_sha256"] = feature_cache_digest(cache)
    temporary = path.with_suffix(".tmp")
    torch.save(cache, temporary)
    temporary.replace(path)


def evaluate_features(
    head: nn.Module, features: torch.Tensor, targets: torch.Tensor,
    labels: Sequence[str], *, positive_class_count: int | None = None,
) -> dict[str, Any]:
    with torch.inference_mode():
        logits = head(features)
        if not torch.isfinite(logits).all():
            raise ValueError("Non-finite logits")
        probabilities = logits.softmax(dim=1)
        predicted = probabilities.argmax(dim=1)
        top2 = probabilities.topk(min(2, probabilities.shape[1]), dim=1).values
        accepted = top2[:, 0] >= .70
        if top2.shape[1] == 2:
            accepted &= top2[:, 0] - top2[:, 1] >= .15
        idle_id = labels.index(IDLE_LABEL) if IDLE_LABEL in labels else len(labels)
        accepted &= predicted != idle_id
        negative = targets == idle_id
        class_count = logits.shape[1]
        confusion = torch.bincount(targets * class_count + predicted, minlength=class_count ** 2).reshape(class_count, class_count).double()
        tp = confusion.diag()
        actual, guessed = confusion.sum(dim=1), confusion.sum(dim=0)
        precision, recall = tp / guessed.clamp_min(1), tp / actual.clamp_min(1)
        f1 = 2 * precision * recall / (precision + recall).clamp_min(1e-12)
        evaluated_classes = positive_class_count or class_count
        positive = ~negative
        negative_count = int(negative.sum())
        return {
            "samples": len(targets), "accuracy": float((predicted == targets).float().mean()),
            "macro_f1": float(f1[:evaluated_classes].mean()),
            "top3_accuracy": float((logits.topk(min(3, class_count), dim=1).indices == targets[:, None]).any(dim=1).float().mean()),
            "positive_samples": int(positive.sum()), "negative_samples": negative_count,
            "negative_false_accept_rate": float(accepted[negative].float().mean()) if negative_count else None,
            "negative_recognition_rate": float((predicted[negative] == idle_id).float().mean()) if negative_count else None,
            "positive_correct_accept_rate": float((accepted[positive] & (predicted[positive] == targets[positive])).float().mean()) if positive.any() else None,
            "per_class": {label: {"samples": int(actual[index]), "recall": float(recall[index]), "f1": float(f1[index])} for index, label in enumerate(labels)},
        }


def regression_gate(baseline: dict[str, Any], candidate: dict[str, Any]) -> bool:
    for key in ("accuracy", "macro_f1", "positive_correct_accept_rate"):
        old, new = baseline.get(key), candidate.get(key)
        if (not isinstance(old, (int, float)) or not isinstance(new, (int, float))
                or not math.isfinite(old) or not math.isfinite(new) or new < old - .02):
            return False
    return True
