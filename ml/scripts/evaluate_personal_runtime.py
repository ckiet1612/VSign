"""Replay unchanged held-out clips against the current personal-model runtime."""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen
from uuid import uuid4

import numpy as np

from ml.scripts.smoke_personal_runtime import IDLE_LABEL, encode_frames, validate_metadata, validate_reply


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def select_held_out(rows: list[dict], labels: list[str], root: Path) -> list[dict]:
    hashes, groups = {}, {}
    for row in rows:
        split = row["split"]
        index = int(row["label_id"])
        if split not in {"train", "validation", "test"} or not 0 <= index < len(labels) or labels[index] != row["label"]:
            raise ValueError("Invalid manifest split or label")
        for identity, registry in ((row["sha256"], hashes), (row["group_id"], groups)):
            if not identity or identity in registry and registry[identity] != split:
                raise ValueError("Manifest leak across splits")
            registry[identity] = split
    selected = [row for row in rows if row["split"] in {"test", "validation"}]
    if not selected or len({row["path"] for row in selected}) != len(selected):
        raise ValueError("Empty or duplicate held-out paths")
    for row in selected:
        path = (root / row["path"]).resolve()
        if not path.is_relative_to(root.resolve()) or file_hash(path) != row["sha256"]:
            raise ValueError(f"Held-out checksum mismatch: {row['path']}")
    return sorted(selected, key=lambda row: (row["split"] != "test", row["source"], int(row["label_id"]), row["path"]))


def diagnose_probabilities(probabilities, labels, confidence_threshold, margin_threshold) -> dict:
    probabilities = np.asarray(probabilities, dtype=np.float32)
    if (probabilities.shape != (len(labels),) or not np.isfinite(probabilities).all()
            or (probabilities < 0).any() or not np.isclose(probabilities.sum(), 1., atol=1e-5)):
        raise ValueError("Invalid probabilities")
    indices = np.argsort(probabilities)[::-1]
    winner, second = int(indices[0]), int(indices[1])
    confidence = float(probabilities[winner])
    margin = float(probabilities[winner] - probabilities[second])
    reasons = []
    if labels[winner] == IDLE_LABEL:
        reasons.append("idle_winner")
    if confidence < confidence_threshold:
        reasons.append("low_confidence")
    if margin < margin_threshold:
        reasons.append("low_margin")
    return {"raw_top1": labels[winner], "raw_confidence": confidence, "raw_margin": margin,
            "rejection_reasons": reasons,
            "probabilities": {label: float(probabilities[index]) for index, label in enumerate(labels)}}


def summarize(samples: list[dict], labels: list[str]) -> dict:
    for sample in samples:
        if sample["expected_label"] not in labels or sample["reply"]["status"] not in {"ok", "uncertain"}:
            raise ValueError("Invalid evaluation label or status")

    def counts(rows):
        total = len(rows)
        correct = sum(row["reply"]["status"] == "ok" and row["reply"]["label"] == row["expected_label"] for row in rows)
        uncertain = sum(row["reply"]["status"] == "uncertain" for row in rows)
        wrong = total - correct - uncertain
        raw_correct = sum(row["diagnostic"]["raw_top1"] == row["expected_label"] for row in rows)
        pct = lambda value: round(value * 100 / total, 4) if total else None
        dominant = ("no_samples" if not total else "none" if not wrong and not uncertain else
                    "wrong" if wrong > uncertain else "uncertain" if uncertain > wrong else "mixed")
        return {"samples": total, "correct": correct, "wrong": wrong, "uncertain": uncertain,
                "correct_pct": pct(correct), "wrong_pct": pct(wrong), "uncertain_pct": pct(uncertain),
                "raw_top1_correct": raw_correct, "raw_top1_correct_pct": pct(raw_correct), "dominant_error": dominant,
                "wrong_labels": dict(Counter(row["reply"]["label"] for row in rows
                    if row["reply"]["status"] == "ok" and row["reply"]["label"] != row["expected_label"]).most_common()),
                "uncertain_top1": dict(Counter(row["diagnostic"]["raw_top1"] for row in rows
                    if row["reply"]["status"] == "uncertain").most_common()),
                "uncertain_reasons": dict(Counter(reason for row in rows if row["reply"]["status"] == "uncertain"
                    for reason in row["diagnostic"]["rejection_reasons"]).most_common())}

    positives = [sample for sample in samples if sample["expected_label"] != IDLE_LABEL]
    return {"overall": counts(positives), "per_word": [
        {"label": label, **counts([sample for sample in positives if sample["expected_label"] == label])}
        for label in labels if label != IDLE_LABEL]}


def framed_encoder(observations: dict):
    """Encode clips the way a trim-bodycrop-v1 client sends them, JPEG 90 like encode_frames."""
    import base64
    import io

    from ml.body_framing import frame_clip
    from ml.visignlanguage import decode_video

    def encode(path: Path, relative: str) -> list[str]:
        images = decode_video(path)
        try:
            framed = frame_clip(images, observations[relative])
        finally:
            for image in images:
                image.close()
        encoded = []
        for image in framed:
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=90)
            encoded.append("data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"))
            image.close()
        return encoded
    return encode


def get_metadata(url):
    with urlopen(url + "/metadata", timeout=10) as response:
        return json.load(response)


def diagnostic_replay(backend, encoded_frames, reply, expected):
    from app.validation import close_frames, decode_frames
    from ml.scripts.benchmark_personal_cpu import prediction_delta

    frames = decode_frames(encoded_frames, 256 * 1024)
    try:
        logits = np.asarray(backend._model.predict({"frames": backend._preprocess(frames)})["logits"], dtype=np.float32)
        prediction = asdict(backend._postprocess(logits))
        delta = prediction_delta(reply, prediction)
        exponentials = np.exp(logits[0] - np.max(logits[0]))
        diagnostic = diagnose_probabilities(exponentials / exponentials.sum(), backend.labels,
                                            backend.confidence_threshold, backend.margin_threshold)
        diagnostic.update(origin="same_encoded_frames_local_coreml", live_probability_delta=delta,
                          expected_probability=diagnostic["probabilities"][expected])
        return diagnostic
    finally:
        close_frames(frames)


async def replay(url, metadata, selected, root, output, backend, encoder=None):
    import websockets

    session = str(uuid4())
    ws_url = url.replace("http://", "ws://", 1).replace("https://", "wss://", 1) + "/ws/inference"
    samples = []
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=1) as pool, (output / "predictions.jsonl").open("x", encoding="utf-8") as log:
        async with websockets.connect(ws_url, max_size=6 * 1024 * 1024, ping_timeout=120) as socket:
            for sequence, row in enumerate(selected):
                frames = (encoder(root / row["path"], row["path"]) if encoder
                          else encode_frames(root / row["path"]))
                request = {"type": "frames", "session_id": session, "sequence": sequence,
                           "captured_at": int(time.time() * 1000), "frames": frames}
                sent = time.monotonic()
                await socket.send(json.dumps(request))
                reply = json.loads(await asyncio.wait_for(socket.recv(), timeout=60))
                response_seconds = time.monotonic() - sent
                validate_reply(reply, sequence, metadata["model_version"], metadata["labels"])
                if reply["status"] == "uncertain":
                    diagnostic = await asyncio.wrap_future(pool.submit(diagnostic_replay, backend, frames, reply, row["label"]))
                else:
                    diagnostic = {"raw_top1": reply["label"], "raw_confidence": reply["confidence"],
                                  "rejection_reasons": [], "origin": "live_accepted_reply",
                                  "expected_probability": next((item["confidence"] for item in reply["top_k"]
                                      if item["label"] == row["label"]), None)}
                sample = {**row, "expected_label": row["label"], "sequence": sequence,
                          "response_seconds": response_seconds, "reply": reply, "diagnostic": diagnostic}
                samples.append(sample)
                log.write(json.dumps(sample, ensure_ascii=False) + "\n")
                log.flush()
                if (sequence + 1) % 30 == 0 or sequence + 1 == len(selected):
                    counts = summarize(samples, metadata["labels"])["overall"]
                    print(json.dumps({"completed": sequence + 1, "total": len(selected),
                                      "split": row["split"], "source": row["source"],
                                      "elapsed_seconds": round(time.monotonic() - started, 1),
                                      **{key: counts[key] for key in ("correct", "wrong", "uncertain")}}), flush=True)
    return samples


DOMINANT_VI = {"none": "Chưa thấy lỗi", "wrong": "Nhận nhầm", "uncertain": "Không xác định",
               "mixed": "Hai loại ngang nhau", "no_samples": "Chưa có mẫu"}
REASON_VI = {"idle_winner": "Model ưu tiên Không ký hiệu", "low_confidence": "Tin cậy dưới 70%",
             "low_margin": "Chênh lệch top 1/top 2 dưới 15%"}
GROUP_VI = {"test:standing": "Test đứng (chưa dùng chọn checkpoint)",
            "validation:seated": "Validation ngồi (đã dùng chọn checkpoint)",
            "validation:standing": "Validation đứng (đã dùng chọn checkpoint)"}


def write_reports(report, output):
    with (output / "report.json").open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    fields = ["group", "label", "samples", "correct", "wrong", "uncertain", "correct_pct", "wrong_pct",
              "uncertain_pct", "raw_top1_correct_pct", "dominant_error", "wrong_labels", "uncertain_top1", "uncertain_reasons"]
    with (output / "per_word.csv").open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for group, data in report["groups"].items():
            for row in data["per_word"]:
                values = {field: row.get(field) for field in fields if field != "group"}
                for field in ("wrong_labels", "uncertain_top1", "uncertain_reasons"):
                    values[field] = json.dumps(values[field], ensure_ascii=False)
                writer.writerow({"group": group, **values})
    with (output / "errors.csv").open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["group", "expected", "status", "accepted_label", "raw_top1",
                                                  "confidence", "margin", "reasons", "path"])
        writer.writeheader()
        for sample in report["samples"]:
            if sample["reply"]["status"] == "ok" and sample["reply"]["label"] == sample["expected_label"]:
                continue
            diagnostic = sample["diagnostic"]
            writer.writerow({"group": sample["split"] + ":" + sample["source"], "expected": sample["expected_label"],
                             "status": sample["reply"]["status"], "accepted_label": sample["reply"]["label"],
                             "raw_top1": diagnostic["raw_top1"], "confidence": diagnostic["raw_confidence"],
                             "margin": diagnostic.get("raw_margin"), "reasons": ";".join(diagnostic["rejection_reasons"]),
                             "path": str((Path(report["project_root"]) / sample["path"]).resolve())})
    lines = ["# Độ chính xác từng từ của runtime hiện tại", "", f"- Thời điểm: {report['finished_at']}.",
             f"- Model: `{report['metadata_before']['model_version']}`, backend Core ML, tin cậy 70%, margin 15%.",
             f"- Đã gửi {len(report['samples'])} clip qua WebSocket của backend đang chạy; không chỉnh model/ngưỡng.",
             "- Đúng = backend chấp nhận đúng từ. Nhầm = backend chấp nhận từ khác. Không xác định = backend không chấp nhận từ nào.",
             "- Cả ba tỷ lệ đều chia cho TOÀN BỘ clip của từ. Top 1 thô đúng chưa chắc được chấp nhận.",
             "- Gợi ý top_k khi không xác định KHÔNG được tính thành nhận nhầm.",
             "- Clip không xác định được chạy chẩn đoán riêng trên cùng byte ảnh và cùng artifact; quyết định/gợi ý khớp API.",
             "- Không trộn validation với test. Các clip personal-100 đều thuộc train và không được đưa vào tỷ lệ này.",
             "- Không có mẫu Không ký hiệu độc lập trong test/validation, nên chưa đo được tỷ lệ chấp nhận sai chuyển động nền.",
             "- Kiểm tra checksum và group không giao nhau giữa các split; chưa chứng minh độc lập người ký/phiên quay.",
             "- Nhãn kỳ vọng theo manifest, chưa được chuyên gia VSL kiểm định độc lập.",
             "- Đây là replay clip đã chia sẵn, 16 frame đều toàn clip, resize 224x224, JPEG 90. Không test cắt cử chỉ tự động, crop trình duyệt, câu liên tục hoặc camera mới.",
             "- Số mẫu test của một số từ ít (Chào 3, Mua 4, Tôi 5); 100% trên ít mẫu không bảo đảm 100% ngoài thực tế.",
             "- Tổng số lý do từ chối có thể vượt số clip vì một clip có nhiều lý do cùng lúc.", ""]
    for group, data in report["groups"].items():
        overall = data["overall"]
        lines += [f"## {GROUP_VI.get(group, group)}", "",
                  f"Tổng {overall['samples']} clip: đúng {overall['correct_pct']:.2f}%, nhầm {overall['wrong_pct']:.2f}%, không xác định {overall['uncertain_pct']:.2f}%.", "",
                  "| Từ | N | Đúng % | Nhầm % | Không xác định % | Top 1 thô đúng % | Lỗi chủ yếu |",
                  "|---|---:|---:|---:|---:|---:|---|"]
        for row in data["per_word"]:
            percent = lambda key: f"{row[key]:.2f}" if row[key] is not None else "N/A"
            lines.append(f"| {row['label']} | {row['samples']} | {percent('correct_pct')} | {percent('wrong_pct')} | {percent('uncertain_pct')} | {percent('raw_top1_correct_pct')} | {DOMINANT_VI[row['dominant_error']]} |")
        lines += ["", "### Ghi chú lỗi từng từ", ""]
        for row in data["per_word"]:
            lines += [f"#### {row['label']}", "",
                      f"- {row['correct']}/{row['samples']} đúng; {row['wrong']} nhận nhầm; {row['uncertain']} không xác định. Lỗi chủ yếu: {DOMINANT_VI[row['dominant_error']]}."]
            if row["wrong_labels"]:
                lines.append("- Nhận nhầm đã chấp nhận: " + "; ".join(f"{label}: {count} clip" for label, count in row["wrong_labels"].items()) + ".")
            if row["uncertain_reasons"]:
                lines.append("- Lý do không xác định đã đo: " + "; ".join(f"{REASON_VI[key]}: {count} clip" for key, count in row["uncertain_reasons"].items()) + ".")
                lines.append("- Top 1 thô trong clip bị từ chối (không phải từ đã chấp nhận): " + "; ".join(f"{label}: {count}" for label, count in row["uncertain_top1"].items()) + ".")
            if row["wrong"] or row["uncertain"]:
                lines.append("- Chưa xác nhận nguyên nhân vật lý (góc máy, tay bị che, khác người ký, sai nhãn). Không suy ra nguyên nhân này chỉ từ confidence/confusion.")
            lines.append("")
    lines += ["## Bảo toàn và tái lập", "",
              f"- Model, labels, manifest và Core ML package không đổi: {report['protected_artifacts_unchanged']}.",
              f"- Metadata runtime trước/sau không đổi: {report['metadata_unchanged']}.",
              "- Dữ liệu từng request: `predictions.jsonl`; bảng từng từ: `per_word.csv`; từng lỗi: `errors.csv`; toàn bộ kết quả/checksum: `report.json`."]
    with (output / "README.md").open("x", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main(argv=None):
    from app.backends.coreml import CoreMLInferenceBackend
    from ml.scripts.personal_coreml import package_hash, verify_deployment, verify_source

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--artifact-dir", type=Path, default=Path("ml/artifacts/sales30_personal_v1"))
    parser.add_argument("--coreml-dir", type=Path, default=Path("ml/artifacts/sales30_personal_coreml_fp32_r4"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--framing-dir", type=Path,
                        help="Observations from build_sales30_framing; send trim-bodycrop-v1 framed clips")
    args = parser.parse_args(argv)
    if args.output_dir.exists():
        parser.error("Use a fresh output directory")
    root = Path(__file__).resolve().parents[2]
    url = args.url.rstrip("/")
    manifest = args.artifact_dir / "manifest.csv"
    version, units = verify_deployment(args.artifact_dir, args.coreml_dir, args.coreml_dir / "benchmark_r2/benchmark.json")
    identity = verify_source(args.artifact_dir)
    protected = {"source": identity, "manifest_sha256": file_hash(manifest),
                 "coreml_package_sha256": package_hash(args.coreml_dir / "model.mlpackage"),
                 "coreml_labels_sha256": file_hash(args.coreml_dir / "labels.json")}
    metadata = get_metadata(url)
    validate_metadata(metadata, version, identity["labels"], "coreml")
    with manifest.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    selected = select_held_out(rows, identity["labels"], root)
    print(json.dumps({"stage": "verified_inputs", "samples": len(selected),
                      "groups": dict(Counter(row['split'] + ':' + row['source'] for row in selected)),
                      "compute_units": units}), flush=True)
    backend = CoreMLInferenceBackend(args.coreml_dir / "model.mlpackage", args.coreml_dir / "labels.json",
                                     version, .7, .15, compute_units=units, labels_verified=True)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    encoder = None
    if args.framing_dir:
        from ml.body_framing import load_observations

        if metadata.get("input_framing") != "trim-bodycrop-v1":
            raise ValueError("Runtime does not expect trim-bodycrop-v1 input")
        encoder = framed_encoder(load_observations(args.framing_dir))
    samples = asyncio.run(replay(url, metadata, selected, root, args.output_dir, backend, encoder))
    after = get_metadata(url)
    validate_metadata(after, version, identity["labels"], "coreml")
    after_protected = {"source": verify_source(args.artifact_dir), "manifest_sha256": file_hash(manifest),
                       "coreml_package_sha256": package_hash(args.coreml_dir / "model.mlpackage"),
                       "coreml_labels_sha256": file_hash(args.coreml_dir / "labels.json")}
    select_held_out(rows, identity["labels"], root)
    if metadata != after or protected != after_protected:
        raise ValueError("Model, metadata or evaluation inputs changed during evaluation")
    groups = {group: summarize([sample for sample in samples if sample["split"] + ":" + sample["source"] == group], identity["labels"])
              for group in sorted({sample["split"] + ":" + sample["source"] for sample in samples})}
    report = {"completed": True, "finished_at": datetime.now(timezone.utc).isoformat(), "project_root": str(root),
              "url": url, "metadata_before": metadata, "metadata_after": after, "metadata_unchanged": True,
              "protected_artifacts": protected, "protected_artifacts_unchanged": True, "compute_units": units,
              "held_out_bytes_verified_before_and_after": True, "cross_split_hash_and_group_leakage": False,
              "signer_independence_verified": False, "semantic_labels_independently_verified": False,
              "real_camera_evaluation": False, "negative_held_out_samples": 0,
              "input_framing": "trim-bodycrop-v1" if encoder else "uniform16-full-frame",
              "training_counts": {label: dict(Counter(row["source"] for row in rows if row["split"] == "train" and row["label"] == label))
                                  for label in identity["labels"]},
              "groups": groups, "samples": samples}
    write_reports(report, args.output_dir)
    print(json.dumps({"completed": True, "output_dir": str(args.output_dir.resolve()),
                      "groups": {group: data["overall"] for group, data in groups.items()}}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
