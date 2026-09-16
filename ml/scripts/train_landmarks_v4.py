from __future__ import annotations

import argparse
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

from ml.landmarks_v2 import SplitIndices, stratified_hand_split
from ml.landmarks_v4 import (
    COORDINATES,
    FEATURE_DIM,
    HAND_GLOBAL_OFFSET,
    HAND_PRESENCE_OFFSET,
    HAND_SHAPE_DIM,
    HAND_SHAPE_OFFSET,
    MAX_HANDS,
    PAIR_GEOMETRY_OFFSET,
    POSE_COORDINATE_OFFSET,
    POSE_LANDMARK_COUNT,
    POSE_PRESENCE_OFFSET,
    SEQUENCE_LENGTH,
    UnifiedLandmarkV4,
    mirror_sequence_v4,
    recompute_pair_geometry_v4,
)


class LandmarkV4Dataset(Dataset[tuple[torch.Tensor, torch.Tensor]]):
    def __init__(
        self,
        sequences: np.ndarray,
        labels: np.ndarray,
        indices: np.ndarray,
        *,
        augment: bool,
        include_mirror_copy: bool = False,
        occlusion_probability: float = 0.55,
    ) -> None:
        self.sequences = sequences
        self.labels = labels
        self.indices = indices
        self.augment = augment
        self.include_mirror_copy = include_mirror_copy
        self.occlusion_probability = occlusion_probability

    def __len__(self) -> int:
        return len(self.indices) * (2 if self.include_mirror_copy else 1)

    @staticmethod
    def occlude_hand(
        sequence: np.ndarray, hand_index: int, span_start: int, span_end: int
    ) -> np.ndarray:
        result = sequence.copy()
        shape_start = HAND_SHAPE_OFFSET + hand_index * HAND_SHAPE_DIM
        global_start = HAND_GLOBAL_OFFSET + hand_index * COORDINATES
        result[span_start:span_end, shape_start : shape_start + HAND_SHAPE_DIM] = 0
        result[span_start:span_end, global_start : global_start + COORDINATES] = 0
        result[span_start:span_end, HAND_PRESENCE_OFFSET + hand_index] = 0
        return recompute_pair_geometry_v4(result)

    def _augment(self, sequence: np.ndarray, *, mirror: bool) -> np.ndarray:
        result = mirror_sequence_v4(sequence) if mirror else sequence.copy()
        temporal_start = random.randint(0, 3)
        temporal_end = random.randint(12, SEQUENCE_LENGTH - 1)
        temporal_indices = np.rint(
            np.linspace(temporal_start, temporal_end, SEQUENCE_LENGTH)
        ).astype(np.int64)
        result = result[temporal_indices].copy()

        hand_mask = result[:, HAND_PRESENCE_OFFSET:POSE_PRESENCE_OFFSET]
        pose_mask = result[:, POSE_PRESENCE_OFFSET:]
        shapes = result[:, HAND_SHAPE_OFFSET:HAND_GLOBAL_OFFSET].reshape(
            SEQUENCE_LENGTH, MAX_HANDS, HAND_SHAPE_DIM
        )
        globals_ = result[:, HAND_GLOBAL_OFFSET:POSE_COORDINATE_OFFSET].reshape(
            SEQUENCE_LENGTH, MAX_HANDS, COORDINATES
        )
        pose = result[:, POSE_COORDINATE_OFFSET:PAIR_GEOMETRY_OFFSET].reshape(
            SEQUENCE_LENGTH, POSE_LANDMARK_COUNT, COORDINATES
        )

        shapes *= random.uniform(0.92, 1.08)
        shapes += np.random.normal(0.0, 0.018, shapes.shape).astype(
            np.float32
        ) * hand_mask[..., None]
        globals_ += np.random.normal(0.0, 0.025, globals_.shape).astype(
            np.float32
        ) * hand_mask[..., None]
        pose += np.random.normal(0.0, 0.018, pose.shape).astype(
            np.float32
        ) * pose_mask[..., None]

        if random.random() < self.occlusion_probability:
            available = np.flatnonzero(hand_mask.max(axis=0) > 0.5)
            if len(available):
                hand_index = int(random.choice(available.tolist()))
                span_length = random.randint(3, 7)
                span_start = random.randint(1, SEQUENCE_LENGTH - span_length - 1)
                result = self.occlude_hand(
                    result, hand_index, span_start, span_start + span_length
                )

        if random.random() < 0.2:
            pose_index = random.randrange(7, POSE_LANDMARK_COUNT)
            span_length = random.randint(1, 4)
            span_start = random.randint(0, SEQUENCE_LENGTH - span_length)
            coordinate_start = POSE_COORDINATE_OFFSET + pose_index * COORDINATES
            result[
                span_start : span_start + span_length,
                coordinate_start : coordinate_start + COORDINATES,
            ] = 0
            result[
                span_start : span_start + span_length,
                POSE_PRESENCE_OFFSET + pose_index,
            ] = 0
        return recompute_pair_geometry_v4(result)

    def __getitem__(self, item: int) -> tuple[torch.Tensor, torch.Tensor]:
        mirror = self.include_mirror_copy and item >= len(self.indices)
        index = int(self.indices[item % len(self.indices)])
        sequence = self.sequences[index]
        if self.augment:
            sequence = self._augment(sequence, mirror=mirror)
        return torch.from_numpy(sequence), torch.tensor(
            self.labels[index], dtype=torch.long
        )


def calculate_metrics(
    logits: torch.Tensor, targets: torch.Tensor, label_count: int
) -> dict[str, object]:
    predictions = logits.argmax(dim=1)
    confusion = torch.zeros((label_count, label_count), dtype=torch.int64)
    for target, predicted in zip(targets.tolist(), predictions.tolist()):
        confusion[target, predicted] += 1
    true_positive = confusion.diag().float()
    precision = true_positive / confusion.sum(dim=0).clamp(min=1)
    recall = true_positive / confusion.sum(dim=1).clamp(min=1)
    f1 = 2 * precision * recall / (precision + recall).clamp(min=1e-9)
    return {
        "accuracy": float((predictions == targets).float().mean().item()),
        "macro_f1": float(f1.mean().item()),
        "confusion_matrix": confusion.tolist(),
        "per_class_accuracy": recall.tolist(),
    }


def evaluate(
    model: nn.Module,
    loader: DataLoader[tuple[torch.Tensor, torch.Tensor]],
    device: torch.device,
    label_count: int,
) -> tuple[float, dict[str, object], torch.Tensor, torch.Tensor]:
    model.eval()
    criterion = nn.CrossEntropyLoss()
    losses: list[float] = []
    logits: list[torch.Tensor] = []
    targets: list[torch.Tensor] = []
    with torch.no_grad():
        for inputs, target in loader:
            output = model(inputs.to(device))
            losses.append(float(criterion(output, target.to(device)).item()) * len(target))
            logits.append(output.cpu())
            targets.append(target)
    all_logits = torch.cat(logits)
    all_targets = torch.cat(targets)
    return (
        sum(losses) / len(all_targets),
        calculate_metrics(all_logits, all_targets, label_count),
        all_logits,
        all_targets,
    )


def deterministic_occlusion(sequences: np.ndarray) -> np.ndarray:
    output = sequences.copy()
    for sample_index in range(len(output)):
        presence = output[
            sample_index, :, HAND_PRESENCE_OFFSET:POSE_PRESENCE_OFFSET
        ].sum(axis=0)
        output[sample_index] = LandmarkV4Dataset.occlude_hand(
            output[sample_index], int(np.argmax(presence)), 5, 11
        )
    return output


def benchmark_onnx(model_path: Path, sample: np.ndarray) -> tuple[float, float]:
    session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    for _ in range(10):
        session.run(None, {input_name: sample})
    timings: list[float] = []
    for _ in range(100):
        started = time.perf_counter()
        session.run(None, {input_name: sample})
        timings.append((time.perf_counter() - started) * 1000)
    return float(np.median(timings)), float(np.percentile(timings, 95))


def main() -> None:
    parser = argparse.ArgumentParser(description="Train unified VSign Landmark V4")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("ml/data/processed/landmarks_v4/collected_common20_idle.npz"),
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("ml/artifacts/landmark_v4")
    )
    parser.add_argument(
        "--web-model-dir", type=Path, default=Path("apps/web/public/models")
    )
    parser.add_argument(
        "--supplement-dataset",
        type=Path,
        default=None,
        help="NPZ public V4.1 có splits train/validation; split test bị bỏ qua",
    )
    parser.add_argument("--epochs", type=int, default=360)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--learning-rate", type=float, default=1.8e-3)
    parser.add_argument("--seed", type=int, default=20260911)
    parser.add_argument("--patience", type=int, default=70)
    parser.add_argument("--device", choices=("cpu", "mps"), default="cpu")
    parser.add_argument("--occlusion-probability", type=float, default=0.55)
    args = parser.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.set_num_threads(min(4, max(1, torch.get_num_threads())))
    if not 0 <= args.occlusion_probability <= 1:
        raise ValueError("--occlusion-probability phải nằm trong khoảng 0..1")

    data = np.load(args.dataset)
    sequences = data["sequences"].astype(np.float32)
    targets = data["labels"].astype(np.int64)
    hands = data["hands"].tolist()
    labels = data["label_names"].tolist()
    if sequences.shape[1:] != (SEQUENCE_LENGTH, FEATURE_DIM):
        raise ValueError(f"Dataset V4 có shape không hợp lệ: {sequences.shape}")
    if "is_negative" in data.files:
        is_negative = data["is_negative"].astype(np.bool_)
        source_indices = data["source_sample_index"].astype(np.int64)
        positive_indices = np.flatnonzero(~is_negative)
        positive_split = stratified_hand_split(
            targets[positive_indices],
            [hands[index] for index in positive_indices.tolist()],
            seed=args.seed,
        )
        positive_train = positive_indices[positive_split.train]
        positive_validation = positive_indices[positive_split.validation]
        train_sources = set(positive_train.tolist())
        negative_indices = np.flatnonzero(is_negative)
        negative_train = np.asarray(
            [
                index
                for index in negative_indices.tolist()
                if int(source_indices[index]) in train_sources
            ],
            dtype=np.int64,
        )
        negative_validation = np.asarray(
            [
                index
                for index in negative_indices.tolist()
                if int(source_indices[index]) not in train_sources
            ],
            dtype=np.int64,
        )
        split = SplitIndices(
            train=np.concatenate((positive_train, negative_train)),
            validation=np.concatenate((positive_validation, negative_validation)),
        )
    else:
        is_negative = np.zeros(len(sequences), dtype=np.bool_)
        split = stratified_hand_split(targets, hands, seed=args.seed)

    local_validation_indices = split.validation.copy()
    supplement_validation_indices = np.empty(0, dtype=np.int64)
    supplement_train_count = 0
    supplement_validation_count = 0
    if args.supplement_dataset is not None:
        supplement = np.load(args.supplement_dataset)
        supplement_sequences = supplement["sequences"].astype(np.float32)
        supplement_targets = supplement["labels"].astype(np.int64)
        supplement_labels = supplement["label_names"].tolist()
        supplement_splits = supplement["splits"].astype(str)
        if supplement_sequences.shape[1:] != (SEQUENCE_LENGTH, FEATURE_DIM):
            raise ValueError(
                f"Supplement V4.1 có shape không hợp lệ: {supplement_sequences.shape}"
            )
        if supplement_labels != labels:
            raise ValueError("Thứ tự nhãn supplement không khớp dataset local")
        allowed_splits = {"train", "validation", "test"}
        if not set(supplement_splits.tolist()) <= allowed_splits:
            raise ValueError("Supplement chứa split không hợp lệ")
        supplement_train = np.flatnonzero(supplement_splits == "train")
        supplement_validation = np.flatnonzero(supplement_splits == "validation")
        supplement_keep = np.concatenate(
            (supplement_train, supplement_validation)
        )
        base_count = len(sequences)
        sequences = np.concatenate((sequences, supplement_sequences[supplement_keep]))
        targets = np.concatenate((targets, supplement_targets[supplement_keep]))
        supplement_negative = (
            supplement["is_negative"].astype(np.bool_)[supplement_keep]
            if "is_negative" in supplement.files
            else supplement_targets[supplement_keep] == labels.index("Không ký hiệu")
        )
        is_negative = np.concatenate((is_negative, supplement_negative))
        split = SplitIndices(
            train=np.concatenate(
                (
                    split.train,
                    base_count + np.arange(len(supplement_train), dtype=np.int64),
                )
            ),
            validation=np.concatenate(
                (
                    split.validation,
                    base_count
                    + len(supplement_train)
                    + np.arange(len(supplement_validation), dtype=np.int64),
                )
            ),
        )
        supplement_validation_indices = split.validation[
            len(local_validation_indices) :
        ].copy()
        supplement_train_count = len(supplement_train)
        supplement_validation_count = len(supplement_validation)

    train_loader = DataLoader(
        LandmarkV4Dataset(
            sequences,
            targets,
            split.train,
            augment=True,
            include_mirror_copy=True,
            occlusion_probability=args.occlusion_probability,
        ),
        batch_size=args.batch_size,
        shuffle=True,
        generator=torch.Generator().manual_seed(args.seed),
    )
    validation_loader = DataLoader(
        LandmarkV4Dataset(sequences, targets, split.validation, augment=False),
        batch_size=args.batch_size,
        shuffle=False,
    )
    mirrored_loader = DataLoader(
        LandmarkV4Dataset(
            mirror_sequence_v4(sequences), targets, split.validation, augment=False
        ),
        batch_size=args.batch_size,
        shuffle=False,
    )
    occluded_loader = DataLoader(
        LandmarkV4Dataset(
            deterministic_occlusion(sequences), targets, split.validation, augment=False
        ),
        batch_size=args.batch_size,
        shuffle=False,
    )

    if args.device == "mps" and not torch.backends.mps.is_available():
        raise RuntimeError("PyTorch hiện tại không hỗ trợ MPS trên máy này")
    device = torch.device(args.device)
    model = UnifiedLandmarkV4(len(labels)).to(device)
    class_counts = np.bincount(targets[split.train], minlength=len(labels))
    class_weights = np.sqrt(class_counts.max() / np.maximum(class_counts, 1))
    criterion = nn.CrossEntropyLoss(
        weight=torch.tensor(class_weights, dtype=torch.float32, device=device),
        label_smoothing=0.07,
    )
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=args.learning_rate, weight_decay=2e-3
    )
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="min", factor=0.5, patience=15, min_lr=2e-5
    )

    best_loss = float("inf")
    best_state: dict[str, torch.Tensor] | None = None
    best_epoch = stale_epochs = 0
    history: list[dict[str, float]] = []
    for epoch in range(1, args.epochs + 1):
        model.train()
        total_loss = 0.0
        seen = 0
        for inputs, target in train_loader:
            inputs, target = inputs.to(device), target.to(device)
            optimizer.zero_grad(set_to_none=True)
            output = model(inputs)
            loss = criterion(output, target)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), max_norm=3.0)
            optimizer.step()
            total_loss += float(loss.item()) * len(target)
            seen += len(target)

        validation_loss, validation_metrics, _, _ = evaluate(
            model, validation_loader, device, len(labels)
        )
        mirrored_loss, mirrored_metrics, _, _ = evaluate(
            model, mirrored_loader, device, len(labels)
        )
        occluded_loss, occluded_metrics, _, _ = evaluate(
            model, occluded_loader, device, len(labels)
        )
        robust_loss = validation_loss * 0.4 + mirrored_loss * 0.25 + occluded_loss * 0.35
        scheduler.step(robust_loss)
        row = {
            "epoch": float(epoch),
            "train_loss": total_loss / seen,
            "validation_loss": validation_loss,
            "validation_accuracy": float(validation_metrics["accuracy"]),
            "mirrored_validation_accuracy": float(mirrored_metrics["accuracy"]),
            "occluded_validation_accuracy": float(occluded_metrics["accuracy"]),
        }
        history.append(row)
        if robust_loss < best_loss - 1e-4:
            best_loss, best_epoch, stale_epochs = robust_loss, epoch, 0
            best_state = {
                key: value.detach().cpu().clone()
                for key, value in model.state_dict().items()
            }
        else:
            stale_epochs += 1
        if epoch == 1 or epoch % 10 == 0:
            print(
                f"Epoch {epoch:03d}: train={row['train_loss']:.4f} "
                f"val={validation_loss:.4f}/{validation_metrics['accuracy']:.3f} "
                f"mirror={mirrored_metrics['accuracy']:.3f} "
                f"occluded={occluded_metrics['accuracy']:.3f}",
                flush=True,
            )
        if stale_epochs >= args.patience:
            print(f"Dừng sớm ở epoch {epoch}", flush=True)
            break

    if best_state is None:
        raise RuntimeError("Không tạo được checkpoint V4")
    model.load_state_dict(best_state)
    model.to("cpu").eval()
    validation_loss, validation_metrics, logits, validation_targets = evaluate(
        model, validation_loader, torch.device("cpu"), len(labels)
    )
    mirrored_loss, mirrored_metrics, _, _ = evaluate(
        model, mirrored_loader, torch.device("cpu"), len(labels)
    )
    occluded_loss, occluded_metrics, _, _ = evaluate(
        model, occluded_loader, torch.device("cpu"), len(labels)
    )
    _, local_validation_metrics, _, _ = evaluate(
        model,
        DataLoader(
            LandmarkV4Dataset(
                sequences, targets, local_validation_indices, augment=False
            ),
            batch_size=args.batch_size,
            shuffle=False,
        ),
        torch.device("cpu"),
        len(labels),
    )
    public_validation_metrics: dict[str, object] | None = None
    if len(supplement_validation_indices):
        _, public_validation_metrics, _, _ = evaluate(
            model,
            DataLoader(
                LandmarkV4Dataset(
                    sequences,
                    targets,
                    supplement_validation_indices,
                    augment=False,
                ),
                batch_size=args.batch_size,
                shuffle=False,
            ),
            torch.device("cpu"),
            len(labels),
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = args.output_dir / "model.pt"
    onnx_path = args.output_dir / "model.onnx"
    torch.save(
        {
            "model_state": model.state_dict(),
            "labels": labels,
            "feature_dim": FEATURE_DIM,
            "sequence_length": SEQUENCE_LENGTH,
            "architecture": "unified-landmark-v4.1",
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

    probabilities = torch.softmax(logits, dim=1)
    top_two = probabilities.topk(2, dim=1).values
    correct = logits.argmax(dim=1) == validation_targets
    correct_confidence = probabilities.max(dim=1).values[correct]
    correct_margin = (top_two[:, 0] - top_two[:, 1])[correct]
    metrics = {
        "model_version": "unified-landmark-v4.2-personalized",
        "source": (
            "207 local webcam clips plus boundary idle segments and balanced "
            "ViSignLanguage common-20/OOV train-validation groups; no public test "
            "or frozen camera set used for training"
            if args.supplement_dataset is not None
            else "207 local webcam clips plus boundary idle segments; "
            "no frozen camera set used for training"
            if bool(is_negative.any())
            else "207 local webcam clips; no frozen camera set used for training"
        ),
        "feature_schema": (
            "hand-shape + shoulder-relative hand/pose + inter-hand geometry + masks"
        ),
        "train_samples": int(len(split.train)),
        "validation_samples": int(len(split.validation)),
        "negative_train_samples": int(is_negative[split.train].sum()),
        "negative_validation_samples": int(is_negative[split.validation].sum()),
        "public_supplement_train_samples": supplement_train_count,
        "public_supplement_validation_samples": supplement_validation_count,
        "occlusion_probability": args.occlusion_probability,
        "best_epoch": best_epoch,
        "validation_loss": validation_loss,
        "validation_accuracy": validation_metrics["accuracy"],
        "validation_macro_f1": validation_metrics["macro_f1"],
        "local_validation_accuracy": local_validation_metrics["accuracy"],
        "public_validation_accuracy": (
            public_validation_metrics["accuracy"]
            if public_validation_metrics is not None
            else None
        ),
        "mirrored_validation_loss": mirrored_loss,
        "mirrored_validation_accuracy": mirrored_metrics["accuracy"],
        "occluded_validation_loss": occluded_loss,
        "occluded_validation_accuracy": occluded_metrics["accuracy"],
        "per_class_accuracy": {
            label: float(validation_metrics["per_class_accuracy"][index])
            for index, label in enumerate(labels)
        },
        "confusion_matrix": validation_metrics["confusion_matrix"],
        "correct_confidence_median": float(correct_confidence.median().item())
        if len(correct_confidence)
        else 0.0,
        "correct_margin_median": float(correct_margin.median().item())
        if len(correct_margin)
        else 0.0,
        "onnx_export_max_difference": float(
            np.abs(onnx_logits - torch_logits).max()
        ),
        "onnx_cpu_median_ms": median_ms,
        "onnx_cpu_p95_ms": p95_ms,
        "history": history,
    }
    (args.output_dir / "labels.json").write_text(
        json.dumps(labels, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.web_model_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(onnx_path, args.web_model_dir / "vsign-landmark-v4.onnx")
    shutil.copy2(
        args.output_dir / "labels.json",
        args.web_model_dir / "vsign-landmark-v4.labels.json",
    )
    print(
        f"V4 tốt nhất epoch {best_epoch}: val={validation_metrics['accuracy']:.3f}, "
        f"mirror={mirrored_metrics['accuracy']:.3f}, "
        f"occluded={occluded_metrics['accuracy']:.3f}",
        flush=True,
    )
    print(f"ONNX CPU: median={median_ms:.3f}ms, p95={p95_ms:.3f}ms", flush=True)
    print(f"Đã xuất {onnx_path} và model web V4", flush=True)


if __name__ == "__main__":
    main()
