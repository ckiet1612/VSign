from __future__ import annotations

import argparse
import csv
import itertools
import random
from pathlib import Path


FOCUS_COUNTS = {
    "Uống": 18,
    "Ăn": 12,
    "Trường học": 12,
    "Nói": 12,
    "Đâu": 6,
}
HANDS = ("right", "left")
DISTANCES = ("near", "standard", "far")
LIGHTING = ("normal", "low", "side")
EXECUTIONS = ("natural", "slightly_slow", "slightly_fast")
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


def build_plan(seed: int = 20260912) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    combinations = list(itertools.product(HANDS, DISTANCES, LIGHTING))
    for label_index, (label, count) in enumerate(FOCUS_COUNTS.items()):
        rotated = combinations[label_index:] + combinations[:label_index]
        for index in range(count):
            hand, distance, lighting = rotated[index % len(rotated)]
            rows.append(
                {
                    "kind": "positive",
                    "expected_label": label,
                    "hand": hand,
                    "distance": distance,
                    "lighting": lighting,
                    "negative_action": "",
                    "execution": EXECUTIONS[index % len(EXECUTIONS)],
                }
            )
    for index in range(24):
        rows.append(
            {
                "kind": "negative",
                "expected_label": "Không ký hiệu",
                "hand": HANDS[index % len(HANDS)],
                "distance": DISTANCES[index % len(DISTANCES)],
                "lighting": LIGHTING[(index // len(DISTANCES)) % len(LIGHTING)],
                "negative_action": NEGATIVE_ACTIONS[index % len(NEGATIVE_ACTIONS)],
                "execution": "natural",
            }
        )
    random.Random(seed).shuffle(rows)
    for index, row in enumerate(rows, start=1):
        row["order"] = str(index)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tạo lịch development V5 cho cụm Uống–Ăn–Trường học và Nói"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("ml/data/development/v5/capture_plan.csv"),
    )
    parser.add_argument("--seed", type=int, default=20260912)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.output.exists() and not args.force:
        raise FileExistsError(f"Lịch development đã tồn tại: {args.output}")
    rows = build_plan(args.seed)
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
                "execution",
            ),
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"Đã tạo {len(rows)} lượt development V5 tại {args.output}")


if __name__ == "__main__":
    main()
