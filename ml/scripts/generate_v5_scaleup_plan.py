from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

import numpy as np


HANDS = ("right", "left")
DISTANCES = ("standard", "near", "far", "standard")
LIGHTING = ("normal", "normal", "side", "low")
EXECUTIONS = (
    "natural",
    "natural",
    "slightly_slow",
    "natural",
    "slightly_fast",
)


def load_public_counts(path: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            # Public test remains frozen and never contributes to a train quota.
            if row["split"] != "test":
                counts[row["label"]] += 1
    return counts


def load_quality_checked_public_counts(
    path: Path, *, min_detected_hand_frames: int
) -> Counter[str]:
    dataset = np.load(path, allow_pickle=False)
    required = {
        "labels",
        "label_names",
        "splits",
        "detected_hand_frames",
    }
    missing = required - set(dataset.files)
    if missing:
        raise ValueError(f"Dataset public V5 thiếu trường: {sorted(missing)}")
    split_names = dataset["splits"].astype(str)
    invalid = sorted(set(split_names.tolist()) - {"train", "validation"})
    if invalid:
        raise ValueError(f"Dataset public V5 chứa split cấm: {invalid}")
    labels = [str(value) for value in dataset["label_names"].tolist()]
    targets = dataset["labels"].astype(np.int64)
    detected = dataset["detected_hand_frames"].astype(np.int64)
    if not len(targets) == len(detected) == len(split_names):
        raise ValueError("Dataset public V5 lệch số mẫu")
    return Counter(
        labels[int(target)]
        for target, hand_frames in zip(targets, detected)
        if hand_frames >= min_detected_hand_frames
    )


def load_local_counts(root: Path) -> dict[str, Counter[str]]:
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for path in root.rglob("*.json"):
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        label = metadata.get("expected_label")
        hand = metadata.get("hand")
        if isinstance(label, str) and hand in HANDS:
            counts[label][str(hand)] += 1
    return counts


def build_targets(
    labels: Iterable[str],
    public_counts: Counter[str],
    *,
    target_per_label: int,
) -> dict[str, dict[str, int]]:
    targets: dict[str, dict[str, int]] = {}
    for label in labels:
        local_goal = max(0, target_per_label - public_counts[label])
        targets[label] = {
            "right": math.ceil(local_goal / 2),
            "left": local_goal // 2,
        }
    return targets


def build_rows(
    labels: Iterable[str],
    targets: dict[str, dict[str, int]],
    local_counts: dict[str, Counter[str]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for label_index, label in enumerate(labels):
        for hand_index, hand in enumerate(HANDS):
            missing = max(0, targets[label][hand] - local_counts[label][hand])
            for sample_index in range(missing):
                variant = sample_index + label_index * 3 + hand_index
                rows.append(
                    {
                        "order": str(len(rows) + 1),
                        "expected_label": label,
                        "hand": hand,
                        "distance": DISTANCES[variant % len(DISTANCES)],
                        "lighting": LIGHTING[(variant // 2) % len(LIGHTING)],
                        "execution": EXECUTIONS[variant % len(EXECUTIONS)],
                    }
                )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Tạo lịch clip còn thiếu để mỗi từ có 100 video train/validation thật"
        )
    )
    parser.add_argument(
        "--public-manifest",
        type=Path,
        default=Path("ml/data/raw/visignlanguage-video/common20_manifest.csv"),
    )
    parser.add_argument(
        "--public-v5-dataset",
        type=Path,
        default=Path("ml/data/processed/landmarks_v5/public_trainval.npz"),
        help=(
            "Nếu tồn tại, tính quota từ các clip public train/validation đã "
            "qua kiểm tra landmark thay vì chỉ đếm manifest"
        ),
    )
    parser.add_argument(
        "--labels",
        type=Path,
        default=Path("ml/data/raw/visignlanguage-video/common20_label_map.json"),
    )
    parser.add_argument(
        "--local-root", type=Path, default=Path("ml/data/collected/webcam")
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("ml/data/development/v5/capture_plan_100_each.csv"),
    )
    parser.add_argument(
        "--web-targets",
        type=Path,
        default=Path("apps/web/src/v5CollectionTargets.json"),
    )
    parser.add_argument("--target-per-label", type=int, default=100)
    parser.add_argument("--min-detected-hand-frames", type=int, default=1)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.target_per_label <= 0:
        raise ValueError("--target-per-label phải lớn hơn 0")
    if args.min_detected_hand_frames < 0:
        raise ValueError("--min-detected-hand-frames không được âm")
    for output in (args.output, args.web_targets):
        if output.exists() and not args.force:
            raise FileExistsError(f"File đã tồn tại: {output}")

    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    if not isinstance(labels, list) or not all(isinstance(item, str) for item in labels):
        raise ValueError("Label map phải là mảng chuỗi")
    if args.public_v5_dataset.exists():
        public_counts = load_quality_checked_public_counts(
            args.public_v5_dataset,
            min_detected_hand_frames=args.min_detected_hand_frames,
        )
    else:
        public_counts = load_public_counts(args.public_manifest)
    local_counts = load_local_counts(args.local_root)
    targets = build_targets(
        labels, public_counts, target_per_label=args.target_per_label
    )
    rows = build_rows(labels, targets, local_counts)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "order",
                "expected_label",
                "hand",
                "distance",
                "lighting",
                "execution",
            ),
        )
        writer.writeheader()
        writer.writerows(rows)
    args.web_targets.parent.mkdir(parents=True, exist_ok=True)
    args.web_targets.write_text(
        json.dumps(
            {
                "targetPerLabel": args.target_per_label,
                "excludedPublicSplits": ["test"],
                "minimumDetectedHandFrames": args.min_detected_hand_frames,
                "targets": targets,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"Đã tạo {len(rows)} lượt còn thiếu để đủ "
        f"{args.target_per_label} video/từ (không tính public test)."
    )


if __name__ == "__main__":
    main()
