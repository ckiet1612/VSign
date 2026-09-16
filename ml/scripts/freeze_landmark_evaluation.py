from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Đóng băng dataset camera V4 trước khi đánh giá"
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(
            f"Manifest đã tồn tại: {args.output}. Không ghi đè bộ test đóng băng."
        )
    data = np.load(args.dataset)
    manifest = {
        "schema_version": "1.0",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(args.dataset),
        "dataset_sha256": sha256(args.dataset),
        "sample_count": int(len(data["sequences"])),
        "labels": data["label_names"].tolist(),
        "policy": "Không dùng dataset này để train, early-stop hoặc chọn threshold.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Đã đóng băng {manifest['sample_count']} mẫu: {args.output}")
    print(f"SHA-256: {manifest['dataset_sha256']}")


if __name__ == "__main__":
    main()
