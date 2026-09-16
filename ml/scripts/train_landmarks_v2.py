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

from ml.landmarks_v2 import (
    COORDINATES_PER_LANDMARK,
    FEATURE_DIM,
    HAND_FEATURES,
    LANDMARKS_PER_HAND,
    MAX_HANDS,
    SEQUENCE_LENGTH,
    LandmarkKeyframeNet,
    LandmarkTCN,
    mirror_sequence,
    stratified_hand_split,
)


class LandmarkDataset(Dataset[tuple[torch.Tensor, torch.Tensor]]):
    def __init__(
        self,
        sequences: np.ndarray,
        labels: np.ndarray,
        indices: np.ndarray,
        *,
        augment: bool,
        include_mirror_copy: bool = False,
        occlusion_probability: float = 0.0,
    ) -> None:
        self.sequences = sequences
        self.labels = labels
        self.indices = indices
        self.augment = augment
        self.include_mirror_copy = include_mirror_copy
        self.occlusion_probability = occlusion_probability

    def __len__(self) -> int:
        return len(self.indices) * (2 if self.include_mirror_copy else 1)

    def _augment(self, sequence: np.ndarray, *, mirror: bool) -> np.ndarray:
        result = sequence.copy()
        if mirror:
            result = mirror_sequence(result)

        hands = result[:, : MAX_HANDS * HAND_FEATURES].reshape(
            SEQUENCE_LENGTH,
            MAX_HANDS,
            LANDMARKS_PER_HAND,
            COORDINATES_PER_LANDMARK,
        )
        presence = result[:, -MAX_HANDS:]
        scale = random.uniform(0.88, 1.12)
        translate_x = random.uniform(-0.06, 0.06)
        translate_y = random.uniform(-0.05, 0.05)
        valid = presence[:, :, None] > 0.5
        hands[..., 0] = np.where(
            valid,
            (hands[..., 0] - 0.5) * scale + 0.5 + translate_x,
            hands[..., 0],
        )
        hands[..., 1] = np.where(
            valid,
            (hands[..., 1] - 0.5) * scale + 0.5 + translate_y,
            hands[..., 1],
        )
        hands[..., 2] = np.where(valid, hands[..., 2] * scale, hands[..., 2])

        noise = np.random.normal(0.0, 0.004, size=hands.shape).astype(np.float32)
        hands += noise * valid[..., None]

        # A live capture rarely starts and ends at the exact same phase as the
        # saved clip. Randomly zoom into a valid temporal window so short signs
        # such as "Uống" remain recognizable even when the neutral frames vary.
        temporal_start = random.randint(0, 4)
        temporal_end = random.randint(11, SEQUENCE_LENGTH - 1)
        temporal_indices = np.rint(
            np.linspace(temporal_start, temporal_end, SEQUENCE_LENGTH)
        ).astype(np.int64)
        result = result[temporal_indices].copy()

        if random.random() < 0.25:
            frame = random.randrange(1, SEQUENCE_LENGTH - 1)
            result[frame] = (result[frame - 1] + result[frame + 1]) * 0.5
            result[frame, -MAX_HANDS:] = np.maximum(
                result[frame - 1, -MAX_HANDS:], result[frame + 1, -MAX_HANDS:]
            )
        if random.random() < self.occlusion_probability:
            hands = result[:, : MAX_HANDS * HAND_FEATURES].reshape(
                SEQUENCE_LENGTH,
                MAX_HANDS,
                HAND_FEATURES,
            )
            presence = result[:, -MAX_HANDS:]
            # Simulate one hand disappearing while crossing the other. Only
            # remove it where the other hand remains visible, so this is an
            # occlusion example rather than a completely empty clip.
            hand_index = random.randrange(MAX_HANDS)
            other_index = 1 - hand_index
            span_length = random.randint(2, 6)
            span_start = random.randint(1, SEQUENCE_LENGTH - span_length - 1)
            span_end = span_start + span_length
            occluded = (
                (presence[span_start:span_end, hand_index] > 0.5)
                & (presence[span_start:span_end, other_index] > 0.5)
            )
            hands[span_start:span_end, hand_index] = np.where(
                occluded[:, None], 0.0, hands[span_start:span_end, hand_index]
            )
            presence[span_start:span_end, hand_index] = np.where(
                occluded,
                0.0,
                presence[span_start:span_end, hand_index],
            )
        return result

    def __getitem__(self, item: int) -> tuple[torch.Tensor, torch.Tensor]:
        mirror = self.include_mirror_copy and item >= len(self.indices)
        index = int(self.indices[item % len(self.indices)])
        sequence = self.sequences[index]
        if self.augment:
            sequence = self._augment(sequence, mirror=mirror)
        return torch.from_numpy(sequence), torch.tensor(self.labels[index], dtype=torch.long)


def calculate_metrics(
    logits: torch.Tensor, targets: torch.Tensor, label_count: int
) -> dict[str, object]:
    predictions = logits.argmax(dim=1)
    confusion = torch.zeros((label_count, label_count), dtype=torch.int64)
    for target, predicted in zip(targets.tolist(), predictions.tolist()):
        confusion[target, predicted] += 1
    true_positive = confusion.diag().to(torch.float32)
    precision = true_positive / confusion.sum(dim=0).clamp(min=1)
    recall = true_positive / confusion.sum(dim=1).clamp(min=1)
    f1 = 2 * precision * recall / (precision + recall).clamp(min=1e-9)
    return {
        "accuracy": float((predictions == targets).to(torch.float32).mean().item()),
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
    loss = sum(losses) / len(all_targets)
    return loss, calculate_metrics(all_logits, all_targets, label_count), all_logits, all_targets


def benchmark_onnx(model_path: Path, sample: np.ndarray) -> tuple[float, float]:
    session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    for _ in range(10):
        session.run(None, {input_name: sample})
    timings = []
    for _ in range(100):
        started = time.perf_counter()
        session.run(None, {input_name: sample})
        timings.append((time.perf_counter() - started) * 1_000)
    return float(np.median(timings)), float(np.percentile(timings, 95))


def select_supplement_train_indices(
    data: np.lib.npyio.NpzFile,
    focus_labels: list[str],
    label_names: list[str],
    *,
    max_groups_per_label: int,
    minimum_detected_frames: int,
    seed: int,
) -> np.ndarray:
    splits = data["splits"]
    group_ids = data["group_ids"]
    targets = data["labels"].astype(np.int64)
    detected = data["detected_frames"].astype(np.int64)
    rng = np.random.default_rng(seed)
    selected: list[int] = []
    for label in focus_labels:
        if label not in label_names:
            raise ValueError(f"Nhãn supplement không hợp lệ: {label}")
        label_index = label_names.index(label)
        candidates = np.flatnonzero(
            (splits == "train")
            & (targets == label_index)
            & (detected >= minimum_detected_frames)
        )
        # Filename variants share a group_id. Keep the best detected clip per
        # group so repeated copies cannot dominate the personalized samples.
        best_by_group: dict[str, int] = {}
        for index in candidates.tolist():
            group = str(group_ids[index])
            current = best_by_group.get(group)
            if current is None or detected[index] > detected[current]:
                best_by_group[group] = index
        group_samples = np.asarray(list(best_by_group.values()), dtype=np.int64)
        rng.shuffle(group_samples)
        selected.extend(group_samples[:max_groups_per_label].tolist())
    return np.asarray(selected, dtype=np.int64)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train model landmark TCN VSign v2")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("ml/data/processed/landmarks_v2/collected_common20.npz"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("ml/artifacts/landmark_v2"),
    )
    parser.add_argument(
        "--web-model-dir", type=Path, default=Path("apps/web/public/models")
    )
    parser.add_argument("--web-model-name")
    parser.add_argument("--epochs", type=int, default=300)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--learning-rate", type=float, default=2e-3)
    parser.add_argument("--seed", type=int, default=20260911)
    parser.add_argument("--patience", type=int, default=60)
    parser.add_argument("--device", choices=("cpu", "mps"), default="cpu")
    parser.add_argument(
        "--architecture",
        choices=("tcn-v2", "keyframe-v3"),
        default="tcn-v2",
    )
    parser.add_argument("--supplement-dataset", type=Path)
    parser.add_argument(
        "--supplement-labels", nargs="+", default=["Trường học", "Chào"]
    )
    parser.add_argument("--supplement-max-groups-per-label", type=int, default=16)
    parser.add_argument("--supplement-min-detected-frames", type=int, default=4)
    parser.add_argument(
        "--occlusion-probability",
        type=float,
        default=0.0,
        help="Xác suất mô phỏng một tay bị tay kia che tạm thời (0..1)",
    )
    args = parser.parse_args()
    if not 0.0 <= args.occlusion_probability <= 1.0:
        raise ValueError("--occlusion-probability phải nằm trong khoảng 0..1")

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.set_num_threads(min(4, max(1, torch.get_num_threads())))

    data = np.load(args.dataset)
    sequences = data["sequences"].astype(np.float32)
    targets = data["labels"].astype(np.int64)
    hands = data["hands"].tolist()
    labels = data["label_names"].tolist()
    if sequences.shape[1:] != (SEQUENCE_LENGTH, FEATURE_DIM):
        raise ValueError(f"Dataset có shape không hợp lệ: {sequences.shape}")
    split = stratified_hand_split(targets, hands, seed=args.seed)

    training_sequences = sequences
    training_targets = targets
    training_indices = split.train
    supplement_validation_loader = None
    supplement_test_loader = None
    supplement_train_count = 0
    supplement_validation_count = 0
    supplement_test_count = 0
    if args.supplement_dataset:
        supplement = np.load(args.supplement_dataset)
        supplement_sequences = supplement["sequences"].astype(np.float32)
        supplement_targets = supplement["labels"].astype(np.int64)
        supplement_labels = supplement["label_names"].tolist()
        if supplement_labels != labels:
            raise ValueError("Label map của supplement không khớp dataset webcam")
        if supplement_sequences.shape[1:] != (SEQUENCE_LENGTH, FEATURE_DIM):
            raise ValueError(
                f"Supplement có shape không hợp lệ: {supplement_sequences.shape}"
            )
        supplement_train = select_supplement_train_indices(
            supplement,
            args.supplement_labels,
            labels,
            max_groups_per_label=args.supplement_max_groups_per_label,
            minimum_detected_frames=args.supplement_min_detected_frames,
            seed=args.seed,
        )
        offset = len(sequences)
        training_sequences = np.concatenate((sequences, supplement_sequences))
        training_targets = np.concatenate((targets, supplement_targets))
        training_indices = np.concatenate((split.train, supplement_train + offset))
        supplement_train_count = int(len(supplement_train))

        detected = supplement["detected_frames"].astype(np.int64)
        for split_name in ("validation", "test"):
            indices = np.flatnonzero(
                (supplement["splits"] == split_name)
                & (detected >= args.supplement_min_detected_frames)
            )
            dataset = LandmarkDataset(
                supplement_sequences,
                supplement_targets,
                indices,
                augment=False,
            )
            loader = DataLoader(dataset, batch_size=args.batch_size, shuffle=False)
            if split_name == "validation":
                supplement_validation_loader = loader
                supplement_validation_count = int(len(indices))
            else:
                supplement_test_loader = loader
                supplement_test_count = int(len(indices))

    train_dataset = LandmarkDataset(
        training_sequences,
        training_targets,
        training_indices,
        augment=True,
        include_mirror_copy=True,
        occlusion_probability=args.occlusion_probability,
    )
    validation_dataset = LandmarkDataset(
        sequences, targets, split.validation, augment=False
    )
    mirrored_validation_dataset = LandmarkDataset(
        mirror_sequence(sequences), targets, split.validation, augment=False
    )
    generator = torch.Generator().manual_seed(args.seed)
    train_loader = DataLoader(
        train_dataset,
        batch_size=args.batch_size,
        shuffle=True,
        generator=generator,
    )
    validation_loader = DataLoader(
        validation_dataset, batch_size=args.batch_size, shuffle=False
    )
    mirrored_validation_loader = DataLoader(
        mirrored_validation_dataset, batch_size=args.batch_size, shuffle=False
    )

    if args.device == "mps" and not torch.backends.mps.is_available():
        raise RuntimeError("PyTorch hiện tại không hỗ trợ MPS trên máy này")
    device = torch.device(args.device)
    model_version = (
        "landmark-keyframe-v3-personalized"
        if args.architecture == "keyframe-v3"
        else "landmark-tcn-v2-personalized"
    )
    model_class = (
        LandmarkKeyframeNet if args.architecture == "keyframe-v3" else LandmarkTCN
    )
    model = model_class(len(labels)).to(device)
    class_counts = np.bincount(targets[split.train], minlength=len(labels))
    class_weights = np.sqrt(class_counts.max() / np.maximum(class_counts, 1))
    criterion = nn.CrossEntropyLoss(
        weight=torch.tensor(class_weights, dtype=torch.float32, device=device),
        label_smoothing=0.06,
    )
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=args.learning_rate, weight_decay=2e-3
    )
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="min", factor=0.5, patience=15, min_lr=2e-5
    )

    best_loss = float("inf")
    best_state: dict[str, torch.Tensor] | None = None
    best_epoch = 0
    stale_epochs = 0
    history: list[dict[str, float]] = []
    for epoch in range(1, args.epochs + 1):
        model.train()
        train_loss = 0.0
        seen = 0
        for inputs, target in train_loader:
            inputs = inputs.to(device)
            target = target.to(device)
            optimizer.zero_grad(set_to_none=True)
            output = model(inputs)
            loss = criterion(output, target)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), max_norm=3.0)
            optimizer.step()
            train_loss += float(loss.item()) * len(target)
            seen += len(target)
        validation_loss, validation_metrics, _, _ = evaluate(
            model, validation_loader, device, len(labels)
        )
        mirrored_loss, mirrored_metrics, _, _ = evaluate(
            model, mirrored_validation_loader, device, len(labels)
        )
        supplement_validation_loss = None
        supplement_validation_metrics = None
        if supplement_validation_loader is not None:
            (
                supplement_validation_loss,
                supplement_validation_metrics,
                _,
                _,
            ) = evaluate(
                model, supplement_validation_loader, device, len(labels)
            )
        robust_loss = (
            validation_loss * 0.4
            + mirrored_loss * 0.3
            + (
                supplement_validation_loss * 0.3
                if supplement_validation_loss is not None
                else validation_loss * 0.3
            )
        )
        scheduler.step(robust_loss)
        row = {
            "epoch": float(epoch),
            "train_loss": train_loss / seen,
            "validation_loss": validation_loss,
            "validation_accuracy": float(validation_metrics["accuracy"]),
            "validation_macro_f1": float(validation_metrics["macro_f1"]),
            "mirrored_validation_loss": mirrored_loss,
            "mirrored_validation_accuracy": float(mirrored_metrics["accuracy"]),
        }
        if supplement_validation_metrics is not None:
            row["supplement_validation_loss"] = float(
                supplement_validation_loss
            )
            row["supplement_validation_accuracy"] = float(
                supplement_validation_metrics["accuracy"]
            )
        history.append(row)
        if robust_loss < best_loss - 1e-4:
            best_loss = robust_loss
            best_epoch = epoch
            stale_epochs = 0
            best_state = {
                key: value.detach().cpu().clone()
                for key, value in model.state_dict().items()
            }
        else:
            stale_epochs += 1
        if epoch == 1 or epoch % 10 == 0:
            print(
                f"Epoch {epoch:03d}: train={row['train_loss']:.4f} "
                f"val={validation_loss:.4f} acc={validation_metrics['accuracy']:.3f} "
                f"mirror_acc={mirrored_metrics['accuracy']:.3f}"
                + (
                    ""
                    if supplement_validation_metrics is None
                    else f" supplement_acc={supplement_validation_metrics['accuracy']:.3f}"
                ),
                flush=True,
            )
        if stale_epochs >= args.patience:
            print(f"Dừng sớm ở epoch {epoch}")
            break

    if best_state is None:
        raise RuntimeError("Không tạo được checkpoint")
    model.load_state_dict(best_state)
    model.to("cpu").eval()
    validation_loss, validation_metrics, validation_logits, validation_targets = evaluate(
        model, validation_loader, torch.device("cpu"), len(labels)
    )
    mirrored_validation_loss, mirrored_validation_metrics, _, _ = evaluate(
        model,
        mirrored_validation_loader,
        torch.device("cpu"),
        len(labels),
    )
    supplement_validation_metrics = None
    supplement_test_metrics = None
    if supplement_validation_loader is not None:
        _, supplement_validation_metrics, _, _ = evaluate(
            model,
            supplement_validation_loader,
            torch.device("cpu"),
            len(labels),
        )
    if supplement_test_loader is not None:
        _, supplement_test_metrics, _, _ = evaluate(
            model,
            supplement_test_loader,
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
            "architecture": args.architecture,
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

    onnx_session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    onnx_logits = onnx_session.run(None, {"landmarks": example})[0]
    with torch.no_grad():
        torch_logits = model(torch.from_numpy(example)).numpy()
    max_export_difference = float(np.abs(onnx_logits - torch_logits).max())
    median_ms, p95_ms = benchmark_onnx(onnx_path, example)

    per_class = {
        label: float(validation_metrics["per_class_accuracy"][index])
        for index, label in enumerate(labels)
    }
    probabilities = torch.softmax(validation_logits, dim=1)
    top_two = probabilities.topk(2, dim=1).values
    correct = validation_logits.argmax(dim=1) == validation_targets
    correct_confidence = probabilities.max(dim=1).values[correct]
    correct_margin = (top_two[:, 0] - top_two[:, 1])[correct]
    metrics = {
        "model_version": model_version,
        "source": (
            "207 webcam clips plus focused public supplement"
            if args.supplement_dataset
            else "207 webcam clips collected locally"
        ),
        "train_samples": int(len(training_indices)),
        "validation_samples": int(len(split.validation)),
        "supplement_train_samples": supplement_train_count,
        "supplement_validation_samples": supplement_validation_count,
        "supplement_test_samples": supplement_test_count,
        "supplement_validation_accuracy": (
            supplement_validation_metrics["accuracy"]
            if supplement_validation_metrics is not None
            else None
        ),
        "supplement_test_accuracy": (
            supplement_test_metrics["accuracy"]
            if supplement_test_metrics is not None
            else None
        ),
        "occlusion_probability": args.occlusion_probability,
        "best_epoch": best_epoch,
        "validation_loss": validation_loss,
        "validation_accuracy": validation_metrics["accuracy"],
        "validation_macro_f1": validation_metrics["macro_f1"],
        "mirrored_validation_loss": mirrored_validation_loss,
        "mirrored_validation_accuracy": mirrored_validation_metrics["accuracy"],
        "mirrored_validation_macro_f1": mirrored_validation_metrics["macro_f1"],
        "per_class_accuracy": per_class,
        "confusion_matrix": validation_metrics["confusion_matrix"],
        "correct_confidence_median": float(correct_confidence.median().item())
        if len(correct_confidence)
        else 0.0,
        "correct_margin_median": float(correct_margin.median().item())
        if len(correct_margin)
        else 0.0,
        "onnx_export_max_difference": max_export_difference,
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
    web_model_name = args.web_model_name or (
        "vsign-landmark-keyframe-v3.onnx"
        if args.architecture == "keyframe-v3"
        else "vsign-landmark-v2.onnx"
    )
    shutil.copy2(onnx_path, args.web_model_dir / web_model_name)
    shutil.copy2(args.output_dir / "labels.json", args.web_model_dir / "vsign-landmark-v2.labels.json")
    print(
        f"Tốt nhất epoch {best_epoch}: accuracy={validation_metrics['accuracy']:.3f}, "
        f"macro-F1={validation_metrics['macro_f1']:.3f}, "
        f"mirror-accuracy={mirrored_validation_metrics['accuracy']:.3f}"
    )
    print(f"ONNX CPU: median={median_ms:.3f}ms, p95={p95_ms:.3f}ms")
    print(
        f"Đã xuất {onnx_path} và copy model vào "
        f"{args.web_model_dir / web_model_name}"
    )


if __name__ == "__main__":
    main()
