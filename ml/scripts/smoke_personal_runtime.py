"""Validate the real local personal-model WebSocket runtime with recorded clips."""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.request import urlopen
from uuid import uuid4

from contracts.v1.inference import PredictionMessage


IDLE_LABEL = "Không ký hiệu"


def validate_metadata(data: dict, version: str, labels: list[str], backend: str = "pytorch") -> None:
    expected = {"model_version": version, "labels": labels, "backend": backend,
                "mock": False, "candidate_labels_unverified": False,
                "frame_count": 16, "frame_width": 224, "frame_height": 224,
                "confidence_threshold": .7, "margin_threshold": .15}
    if any(data.get(field) != value for field, value in expected.items()):
        raise ValueError("Runtime metadata does not match the verified candidate")


def validate_reply(data: dict, sequence: int, version: str, labels: list[str]) -> None:
    prediction = PredictionMessage.model_validate(data)
    if prediction.sequence != sequence or prediction.model_version != version:
        raise ValueError("Stale or mismatched runtime reply")
    if prediction.label == IDLE_LABEL or any(item.label == IDLE_LABEL for item in prediction.top_k):
        raise ValueError("Runtime offered idle as a word")
    if prediction.status.value not in {"ok", "uncertain"}:
        raise ValueError(f"Unexpected runtime reply: {prediction.status.value}")
    if any(item.label not in labels for item in prediction.top_k):
        raise ValueError("Unknown label in runtime reply")
    if prediction.status.value == "ok":
        if prediction.label not in labels or prediction.top_k[0].label != prediction.label:
            raise ValueError("Invalid accepted runtime reply")
    elif prediction.label is not None or prediction.confidence is not None:
        raise ValueError("Uncertain runtime reply must not accept a word")


def select_samples(batch: Path, negative_limit: int) -> list[tuple[Path, dict]]:
    grouped = defaultdict(list)
    for path in batch.rglob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        grouped[data["expected_label"]].append((path.with_suffix(".mp4"), data))
    key = lambda sample: (sample[1]["captured_at"], sample[0].name)
    positives = [min(samples, key=key) for label, samples in sorted(grouped.items()) if label != IDLE_LABEL]
    negatives = sorted(grouped[IDLE_LABEL], key=key)
    by_action = {}
    for sample in negatives:
        by_action.setdefault(sample[1]["negative_action"], sample)
    selected = list(by_action.values())[:negative_limit]
    chosen_paths = {sample[0] for sample in selected}
    for sample in negatives:
        if len(selected) >= negative_limit:
            break
        if sample[0] not in chosen_paths:
            selected.append(sample)
            chosen_paths.add(sample[0])
    return positives + selected


def encode_frames(video: Path) -> list[str]:
    from ml.visignlanguage import decode_video, temporal_indices

    frames = decode_video(video)
    encoded = []
    try:
        for index in temporal_indices(len(frames), 16, False):
            image = frames[int(index)].resize((224, 224))
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=90)
            encoded.append("data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"))
            image.close()
    finally:
        for image in frames:
            image.close()
    return encoded


async def run_smoke(url: str, version: str, labels: list[str], samples):
    import websockets

    session = str(uuid4())
    ws_url = url.replace("http://", "ws://", 1).replace("https://", "wss://", 1) + "/ws/inference"
    results = []
    async with websockets.connect(ws_url, max_size=6 * 1024 * 1024) as socket:
        for sequence, (path, metadata) in enumerate(samples):
            frames = encode_frames(path)
            payload = {"type": "frames", "session_id": session, "sequence": sequence,
                       "captured_at": int(time.time() * 1000), "frames": frames}
            started = time.monotonic()
            await socket.send(json.dumps(payload))
            reply = json.loads(await asyncio.wait_for(socket.recv(), timeout=60))
            validate_reply(reply, sequence, version, labels)
            results.append({"path": str(path), "expected_label": metadata["expected_label"],
                            "negative_action": metadata.get("negative_action"),
                            "response_seconds": time.monotonic() - started, "reply": reply})
            print(json.dumps({"sequence": sequence, "expected": metadata["expected_label"],
                              "status": reply["status"], "label": reply["label"]}, ensure_ascii=False), flush=True)
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8001")
    parser.add_argument("--backend", choices=("pytorch", "coreml"), default="pytorch")
    parser.add_argument("--artifact-dir", type=Path, default=Path("ml/artifacts/sales30_personal_v1"))
    parser.add_argument("--batch", type=Path, default=Path("ml/data/collected/sales30/batches/personal-100"))
    parser.add_argument("--negative-limit", type=int, default=7)
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.negative_limit < 1 or args.output_json.exists():
        parser.error("Use a positive negative-limit and a new output-json path")
    summary = json.loads((args.artifact_dir / "summary.json").read_text(encoding="utf-8"))
    labels = json.loads((args.artifact_dir / "labels.json").read_text(encoding="utf-8"))
    if not summary["deployment_gate_passed"]:
        raise ValueError("Candidate deployment gate failed")
    version = summary["model_version"]
    url = args.url.rstrip("/")
    with urlopen(url + "/metadata", timeout=10) as response:
        metadata = json.load(response)
    validate_metadata(metadata, version, labels, backend=args.backend)
    samples = select_samples(args.batch, args.negative_limit)
    results = asyncio.run(run_smoke(url, version, labels, samples))
    negatives = [sample for sample in results if sample["expected_label"] == IDLE_LABEL]
    positives = [sample for sample in results if sample["expected_label"] != IDLE_LABEL]
    report = {"passed": True, "model_version": version, "url": url, "metadata": metadata,
              "requests": len(results), "positive_replays": len(positives), "negative_replays": len(negatives),
              "negative_false_accepts": sum(sample["reply"]["status"] == "ok" for sample in negatives),
              "positive_correct_accepts": sum(sample["reply"]["status"] == "ok" and sample["reply"]["label"] == sample["expected_label"] for sample in positives),
              "negative_actions": dict(Counter(sample["negative_action"] for sample in negatives)),
              "samples": results, "independent_camera_evaluation": False,
              "limits": "Transport/model integration smoke using training recordings; not unseen-session accuracy or a latency benchmark"}
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    with args.output_json.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({key: report[key] for key in ("passed", "model_version", "requests", "negative_false_accepts", "positive_correct_accepts")}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
