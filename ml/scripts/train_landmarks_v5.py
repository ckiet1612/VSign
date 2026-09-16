from __future__ import annotations

import argparse
import copy
import json
import random
import shutil
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset

from ml.landmarks_v2 import SEQUENCE_LENGTH, SplitIndices, stratified_hand_split
from ml.landmarks_v4 import FEATURE_DIM as V4_FEATURE_DIM
from ml.landmarks_v5 import (
    CONTEXT_DIM,
    CONTEXT_OFFSET,
    DEFAULT_FOCUS_LABELS,
    FEATURE_DIM,
    GuardedLandmarkV5,
    combine_v3_v4_sequences,
    mirror_sequence_v5,
)


class V5DevelopmentDataset(Dataset[tuple[torch.Tensor, torch.Tensor]]):
    def __init__(
        self,
        sequences: np.ndarray,
        labels: np.ndarray,
        indices: np.ndarray,
        *,
        augment: bool,
    ) -> None:
        self.sequences = sequences
        self.labels = labels
        self.indices = indices
        self.augment = augment

    def __len__(self) -> int:
        return len(self.indices)

    def __getitem__(self, item: int) -> tuple[torch.Tensor, torch.Tensor]:
        index = int(self.indices[item])
        sequence = self.sequences[index]
        if self.augment:
            if random.random() < 0.5:
                sequence = mirror_sequence_v5(sequence)
            else:
                sequence = sequence.copy()
            start = random.randint(0, 2)
            end = random.randint(13, SEQUENCE_LENGTH - 1)
            sample_indices = np.rint(
                np.linspace(start, end, SEQUENCE_LENGTH)
            ).astype(np.int64)
            sequence = sequence[sample_indices].copy()
            # The correction branch must tolerate an absent/unstable pose and
            # fall back to V3 instead of learning to depend on it absolutely.
            if random.random() < 0.16:
                sequence[:, CONTEXT_OFFSET:] = 0
            elif random.random() < 0.25:
                span_length = random.randint(2, 5)
                span_start = random.randint(0, SEQUENCE_LENGTH - span_length)
                sequence[
                    span_start : span_start + span_length, CONTEXT_OFFSET:
                ] = 0
        return torch.from_numpy(sequence), torch.tensor(
            self.labels[index], dtype=torch.long
        )


def accuracy(logits: torch.Tensor, targets: torch.Tensor) -> float:
    return float((logits.argmax(dim=1) == targets).float().mean().item())


def mean_true_probability(logits: torch.Tensor, targets: torch.Tensor) -> float:
    probabilities = torch.softmax(logits, dim=1)
    return float(probabilities.gather(1, targets[:, None]).mean().item())


def subset_metrics(
    logits: torch.Tensor,
    targets: torch.Tensor,
    focus_indices: list[int],
) -> dict[str, float]:
    focus_mask = torch.zeros_like(targets, dtype=torch.bool)
    for index in focus_indices:
        focus_mask |= targets == index
    stable_mask = ~focus_mask

    def selected_accuracy(mask: torch.Tensor) -> float:
        return accuracy(logits[mask], targets[mask]) if bool(mask.any()) else 0.0

    def selected_probability(mask: torch.Tensor) -> float:
        return (
            mean_true_probability(logits[mask], targets[mask])
            if bool(mask.any())
            else 0.0
        )

    return {
        "accuracy": accuracy(logits, targets),
        "true_probability": mean_true_probability(logits, targets),
        "focus_accuracy": selected_accuracy(focus_mask),
        "focus_true_probability": selected_probability(focus_mask),
        "stable_accuracy": selected_accuracy(stable_mask),
        "stable_true_probability": selected_probability(stable_mask),
    }


def infer_tta(
    model: nn.Module,
    sequences: np.ndarray,
    *,
    batch_size: int,
) -> torch.Tensor:
    model.eval()
    mirrored = mirror_sequence_v5(sequences)
    outputs: list[torch.Tensor] = []
    with torch.no_grad():
        for start in range(0, len(sequences), batch_size):
            normal = torch.from_numpy(sequences[start : start + batch_size])
            flipped = torch.from_numpy(mirrored[start : start + batch_size])
            outputs.append((model(normal) + model(flipped)) * 0.5)
    return torch.cat(outputs)


def per_class_accuracy(
    logits: torch.Tensor, targets: torch.Tensor, labels: list[str]
) -> dict[str, float]:
    predictions = logits.argmax(dim=1)
    output: dict[str, float] = {}
    for index, label in enumerate(labels):
        mask = targets == index
        output[label] = (
            float((predictions[mask] == targets[mask]).float().mean().item())
            if bool(mask.any())
            else 0.0
        )
    return output


def confusion_matrix(
    logits: torch.Tensor, targets: torch.Tensor, class_count: int
) -> list[list[int]]:
    matrix = torch.zeros((class_count, class_count), dtype=torch.int64)
    for target, predicted in zip(targets.tolist(), logits.argmax(dim=1).tolist()):
        matrix[target, predicted] += 1
    return matrix.tolist()


def benchmark_onnx(path: Path, example: np.ndarray) -> tuple[float, float]:
    session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    for _ in range(10):
        session.run(None, {"landmarks": example})
    timings: list[float] = []
    for _ in range(100):
        started = time.perf_counter()
        session.run(None, {"landmarks": example})
        timings.append((time.perf_counter() - started) * 1000)
    return float(np.median(timings)), float(np.percentile(timings, 95))


def append_v5_supplements(
    sequences: np.ndarray,
    targets: np.ndarray,
    hands: list[str],
    paths: list[str],
    split: SplitIndices,
    supplement_paths: list[Path],
    labels: list[str],
    *,
    seed: int,
    min_detected_hand_frames: int = 1,
) -> tuple[
    np.ndarray,
    np.ndarray,
    list[str],
    list[str],
    SplitIndices,
    int,
    int,
]:
    train_indices = split.train.tolist()
    validation_indices = split.validation.tolist()
    seen_paths = set(paths)
    added = 0
    rejected_for_quality = 0
    for supplement_path in supplement_paths:
        supplement = np.load(supplement_path, allow_pickle=True)
        supplement_sequences = supplement["sequences"].astype(np.float32)
        supplement_targets = supplement["labels"].astype(np.int64)
        supplement_hands = [str(value) for value in supplement["hands"].tolist()]
        supplement_sample_paths = [
            str(value) for value in supplement["paths"].tolist()
        ]
        supplement_labels = [
            str(value) for value in supplement["label_names"].tolist()
        ]
        if supplement_sequences.shape[1:] != (SEQUENCE_LENGTH, FEATURE_DIM):
            raise ValueError(
                f"Supplement V5 sai shape tại {supplement_path}: "
                f"{supplement_sequences.shape}"
            )
        if supplement_labels != labels:
            raise ValueError(f"Nhãn supplement V5 không khớp: {supplement_path}")
        if not (
            len(supplement_sequences)
            == len(supplement_targets)
            == len(supplement_hands)
            == len(supplement_sample_paths)
        ):
            raise ValueError(f"Supplement V5 lệch số mẫu: {supplement_path}")

        supplement_split_names: np.ndarray | None = None
        if "splits" in supplement.files:
            supplement_split_names = supplement["splits"].astype(str)
            if len(supplement_split_names) != len(supplement_sequences):
                raise ValueError(
                    f"Supplement V5 lệch số split: {supplement_path}"
                )
            invalid = sorted(
                set(supplement_split_names.tolist()) - {"train", "validation"}
            )
            if invalid:
                raise ValueError(
                    f"Supplement V5 chứa split cấm {invalid}: {supplement_path}"
                )

        quality_mask = np.ones(len(supplement_sequences), dtype=bool)
        if "detected_hand_frames" in supplement.files:
            detected_hand_frames = supplement["detected_hand_frames"].astype(
                np.int64
            )
            if len(detected_hand_frames) != len(supplement_sequences):
                raise ValueError(
                    f"Supplement V5 lệch số đo chất lượng: {supplement_path}"
                )
            quality_mask &= detected_hand_frames >= min_detected_hand_frames
            rejected_for_quality += int((~quality_mask).sum())

        keep = np.asarray(
            [
                index
                for index, sample_path in enumerate(supplement_sample_paths)
                if quality_mask[index] and sample_path not in seen_paths
            ],
            dtype=np.int64,
        )
        if not len(keep):
            continue
        kept_sequences = supplement_sequences[keep]
        kept_targets = supplement_targets[keep]
        kept_hands = [supplement_hands[index] for index in keep.tolist()]
        kept_paths = [supplement_sample_paths[index] for index in keep.tolist()]
        base_index = len(sequences)
        sequences = np.concatenate((sequences, kept_sequences), axis=0)
        targets = np.concatenate((targets, kept_targets), axis=0)
        hands.extend(kept_hands)
        paths.extend(kept_paths)
        seen_paths.update(kept_paths)

        if supplement_split_names is not None:
            split_names = supplement_split_names[keep]
            train_indices.extend(
                (base_index + np.flatnonzero(split_names == "train")).tolist()
            )
            validation_indices.extend(
                (
                    base_index
                    + np.flatnonzero(split_names == "validation")
                ).tolist()
            )
        else:
            local_split = stratified_hand_split(
                kept_targets, kept_hands, seed=seed
            )
            train_indices.extend((base_index + local_split.train).tolist())
            validation_indices.extend(
                (base_index + local_split.validation).tolist()
            )
        added += len(keep)
    return (
        sequences,
        targets,
        hands,
        paths,
        SplitIndices(
            train=np.asarray(train_indices, dtype=np.int64),
            validation=np.asarray(validation_indices, dtype=np.int64),
        ),
        added,
        rejected_for_quality,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train guarded VSign V5 from aligned local V3/V4 features"
    )
    parser.add_argument(
        "--v3-dataset",
        type=Path,
        default=Path("ml/data/processed/landmarks_v2/collected_common20.npz"),
    )
    parser.add_argument(
        "--v4-dataset",
        type=Path,
        default=Path("ml/data/processed/landmarks_v4/collected_common20.npz"),
    )
    parser.add_argument(
        "--baseline-checkpoint",
        type=Path,
        default=Path("ml/artifacts/landmark_v3/model.pt"),
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("ml/artifacts/landmark_v5")
    )
    parser.add_argument(
        "--web-model-dir", type=Path, default=Path("apps/web/public/models")
    )
    parser.add_argument(
        "--supplement-v5-dataset",
        action="append",
        type=Path,
        default=[],
        help=(
            "NPZ V5 bổ sung; có thể lặp lại cho public train/validation và "
            "webcam mới. Mẫu trùng path được bỏ."
        ),
    )
    parser.add_argument(
        "--require-samples-per-label",
        type=int,
        default=0,
        help="Dừng train nếu bất kỳ từ nào chưa đủ số video thật yêu cầu",
    )
    parser.add_argument(
        "--min-detected-hand-frames",
        type=int,
        default=1,
        help=(
            "Loại supplement không có đủ frame phát hiện tay; mặc định loại "
            "clip hoàn toàn không có landmark tay"
        ),
    )
    parser.add_argument("--epochs", type=int, default=180)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--learning-rate", type=float, default=1.2e-3)
    parser.add_argument("--patience", type=int, default=45)
    parser.add_argument("--seed", type=int, default=20260911)
    args = parser.parse_args()
    if args.min_detected_hand_frames < 0:
        raise ValueError("--min-detected-hand-frames không được âm")

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.set_num_threads(min(4, max(1, torch.get_num_threads())))

    v3 = np.load(args.v3_dataset, allow_pickle=True)
    v4 = np.load(args.v4_dataset, allow_pickle=True)
    if v4["sequences"].shape[-1] != V4_FEATURE_DIM:
        raise ValueError("Dataset V4 không đúng feature contract 183")
    labels = [str(value) for value in v3["label_names"].tolist()]
    if labels != [str(value) for value in v4["label_names"].tolist()]:
        raise ValueError("Thứ tự nhãn V3/V4 không khớp")
    if not np.array_equal(v3["labels"], v4["labels"]):
        raise ValueError("Nhãn từng mẫu V3/V4 không khớp")
    if v3["paths"].astype(str).tolist() != v4["paths"].astype(str).tolist():
        raise ValueError("Video từng mẫu V3/V4 không khớp; không được ghép gần đúng")

    sequences = combine_v3_v4_sequences(v3["sequences"], v4["sequences"])
    targets = v3["labels"].astype(np.int64)
    hands = [str(value) for value in v3["hands"].tolist()]
    sample_paths = [str(value) for value in v3["paths"].tolist()]
    focus_indices = [labels.index(label) for label in DEFAULT_FOCUS_LABELS]
    split = stratified_hand_split(targets, hands, seed=args.seed)
    (
        sequences,
        targets,
        hands,
        sample_paths,
        split,
        supplement_count,
        rejected_supplement_count,
    ) = append_v5_supplements(
        sequences,
        targets,
        hands,
        sample_paths,
        split,
        args.supplement_v5_dataset,
        labels,
        seed=args.seed,
        min_detected_hand_frames=args.min_detected_hand_frames,
    )
    if rejected_supplement_count:
        print(
            f"Đã loại {rejected_supplement_count} clip supplement không đạt "
            f"{args.min_detected_hand_frames} frame tay",
            flush=True,
        )
    class_counts = np.bincount(targets, minlength=len(labels))
    if args.require_samples_per_label > 0:
        missing = {
            label: int(class_counts[index])
            for index, label in enumerate(labels)
            if class_counts[index] < args.require_samples_per_label
        }
        if missing:
            raise RuntimeError(
                f"Chưa đủ {args.require_samples_per_label} video thật/từ: {missing}"
            )
    validation_sequences = sequences[split.validation]
    validation_targets = torch.from_numpy(targets[split.validation])

    checkpoint = torch.load(
        args.baseline_checkpoint, map_location="cpu", weights_only=False
    )
    if checkpoint["labels"] != labels:
        raise ValueError("Nhãn checkpoint V3 không khớp dataset")
    model = GuardedLandmarkV5(
        len(labels), focus_indices=focus_indices, max_logit_correction=1.25
    )
    model.load_baseline_state(checkpoint["model_state"])

    baseline_logits = infer_tta(
        model, validation_sequences, batch_size=args.batch_size
    )
    baseline_metrics = subset_metrics(
        baseline_logits, validation_targets, focus_indices
    )
    best_metrics = baseline_metrics
    best_state = copy.deepcopy(model.state_dict())
    # The guarded selector below uses true-label confidence as the development
    # objective. Epoch zero remains a valid exact-V3 fallback.
    best_focus_probability = baseline_metrics["focus_true_probability"]
    best_epoch = 0
    stale_epochs = 0
    history: list[dict[str, float]] = []

    loader = DataLoader(
        V5DevelopmentDataset(
            sequences, targets, split.train, augment=True
        ),
        batch_size=args.batch_size,
        shuffle=True,
        generator=torch.Generator().manual_seed(args.seed),
    )
    trainable = [parameter for parameter in model.parameters() if parameter.requires_grad]
    optimizer = torch.optim.AdamW(
        trainable, lr=args.learning_rate, weight_decay=2e-3
    )
    label_weights = torch.ones(len(labels), dtype=torch.float32)
    label_weights[focus_indices] = 2.25
    criterion = nn.CrossEntropyLoss(weight=label_weights, label_smoothing=0.035)

    for epoch in range(1, args.epochs + 1):
        model.train()
        total_loss = 0.0
        seen = 0
        for inputs, target in loader:
            optimizer.zero_grad(set_to_none=True)
            logits = model(inputs)
            loss = criterion(logits, target)
            loss.backward()
            nn.utils.clip_grad_norm_(trainable, max_norm=2.0)
            optimizer.step()
            total_loss += float(loss.item()) * len(target)
            seen += len(target)

        validation_logits = infer_tta(
            model, validation_sequences, batch_size=args.batch_size
        )
        metrics = subset_metrics(validation_logits, validation_targets, focus_indices)
        row = {
            "epoch": float(epoch),
            "train_loss": total_loss / seen,
            **metrics,
        }
        history.append(row)

        # A V5 checkpoint is allowed to replace epoch zero only if it preserves
        # top-1 and confidence on stable labels and increases focus confidence.
        eligible = (
            metrics["accuracy"] >= baseline_metrics["accuracy"] - 1e-9
            and metrics["stable_accuracy"]
            >= baseline_metrics["stable_accuracy"] - 1e-9
            and metrics["stable_true_probability"]
            >= baseline_metrics["stable_true_probability"] - 1e-7
            and metrics["focus_accuracy"]
            >= baseline_metrics["focus_accuracy"] - 1e-9
        )
        improved = (
            metrics["focus_true_probability"] > best_focus_probability + 1e-5
        )
        if eligible and improved:
            best_focus_probability = metrics["focus_true_probability"]
            best_metrics = metrics
            best_state = copy.deepcopy(model.state_dict())
            best_epoch = epoch
            stale_epochs = 0
        else:
            stale_epochs += 1
        if epoch == 1 or epoch % 10 == 0:
            print(
                f"Epoch {epoch:03d}: train={row['train_loss']:.4f} "
                f"val={metrics['accuracy']:.3f} "
                f"focus_p={metrics['focus_true_probability']:.3f} "
                f"stable={metrics['stable_accuracy']:.3f}",
                flush=True,
            )
        if stale_epochs >= args.patience:
            print(f"Dừng sớm ở epoch {epoch}", flush=True)
            break

    model.load_state_dict(best_state)
    model.eval()
    final_logits = infer_tta(model, validation_sequences, batch_size=args.batch_size)
    final_metrics = subset_metrics(final_logits, validation_targets, focus_indices)
    correction = final_logits - baseline_logits

    args.output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = args.output_dir / "model.pt"
    onnx_path = args.output_dir / "model.onnx"
    torch.save(
        {
            "model_state": model.state_dict(),
            "labels": labels,
            "focus_labels": list(DEFAULT_FOCUS_LABELS),
            "feature_dim": FEATURE_DIM,
            "context_dim": CONTEXT_DIM,
            "sequence_length": SEQUENCE_LENGTH,
            "architecture": "guarded-landmark-v5-bootstrap",
            "baseline": "landmark-keyframe-v3-personalized",
        },
        checkpoint_path,
    )
    example = sequences[split.validation[:1]].astype(np.float32)
    torch.onnx.export(
        model,
        torch.from_numpy(example),
        onnx_path,
        input_names=["landmarks"],
        output_names=["logits"],
        dynamic_axes={"landmarks": {0: "batch"}, "logits": {0: "batch"}},
        opset_version=17,
    )
    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    onnx_logits = session.run(None, {"landmarks": example})[0]
    with torch.no_grad():
        torch_logits = model(torch.from_numpy(example)).numpy()
    median_ms, p95_ms = benchmark_onnx(onnx_path, example)

    metrics_document = {
        "model_version": "guarded-landmark-v5-bootstrap",
        "status": "experimental-development-only",
        "runtime_default": False,
        "release_gate_passed": False,
        "source": (
            f"207 aligned local bootstrap clips plus {supplement_count} unique "
            "V5 supplement clips; no frozen release camera data or public test"
        ),
        "architecture": (
            "frozen exact V3 plus pose-gated, focus-label-only residual capped "
            "at +/-1.25 logits; residual disabled when V3 top-1 is stable"
        ),
        "feature_schema": "exact V3 128 + V4 body context 57",
        "focus_labels": list(DEFAULT_FOCUS_LABELS),
        "train_samples": int(len(split.train)),
        "validation_samples": int(len(split.validation)),
        "total_unique_samples": int(len(sequences)),
        "supplement_samples": int(supplement_count),
        "rejected_supplement_samples": int(rejected_supplement_count),
        "minimum_detected_hand_frames": int(args.min_detected_hand_frames),
        "samples_per_label": {
            label: int(class_counts[index]) for index, label in enumerate(labels)
        },
        "best_epoch": best_epoch,
        "baseline_validation": baseline_metrics,
        "v5_validation": final_metrics,
        "per_class_accuracy": per_class_accuracy(
            final_logits, validation_targets, labels
        ),
        "confusion_matrix": confusion_matrix(
            final_logits, validation_targets, len(labels)
        ),
        "maximum_tta_logit_change": float(correction.abs().max().item()),
        "mean_tta_logit_change": float(correction.abs().mean().item()),
        "onnx_export_max_difference": float(
            np.abs(onnx_logits - torch_logits).max()
        ),
        "onnx_cpu_median_ms": median_ms,
        "onnx_cpu_p95_ms": p95_ms,
        "next_step": (
            "fine-tune with the isolated V5 development capture plan, then run "
            "paired V3/V5 manual and automatic frozen-camera evaluation"
        ),
        "history": history,
    }
    (args.output_dir / "labels.json").write_text(
        json.dumps(labels, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_dir / "metrics.json").write_text(
        json.dumps(metrics_document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.web_model_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(onnx_path, args.web_model_dir / "vsign-landmark-v5.onnx")
    shutil.copy2(
        args.output_dir / "labels.json",
        args.web_model_dir / "vsign-landmark-v5.labels.json",
    )
    print(
        f"V5 bootstrap epoch {best_epoch}: "
        f"val={final_metrics['accuracy']:.3f}, "
        f"focus_p={final_metrics['focus_true_probability']:.3f}, "
        f"stable={final_metrics['stable_accuracy']:.3f}",
        flush=True,
    )
    print(f"ONNX CPU: median={median_ms:.3f}ms, p95={p95_ms:.3f}ms", flush=True)
    print(f"Đã xuất {onnx_path} và model web V5 thử nghiệm", flush=True)


if __name__ == "__main__":
    main()
