"""Diagnose selected recorded errors through the unchanged browser encoder."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

from ml.scripts.audit_sales30_errors import PRIORITY, write_json
from ml.scripts.evaluate_personal_runtime import file_hash, get_metadata
from ml.scripts.smoke_personal_runtime import validate_reply


def select_probe(samples: list[dict], words: list[str]) -> list[dict]:
    selected = []
    for word in words:
        errors = [row for row in samples if row["source"] == "seated" and row["expected_label"] == word
                  and (row["reply"]["status"] != "ok" or row["reply"]["label"] != word)]
        if not errors:
            raise ValueError(f"Missing recorded seated error: {word}")
        selected.append(max(errors, key=lambda row: (row["diagnostic"]["raw_confidence"], row["path"])))
    return selected


def main(argv=None) -> int:
    from ml.personal_finetune import decode_uniform_frames
    from app.backends.coreml_artifact import package_hash

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, default=Path("docs/reports/2026-10-10-word-accuracy-coreml/predictions.jsonl"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frontend", default="http://127.0.0.1:5173")
    parser.add_argument("--backend", default="http://127.0.0.1:8000")
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("Use a fresh output path")
    root = Path(__file__).resolve().parents[2]
    metadata = get_metadata(args.backend)
    if metadata["backend"] != "coreml" or metadata["mock"] or (metadata["confidence_threshold"], metadata["margin_threshold"]) != (.7, .15):
        raise ValueError("Unexpected active runtime")
    samples = [json.loads(line) for line in args.predictions.read_text().splitlines() if line.strip()]
    selected = select_probe(samples, PRIORITY)
    if any(row["reply"]["model_version"] != metadata["model_version"] for row in selected):
        raise ValueError("Stored evaluation and active model differ")
    package = root / "ml/artifacts/sales30_personal_coreml_fp32_r4/model.mlpackage"
    protected = [root / "ml/artifacts/sales30_personal_v1/best.pt",
                 root / "ml/artifacts/sales30_personal_v1/labels.json", args.predictions]
    before = {str(path): file_hash(path) for path in protected}
    package_before = package_hash(package)
    with tempfile.TemporaryDirectory(prefix="vsign-frontend-probe-") as temporary:
        inputs = []
        for sample_index, sample in enumerate(selected):
            video = (root / sample["path"]).resolve()
            if not video.is_relative_to(root) or file_hash(video) != sample["sha256"]:
                raise ValueError("Selected probe checksum mismatch")
            images = decode_uniform_frames(video)
            paths = []
            try:
                for index, image in enumerate(images):
                    path = Path(temporary) / f"{sample_index}-{index}.png"
                    image.save(path)
                    paths.append(str(path))
            finally:
                for image in images:
                    image.close()
            inputs.append({"path": sample["path"], "expected_label": sample["expected_label"],
                           "sha256": sample["sha256"], "png_frames": paths, "original_reply": sample["reply"]})
        input_path = Path(temporary) / "inputs.json"
        write_json(input_path, {"frontend": args.frontend, "backend": args.backend, "samples": inputs})
        node_output = Path(temporary) / "result.json"
        subprocess.run([os.environ.get("VSIGN_NODE", "node"), str(root / "tests/e2e/recognition_input_probe.mjs"),
                        str(input_path), str(node_output)], check=True, cwd=root, timeout=300)
        report = json.loads(node_output.read_text())
    for result in report["samples"]:
        for variant in result["variants"]:
            validate_reply(variant["reply"], variant["sequence"], metadata["model_version"], metadata["labels"])
    if (get_metadata(args.backend) != metadata or package_hash(package) != package_before
            or any(file_hash(Path(path)) != digest for path, digest in before.items())):
        raise RuntimeError("Runtime or protected inputs changed during probe")
    report.update(metadata=metadata, protected_inputs_unchanged=True, coreml_package_sha256=package_before,
                  protected_sha256=before, limits="Purposively selected recorded clips, uniform16. Actual browser worker/main encoder, not live segmentation or camera accuracy.")
    write_json(args.output, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
