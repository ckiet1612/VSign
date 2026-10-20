"""Record per-frame MediaPipe body/hand observations for every Sales30 training clip.

The observations feed ``ml.body_framing`` so training clips get the same signing-span
trim and body crop that the browser applies before sending frames to the model.
"""

from __future__ import annotations

import argparse
import csv
import json
import multiprocessing
import os
from pathlib import Path

from ml.body_framing import POSE_INDICES

# Match HandTrackingOverlay.tsx so offline and live detections agree.
HAND_CONFIDENCE = 0.35
POSE_CONFIDENCE = 0.3
SF_DATALESS = 0x40000000


def is_dataless(path: Path) -> bool:
    return bool(os.stat(path).st_flags & SF_DATALESS)


def observe_clip(path: Path, hand_detector, pose_detector, mp) -> dict:
    import av
    import numpy as np

    frames = []
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        width, height = stream.codec_context.width, stream.codec_context.height
        rate = float(stream.average_rate or 30)
        last_timestamp = -1
        for index, frame in enumerate(container.decode(video=0)):
            # Container timestamps are unreliable in re-encoded clips; frame order is not.
            timestamp = round(index * 1000 / rate, 1)
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(frame.to_ndarray(format="rgb24")))
            video_timestamp = max(last_timestamp + 1, int(timestamp))
            last_timestamp = video_timestamp
            hands = hand_detector.detect_for_video(image, video_timestamp)
            poses = pose_detector.detect(image)
            pose = None
            if poses.pose_landmarks:
                landmarks = poses.pose_landmarks[0]
                pose = [[round(landmarks[i].x, 4), round(landmarks[i].y, 4), round(landmarks[i].visibility or 0.0, 3)]
                        for i in POSE_INDICES]
            hand_rows = []
            for hand in hands.hand_landmarks:
                xs = [point.x for point in hand]
                ys = [point.y for point in hand]
                hand_rows.append([round(value, 4) for value in (hand[0].x, hand[0].y, min(xs), min(ys), max(xs), max(ys))])
            frames.append({"t": timestamp, "pose": pose, "hands": hand_rows})
    return {"width": width, "height": height, "fps": round(rate, 3), "frames": frames}


def recorded_paths(output: Path) -> set[str]:
    """Paths already observed; drops a line cut short by an interrupted run."""
    recorded = set()
    for shard in sorted(output.glob("observations_*.jsonl")):
        kept = []
        for line in shard.read_text(encoding="utf-8").splitlines():
            try:
                recorded.add(json.loads(line)["path"])
            except (json.JSONDecodeError, KeyError):
                continue
            kept.append(line)
        shard.write_text("".join(f"{line}\n" for line in kept), encoding="utf-8")
    return recorded


def worker(job: tuple[list[dict], Path, Path, Path, Path]) -> int:
    rows, root, hand_model, pose_model, shard = job
    os.environ.setdefault("GLOG_minloglevel", "2")
    import mediapipe as mp

    hand_options = mp.tasks.vision.HandLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(hand_model), delegate=mp.tasks.BaseOptions.Delegate.CPU),
        running_mode=mp.tasks.vision.RunningMode.VIDEO, num_hands=2,
        min_hand_detection_confidence=HAND_CONFIDENCE, min_hand_presence_confidence=HAND_CONFIDENCE,
        min_tracking_confidence=HAND_CONFIDENCE,
    )
    pose_options = mp.tasks.vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(pose_model), delegate=mp.tasks.BaseOptions.Delegate.CPU),
        running_mode=mp.tasks.vision.RunningMode.IMAGE, num_poses=1,
        min_pose_detection_confidence=POSE_CONFIDENCE, min_pose_presence_confidence=POSE_CONFIDENCE,
        min_tracking_confidence=POSE_CONFIDENCE, output_segmentation_masks=False,
    )
    written = 0
    with shard.open("a", encoding="utf-8") as handle, \
            mp.tasks.vision.PoseLandmarker.create_from_options(pose_options) as pose_detector:
        for row in rows:
            path = root / row["path"]
            if is_dataless(path):
                continue
            # VIDEO-mode hand tracking needs a fresh tracker per clip.
            with mp.tasks.vision.HandLandmarker.create_from_options(hand_options) as hand_detector:
                record = observe_clip(path, hand_detector, pose_detector, mp)
            record = {"path": row["path"], "sha256": row["sha256"], **record}
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
            handle.flush()
            written += 1
            if written % 50 == 0:
                print(json.dumps({"event": "progress", "shard": shard.name, "written": written}), flush=True)
    return written


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--manifest", type=Path, default=Path("ml/artifacts/sales30_personal_v1/manifest.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("ml/artifacts/sales30_framing_v1"))
    parser.add_argument("--hand-model", type=Path, default=Path("apps/web/public/models/hand_landmarker.task"))
    parser.add_argument("--pose-model", type=Path, default=Path("apps/web/public/models/pose_landmarker_lite.task"))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    with (root / args.manifest).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    output = root / args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    done = recorded_paths(output)
    pending = [row for row in rows if row["path"] not in done]
    jobs = [(pending[index::args.workers], root, root / args.hand_model, root / args.pose_model,
             output / f"observations_{index}.jsonl") for index in range(args.workers)]
    with multiprocessing.get_context("spawn").Pool(args.workers) as pool:
        written = sum(pool.map(worker, jobs))
    recorded = recorded_paths(output)
    missing = [row["path"] for row in rows if row["path"] not in recorded]
    print(json.dumps({"event": "done", "written": written, "recorded": len(recorded), "missing": len(missing)}), flush=True)
    return 0 if not missing else 3


if __name__ == "__main__":
    raise SystemExit(main())
