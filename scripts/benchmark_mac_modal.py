"""Compare live Mac/Modal WebSocket replay and application round-trip latency."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import platform
import time
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen
from uuid import uuid4

import websockets

from app.inference_token import issue_inference_token
from contracts.v1.inference import FramesMessage, PredictionMessage
from ml.scripts.benchmark_personal_cpu import timing_summary


def metadata(url: str) -> dict:
    with urlopen(url + "/metadata", timeout=55) as response:
        return json.load(response)


async def exchange(socket, payload: str) -> tuple[dict, float]:
    started = time.perf_counter()
    await socket.send(payload)
    raw = await asyncio.wait_for(socket.recv(), timeout=60)
    while json.loads(raw).get("type") == "runtime_info":
        raw = await asyncio.wait_for(socket.recv(), timeout=60)
    elapsed = (time.perf_counter() - started) * 1000
    return json.loads(raw), elapsed


async def run(args) -> dict:
    raw_fixture = args.fixture.read_bytes()
    samples = json.loads(raw_fixture)["samples"]
    session = str(uuid4())
    payloads = []
    for index, sample in enumerate(samples):
        payload = {"type": "frames", "session_id": session, "sequence": index,
                   "captured_at": int(time.time() * 1000), "frames": sample["frames"]}
        FramesMessage.model_validate(payload)
        payloads.append(json.dumps(payload, separators=(",", ":")))
    urls = {"mac": args.mac.rstrip("/"), "modal": args.modal.rstrip("/")}
    metadatas = {name: await asyncio.to_thread(metadata, url) for name, url in urls.items()}
    for field in ("model_version", "protocol_version", "labels", "input_framing",
                  "frame_count", "frame_width", "frame_height", "candidate_labels_unverified",
                  "confidence_threshold", "margin_threshold"):
        if metadatas["mac"].get(field) != metadatas["modal"].get(field):
            raise ValueError(f"Runtime mismatch: {field}")
    if any(value["mock"] for value in metadatas.values()):
        raise ValueError("Mock runtimes cannot be benchmarked")
    token, _ = issue_inference_token(args.secret_file.read_text().strip(), "local", "benchmark")
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "client": platform.platform(), "metadata": metadatas,
        "fixture": str(args.fixture), "fixture_sha256": hashlib.sha256(raw_fixture).hexdigest(),
        "clips": len(samples), "rounds": args.rounds, "warmups_per_backend": 2,
        "payload_bytes": [len(payload.encode()) for payload in payloads],
        "limits": "Prepared JPEG clips, 16 frames, single serial request, alternating backend order. "
                  "Recognition is send-to-prediction including upload/network/decode/model/policy; "
                  "no isolated model timing, camera, segmentation, encode, UI or load benchmark. "
                  "Application RTT uses a tiny invalid request rejected before image/model execution; "
                  "control ping can terminate at the hosting proxy. Existing training recordings are not accuracy evidence.",
        "results": {name: {"url": url, "warmups": [], "samples": [], "application_rtt_ms": [],
                           "control_ping_ms": []} for name, url in urls.items()},
    }
    async with AsyncExitStack() as stack:
        sockets = {}
        for name, url in urls.items():
            ws_url = url.replace("https://", "wss://").replace("http://", "ws://")
            started = time.perf_counter()
            sockets[name] = await stack.enter_async_context(websockets.connect(
                ws_url + "/ws/inference?token=" + token, origin="http://127.0.0.1:5174",
                compression=None, max_size=6 * 1024 * 1024, open_timeout=60,
                ping_interval=None,
            ))
            report["results"][name]["handshake_ms"] = (time.perf_counter() - started) * 1000
            if metadatas[name].get("gpu_name"):
                info = json.loads(await asyncio.wait_for(sockets[name].recv(), timeout=15))
                if (info.get("type") != "runtime_info"
                        or info.get("gpu_name") != metadatas[name]["gpu_name"]):
                    raise ValueError(f"Connected GPU identity changed for {name}")
                report["results"][name]["connected_gpu_name"] = info["gpu_name"]

        async def probe():
            for _ in range(20):
                for name, socket in sockets.items():
                    # Validation rejects this before acquiring an inference slot.
                    reply, elapsed = await exchange(socket, '{"type":"latency_probe"}')
                    if reply.get("status") != "error":
                        raise ValueError("Latency probe unexpectedly ran inference")
                    report["results"][name]["application_rtt_ms"].append(elapsed)
                    started = time.perf_counter()
                    pong = await socket.ping()
                    await asyncio.wait_for(pong, timeout=15)
                    report["results"][name]["control_ping_ms"].append(
                        (time.perf_counter() - started) * 1000)

        async def predict(name, index):
            reply, elapsed = await exchange(sockets[name], payloads[index])
            prediction = PredictionMessage.model_validate(reply)
            if (prediction.sequence != index or prediction.status.value not in {"ok", "uncertain"}
                    or prediction.model_version != metadatas[name]["model_version"]):
                raise ValueError(f"Invalid prediction from {name}: {prediction.status}")
            return {"clip": index, "path": samples[index]["path"], "response_ms": elapsed,
                    "reply": reply}

        await probe()
        for index in range(2):
            for name in sockets:
                result = await predict(name, index)
                report["results"][name]["warmups"].append(result)
                print(json.dumps({"warmup": name, "ms": round(result["response_ms"], 2)}), flush=True)
        for round_index in range(args.rounds):
            for index in range(len(samples)):
                order = ("mac", "modal") if (round_index + index) % 2 == 0 else ("modal", "mac")
                for name in order:
                    result = await predict(name, index)
                    result["round"] = round_index
                    report["results"][name]["samples"].append(result)
                if (index + 1) % 5 == 0:
                    print(json.dumps({"round": round_index + 1, "clips_done": index + 1,
                        "latest_ms": {name: round(report["results"][name]["samples"][-1]["response_ms"], 2)
                                      for name in sockets}}), flush=True)
                    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        await probe()
    for result in report["results"].values():
        result["summary"] = {
            "recognition_response": timing_summary([item["response_ms"] for item in result["samples"]]),
            "application_rtt": timing_summary(result["application_rtt_ms"]),
            "control_ping": timing_summary(result["control_ping_ms"]),
        }
    pairs = list(zip(report["results"]["mac"]["samples"], report["results"]["modal"]["samples"]))
    report["parity"] = {"pairs": len(pairs), "same_status_and_label": sum(
        (a["reply"]["status"], a["reply"]["label"]) == (b["reply"]["status"], b["reply"]["label"])
        for a, b in pairs)}
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mac", default="http://127.0.0.1:8000")
    parser.add_argument("--modal", default="https://ckiet1612--vsign-inference-inference-ap-southeast.ap-south.modal.run")
    parser.add_argument("--fixture", type=Path, default=Path(
        "ml/artifacts/sales30_personal_v3_bodycrop_curated_coreml_fp16/benchmark_r2/fixture.json"))
    parser.add_argument("--secret-file", type=Path, default=Path("data/inference-token-secret"))
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.rounds < 1 or args.output.exists():
        parser.error("Use positive rounds and a new output path")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = asyncio.run(run(args))
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "summary": {
        name: result["summary"] for name, result in report["results"].items()},
        "parity": report["parity"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
