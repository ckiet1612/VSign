from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort

from ml.landmarks_v4 import FEATURE_DIM, SEQUENCE_LENGTH, frame_presence, mirror_sequence_v4


CONFIDENCE_THRESHOLD = 0.56
MARGIN_THRESHOLD = 0.18
MINIMUM_DETECTED_FRAMES = 4
IDLE_LABEL = "Không ký hiệu"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - logits.max(axis=1, keepdims=True)
    exponentials = np.exp(shifted)
    return exponentials / exponentials.sum(axis=1, keepdims=True)


def grouped_metrics(
    values: np.ndarray,
    targets: np.ndarray,
    accepted: np.ndarray,
    correct: np.ndarray,
    idle_index: int,
) -> dict[str, dict[str, float | int | None]]:
    output: dict[str, dict[str, float | int | None]] = {}
    for value in sorted(set(values.astype(str).tolist())):
        selected = values.astype(str) == value
        positive = selected & (targets != idle_index)
        negative = selected & (targets == idle_index)
        positive_count = int(positive.sum())
        negative_count = int(negative.sum())
        output[value] = {
            "samples": int(selected.sum()),
            "positive_accepted_accuracy": (
                float(correct[positive].sum() / positive_count)
                if positive_count
                else None
            ),
            "negative_false_accept_rate": (
                float(accepted[negative].mean()) if negative_count else None
            ),
        }
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Đánh giá ONNX V4 trên camera set đã đóng băng"
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--model",
        type=Path,
        default=Path("ml/artifacts/landmark_v4/model.onnx"),
    )
    parser.add_argument(
        "--labels",
        type=Path,
        default=Path("ml/artifacts/landmark_v4/labels.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("ml/artifacts/landmark_v4/frozen_camera_metrics.json"),
    )
    args = parser.parse_args()

    frozen = json.loads(args.manifest.read_text(encoding="utf-8"))
    current_hash = sha256(args.dataset)
    if frozen.get("dataset_sha256") != current_hash:
        raise RuntimeError("Dataset không còn khớp manifest đóng băng")
    data = np.load(args.dataset)
    sequences = data["sequences"].astype(np.float32)
    targets = data["labels"].astype(np.int64)
    dataset_labels = data["label_names"].tolist()
    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    if dataset_labels != labels:
        raise ValueError("Thứ tự labels của frozen set không khớp model")
    if sequences.shape[1:] != (SEQUENCE_LENGTH, FEATURE_DIM):
        raise ValueError(f"Frozen dataset có shape sai: {sequences.shape}")

    session = ort.InferenceSession(str(args.model), providers=["CPUExecutionProvider"])
    views = np.concatenate((sequences, mirror_sequence_v4(sequences)), axis=0)
    raw_logits = session.run(None, {"landmarks": views})[0]
    logits = (raw_logits[: len(sequences)] + raw_logits[len(sequences) :]) / 2
    probabilities = softmax(logits)
    ordering = np.argsort(-probabilities, axis=1)
    top = ordering[:, 0]
    top_confidence = probabilities[np.arange(len(sequences)), top]
    second_confidence = probabilities[np.arange(len(sequences)), ordering[:, 1]]
    margins = top_confidence - second_confidence
    detected = (frame_presence(sequences).sum(axis=1) >= MINIMUM_DETECTED_FRAMES)
    idle_index = labels.index(IDLE_LABEL) if IDLE_LABEL in labels else -1
    accepted = (
        detected
        & (top != idle_index)
        & (top_confidence >= CONFIDENCE_THRESHOLD)
        & (margins >= MARGIN_THRESHOLD)
    )

    positive = targets != idle_index
    negative = ~positive if idle_index >= 0 else np.zeros(len(targets), dtype=np.bool_)
    correct = accepted & (top == targets)
    top3_correct = np.asarray(
        [target in row[:3] for target, row in zip(targets.tolist(), ordering.tolist())]
    )
    confusion = np.zeros((len(labels), len(labels) + 1), dtype=np.int64)
    for target, prediction, was_accepted in zip(targets, top, accepted):
        confusion[target, prediction if was_accepted else len(labels)] += 1

    per_class: dict[str, dict[str, float | int]] = {}
    for index, label in enumerate(labels):
        selected = targets == index
        count = int(selected.sum())
        per_class[label] = {
            "samples": count,
            "accepted_recall": float(correct[selected].mean()) if count else 0.0,
            "raw_top1_accuracy": float((top[selected] == targets[selected]).mean())
            if count
            else 0.0,
        }

    negative_by_source_label: dict[str, dict[str, float | int]] = {}
    false_accept_examples: list[dict[str, object]] = []
    if "source_labels" in data.files:
        source_labels = data["source_labels"].astype(str)
        for source_label in sorted(set(source_labels[negative].tolist())):
            selected = negative & (source_labels == source_label)
            count = int(selected.sum())
            negative_by_source_label[source_label] = {
                "samples": count,
                "false_accept_rate": float(accepted[selected].mean())
                if count
                else 0.0,
            }
        paths = (
            data["paths"].astype(str)
            if "paths" in data.files
            else np.full(len(targets), "")
        )
        for index in np.flatnonzero(negative & accepted).tolist():
            false_accept_examples.append(
                {
                    "path": str(paths[index]),
                    "source_label": str(source_labels[index]),
                    "predicted_label": labels[int(top[index])],
                    "confidence": float(top_confidence[index]),
                    "margin": float(margins[index]),
                }
            )

    sample = sequences[:1]
    for _ in range(10):
        session.run(None, {"landmarks": sample})
    timings: list[float] = []
    for _ in range(100):
        started = time.perf_counter()
        session.run(None, {"landmarks": sample})
        timings.append((time.perf_counter() - started) * 1000)

    positive_count = int(positive.sum())
    negative_count = int(negative.sum())
    metrics = {
        "model_sha256": sha256(args.model),
        "dataset_sha256": current_hash,
        "sample_count": int(len(sequences)),
        "positive_samples": positive_count,
        "negative_samples": negative_count,
        "thresholds_frozen_before_evaluation": {
            "confidence": CONFIDENCE_THRESHOLD,
            "margin": MARGIN_THRESHOLD,
            "minimum_detected_frames": MINIMUM_DETECTED_FRAMES,
        },
        "accepted_accuracy_positive": float(correct[positive].sum() / positive_count)
        if positive_count
        else 0.0,
        "raw_top1_accuracy_positive": float((top[positive] == targets[positive]).mean())
        if positive_count
        else 0.0,
        "raw_top3_accuracy_positive": float(top3_correct[positive].mean())
        if positive_count
        else 0.0,
        "positive_rejection_rate": float((~accepted[positive]).mean())
        if positive_count
        else 0.0,
        "negative_false_accept_rate": float(accepted[negative].mean())
        if negative_count
        else None,
        "onnx_cpu_median_ms": float(np.median(timings)),
        "onnx_cpu_p95_ms": float(np.percentile(timings, 95)),
        "per_class": per_class,
        "negative_by_source_label": negative_by_source_label,
        "false_accept_examples": false_accept_examples,
        "by_distance": (
            grouped_metrics(
                data["distances"], targets, accepted, correct, idle_index
            )
            if "distances" in data.files
            else {}
        ),
        "by_lighting": (
            grouped_metrics(
                data["lighting"], targets, accepted, correct, idle_index
            )
            if "lighting" in data.files
            else {}
        ),
        "by_negative_action": (
            grouped_metrics(
                data["negative_actions"],
                targets,
                accepted,
                correct,
                idle_index,
            )
            if "negative_actions" in data.files
            else {}
        ),
        "confusion_columns": labels + ["Rejected"],
        "confusion_matrix": confusion.tolist(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: value for key, value in metrics.items() if key not in {"per_class", "confusion_matrix", "confusion_columns"}}, ensure_ascii=False, indent=2))
    print(f"Đã lưu báo cáo: {args.output}")


if __name__ == "__main__":
    main()
