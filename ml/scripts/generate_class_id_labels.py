from __future__ import annotations

import argparse
import json
from pathlib import Path


def generate_labels(class_count: int) -> list[str]:
    if class_count <= 0:
        raise ValueError("class_count phải lớn hơn 0")
    width = max(4, len(str(class_count - 1)))
    return [f"Ký hiệu #{index:0{width}d}" for index in range(class_count)]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Tạo label kỹ thuật theo output index. File này không phải glossary tiếng Việt."
        )
    )
    parser.add_argument("output", type=Path)
    parser.add_argument("--class-count", type=int, default=1000)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    labels = generate_labels(args.class_count)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(labels, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Đã tạo {len(labels)} class ID kỹ thuật tại {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
