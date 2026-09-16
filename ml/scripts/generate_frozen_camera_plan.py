from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path


DISTANCES = ("near", "standard", "far")
LIGHTING = ("normal", "low", "side")
HANDS = ("right", "left")
NEGATIVE_ACTIONS = (
    "still",
    "hand_enter_exit",
    "adjust_hair_glasses",
    "touch_face",
    "turn_body",
    "random_motion",
    "overlap_hands",
    "other_sign",
)


def build_plan(labels: list[str], negative_count: int, seed: int) -> list[dict[str, str]]:
    positive_labels = [label for label in labels if label != "Không ký hiệu"]
    rows: list[dict[str, str]] = []
    for label_index, label in enumerate(positive_labels):
        for distance_index, distance in enumerate(DISTANCES):
            rows.append(
                {
                    "kind": "positive",
                    "expected_label": label,
                    "hand": HANDS[(label_index + distance_index) % len(HANDS)],
                    "distance": distance,
                    "lighting": LIGHTING[(label_index + distance_index) % len(LIGHTING)],
                    "negative_action": "",
                }
            )
    for index in range(negative_count):
        rows.append(
            {
                "kind": "negative",
                "expected_label": "Không ký hiệu",
                "hand": HANDS[index % len(HANDS)],
                "distance": DISTANCES[index % len(DISTANCES)],
                "lighting": LIGHTING[(index // len(DISTANCES)) % len(LIGHTING)],
                "negative_action": NEGATIVE_ACTIONS[index % len(NEGATIVE_ACTIONS)],
            }
        )
    random.Random(seed).shuffle(rows)
    for index, row in enumerate(rows, start=1):
        row["order"] = str(index)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tạo lịch thu 60 positive + 30 negative camera V4"
    )
    parser.add_argument(
        "--labels",
        type=Path,
        default=Path("ml/artifacts/landmark_v4/labels.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("ml/data/evaluation/frozen_camera_v4/capture_plan.csv"),
    )
    parser.add_argument("--negative-count", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20260911)
    args = parser.parse_args()
    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    if not isinstance(labels, list) or not all(isinstance(item, str) for item in labels):
        raise ValueError("labels.json phải là mảng chuỗi")
    rows = build_plan(labels, args.negative_count, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "order",
                "kind",
                "expected_label",
                "hand",
                "distance",
                "lighting",
                "negative_action",
            ),
        )
        writer.writeheader()
        writer.writerows(rows)
    positives = sum(row["kind"] == "positive" for row in rows)
    negatives = len(rows) - positives
    print(f"Đã tạo {len(rows)} lượt: {positives} positive + {negatives} negative")
    print(f"Lịch thu: {args.output}")


if __name__ == "__main__":
    main()
