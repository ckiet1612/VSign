from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from ml.landmarks_v2 import FEATURE_DIM as V3_FEATURE_DIM
from ml.landmarks_v4 import (
    FEATURE_DIM as V4_FEATURE_DIM,
    HAND_GLOBAL_OFFSET,
    HAND_PRESENCE_OFFSET,
    POSE_COORDINATE_OFFSET,
    POSE_PRESENCE_OFFSET,
)


SEQUENCE_LENGTH = 16
PRE_ROLL_MS = 650.0
POST_ROLL_MS = 240.0
START_MOTION_THRESHOLD = 0.009
END_MOTION_THRESHOLD = 0.0045
START_CONFIRM_MS = 55.0
START_CANDIDATE_GAP_MS = 180.0
MINIMUM_GESTURE_MS = 650.0
QUIET_TO_FINISH_MS = 420.0
MISSING_SIGNAL_TO_FINISH_MS = 420.0
MAXIMUM_GESTURE_MS = 3_000.0
MINIMUM_HAND_FRAMES = 4
MOTION_REFERENCE_FRAME_MS = 1000.0 / 30.0
MOTION_POINT_INDICES = (0, 4, 8, 12, 16, 20)


@dataclass(frozen=True)
class PairedFrame:
    timestamp_ms: float
    v3: np.ndarray
    v4: np.ndarray


@dataclass(frozen=True)
class PairedSequence:
    v3: np.ndarray
    v4: np.ndarray
    source_indices: tuple[int, ...]


def has_v4_hand(frame: np.ndarray) -> bool:
    values = np.asarray(frame)
    return bool(
        values[HAND_PRESENCE_OFFSET] > 0.5
        or values[HAND_PRESENCE_OFFSET + 1] > 0.5
    )


def has_v4_arm_pose(frame: np.ndarray) -> bool:
    values = np.asarray(frame)
    return bool(np.max(values[POSE_PRESENCE_OFFSET + 7 : POSE_PRESENCE_OFFSET + 11]) > 0.5)


def v4_landmark_motion(previous: np.ndarray | None, current: np.ndarray | None) -> float:
    if previous is None or current is None:
        return 0.0
    previous_signal = has_v4_hand(previous) or has_v4_arm_pose(previous)
    current_signal = has_v4_hand(current) or has_v4_arm_pose(current)
    if not previous_signal and current_signal:
        return 0.05
    if not previous_signal or not current_signal:
        return 0.0

    distance = 0.0
    points = 0
    for hand in range(2):
        presence_index = HAND_PRESENCE_OFFSET + hand
        if previous[presence_index] <= 0.5 or current[presence_index] <= 0.5:
            continue
        global_offset = HAND_GLOBAL_OFFSET + hand * 3
        distance += float(
            np.linalg.norm(
                current[global_offset : global_offset + 2]
                - previous[global_offset : global_offset + 2]
            )
        )
        points += 1
        for point in MOTION_POINT_INDICES:
            offset = hand * 63 + point * 3
            distance += float(
                np.linalg.norm(current[offset : offset + 2] - previous[offset : offset + 2])
            )
            points += 1
    for pose_point in range(7, 11):
        presence_index = POSE_PRESENCE_OFFSET + pose_point
        if previous[presence_index] <= 0.5 or current[presence_index] <= 0.5:
            continue
        offset = POSE_COORDINATE_OFFSET + pose_point * 3
        distance += float(
            np.linalg.norm(current[offset : offset + 2] - previous[offset : offset + 2])
        )
        points += 1
    return distance / points if points else 0.0


def normalized_v4_motion(previous: PairedFrame | None, current: PairedFrame) -> float:
    if previous is None:
        return 0.0
    elapsed = current.timestamp_ms - previous.timestamp_ms
    if not np.isfinite(elapsed) or elapsed <= 0:
        return 0.0
    normalized_elapsed = min(160.0, max(16.0, float(elapsed)))
    return v4_landmark_motion(previous.v4, current.v4) * (
        MOTION_REFERENCE_FRAME_MS / normalized_elapsed
    )


def uniform_sample_indices(length: int, count: int = SEQUENCE_LENGTH) -> list[int]:
    if length <= 0 or count <= 0:
        raise ValueError("Số frame và số mẫu phải lớn hơn 0")
    if count == 1:
        return [(length - 1) // 2]
    return [
        int(np.floor((index * (length - 1)) / (count - 1) + 0.5))
        for index in range(count)
    ]


def motion_weighted_sample_indices(
    length: int,
    motion_scores: Sequence[float],
    count: int = SEQUENCE_LENGTH,
) -> list[int]:
    if len(motion_scores) != length:
        raise ValueError("Motion score phải khớp số frame")
    if length <= count:
        return uniform_sample_indices(length, count)
    motion = np.maximum(np.nan_to_num(np.asarray(motion_scores), nan=0.0), 0.0)
    peak = float(motion.max())
    if peak <= 1e-8:
        return uniform_sample_indices(length, count)
    weights = 0.6 + np.minimum(motion / peak, 2.0) * 1.4
    cumulative = np.cumsum(weights)
    total = float(cumulative[-1])
    chosen = {0, length - 1}
    for slot in range(1, count - 1):
        target = total * slot / (count - 1)
        index = int(np.searchsorted(cumulative, target, side="left"))
        chosen.add(max(1, min(length - 2, index)))
    peak_index = int(np.argmax(motion))
    if 0 < peak_index < length - 1 and peak_index not in chosen:
        replaceable = sorted(
            (index for index in chosen if 0 < index < length - 1),
            key=lambda index: abs(index - peak_index),
        )
        if replaceable:
            chosen.remove(replaceable[0])
        chosen.add(peak_index)
    for index in uniform_sample_indices(length, count):
        if len(chosen) >= count:
            break
        chosen.add(index)
    for index in range(1, length - 1):
        if len(chosen) >= count:
            break
        chosen.add(index)
    return sorted(chosen)


def _paired_sequence(frames: Sequence[PairedFrame], indices: Sequence[int]) -> PairedSequence:
    return PairedSequence(
        v3=np.stack([frames[index].v3 for index in indices]).astype(np.float32),
        v4=np.stack([frames[index].v4 for index in indices]).astype(np.float32),
        source_indices=tuple(int(index) for index in indices),
    )


def manual_sequence(frames: Sequence[PairedFrame]) -> PairedSequence:
    if not frames:
        raise ValueError("Video không có frame")
    scores = [
        0.0
        if index == 0
        else v4_landmark_motion(frames[index - 1].v4, frame.v4)
        for index, frame in enumerate(frames)
    ]
    indices = motion_weighted_sample_indices(len(frames), scores)
    return _paired_sequence(frames, indices)


def _trim_pose_context(frames: Sequence[PairedFrame]) -> list[PairedFrame]:
    first_hand = next(
        (index for index, frame in enumerate(frames) if has_v4_hand(frame.v4)),
        -1,
    )
    if first_hand < 0:
        return []
    last_hand = len(frames) - 1
    while last_hand > first_hand and not has_v4_hand(frames[last_hand].v4):
        last_hand -= 1
    first = first_hand
    while first > 0 and has_v4_arm_pose(frames[first - 1].v4):
        first -= 1
    last = last_hand
    while last + 1 < len(frames) and has_v4_arm_pose(frames[last + 1].v4):
        last += 1
    return list(frames[first : last + 1])


class AutomaticReplaySegmenter:
    """Python parity implementation of the browser's automatic state machine."""

    def __init__(self) -> None:
        self.phase = "waiting"
        self.previous: PairedFrame | None = None
        self.motion_window: list[float] = []
        self.pre_roll: list[PairedFrame] = []
        self.recording: list[PairedFrame] = []
        self.started_at = 0.0
        self.quiet_started_at: float | None = None
        self.missing_started_at: float | None = None
        self.post_roll_until = 0.0
        self.start_candidate_at: float | None = None
        self.start_candidate_last_at: float | None = None
        self.start_candidate_frames = 0

    def _reset_candidate(self) -> None:
        self.start_candidate_at = None
        self.start_candidate_last_at = None
        self.start_candidate_frames = 0

    def push(self, current: PairedFrame) -> PairedSequence | None:
        raw_motion = normalized_v4_motion(self.previous, current)
        self.motion_window.append(raw_motion)
        self.motion_window = self.motion_window[-3:]
        motion = float(np.median(self.motion_window))
        hands_visible = has_v4_hand(current.v4)
        signal_visible = hands_visible or has_v4_arm_pose(current.v4)
        self.previous = current

        if self.phase == "waiting":
            self.pre_roll.append(current)
            oldest = current.timestamp_ms - PRE_ROLL_MS
            while len(self.pre_roll) > 1 and self.pre_roll[0].timestamp_ms < oldest:
                self.pre_roll.pop(0)
            if hands_visible and motion >= START_MOTION_THRESHOLD:
                if self.start_candidate_at is None:
                    self.start_candidate_at = current.timestamp_ms
                self.start_candidate_last_at = current.timestamp_ms
                self.start_candidate_frames += 1
            elif (
                not hands_visible
                or motion <= END_MOTION_THRESHOLD
                or (
                    self.start_candidate_last_at is not None
                    and current.timestamp_ms - self.start_candidate_last_at
                    > START_CANDIDATE_GAP_MS
                )
            ):
                self._reset_candidate()
            if (
                self.start_candidate_at is not None
                and self.start_candidate_frames >= 2
                and current.timestamp_ms - self.start_candidate_at >= START_CONFIRM_MS
            ):
                self.phase = "capturing"
                self.recording = list(self.pre_roll)
                self.pre_roll = []
                self.started_at = self.start_candidate_at
                self._reset_candidate()
            return None

        self.recording.append(current)
        if self.phase == "postroll":
            if signal_visible and motion > END_MOTION_THRESHOLD:
                self.phase = "capturing"
                self.post_roll_until = 0.0
                self.quiet_started_at = None
                self.missing_started_at = None
                return None
            if current.timestamp_ms < self.post_roll_until:
                return None
            return self._finish()

        if not signal_visible:
            if self.missing_started_at is None:
                self.missing_started_at = current.timestamp_ms
        else:
            self.missing_started_at = None
        if motion <= END_MOTION_THRESHOLD:
            if self.quiet_started_at is None:
                self.quiet_started_at = current.timestamp_ms
        else:
            self.quiet_started_at = None

        elapsed = current.timestamp_ms - self.started_at
        quiet_for = (
            0.0
            if self.quiet_started_at is None
            else current.timestamp_ms - self.quiet_started_at
        )
        missing_for = (
            0.0
            if self.missing_started_at is None
            else current.timestamp_ms - self.missing_started_at
        )
        if elapsed >= MAXIMUM_GESTURE_MS:
            return self._finish()
        if elapsed >= MINIMUM_GESTURE_MS and (
            quiet_for >= QUIET_TO_FINISH_MS
            or missing_for >= MISSING_SIGNAL_TO_FINISH_MS
        ):
            self.phase = "postroll"
            self.post_roll_until = current.timestamp_ms + POST_ROLL_MS
        return None

    def _finish(self) -> PairedSequence | None:
        usable = _trim_pose_context(self.recording)
        if sum(has_v4_hand(frame.v4) for frame in usable) < MINIMUM_HAND_FRAMES:
            self.phase = "finished"
            return None
        scores = [
            0.0
            if index == 0
            else normalized_v4_motion(usable[index - 1], frame)
            for index, frame in enumerate(usable)
        ]
        indices = motion_weighted_sample_indices(len(usable), scores)
        self.phase = "finished"
        return _paired_sequence(usable, indices)


def automatic_sequence(frames: Sequence[PairedFrame]) -> PairedSequence | None:
    if not frames:
        raise ValueError("Video không có frame")
    if frames[0].v3.shape != (V3_FEATURE_DIM,) or frames[0].v4.shape != (V4_FEATURE_DIM,):
        raise ValueError("Feature V3/V4 không đúng kích thước")
    source_times = np.asarray([frame.timestamp_ms for frame in frames], dtype=np.float64)
    intervals = np.diff(source_times)
    valid_intervals = intervals[(intervals >= 16.0) & (intervals <= 160.0)]
    interval = float(np.median(valid_intervals)) if len(valid_intervals) else 75.0
    interval = min(100.0, max(30.0, interval))

    replay: list[PairedFrame] = []
    timestamp = 0.0
    while timestamp < PRE_ROLL_MS:
        replay.append(PairedFrame(timestamp, frames[0].v3, frames[0].v4))
        timestamp += interval
    source_start = timestamp
    initial_time = frames[0].timestamp_ms
    for frame in frames:
        replay.append(
            PairedFrame(
                source_start + frame.timestamp_ms - initial_time,
                frame.v3,
                frame.v4,
            )
        )
    timestamp = replay[-1].timestamp_ms + interval
    post_padding_end = timestamp + QUIET_TO_FINISH_MS + POST_ROLL_MS + 3 * interval
    while timestamp <= post_padding_end:
        replay.append(PairedFrame(timestamp, frames[-1].v3, frames[-1].v4))
        timestamp += interval

    segmenter = AutomaticReplaySegmenter()
    for frame in replay:
        sequence = segmenter.push(frame)
        if sequence is not None:
            return sequence
        if segmenter.phase == "finished":
            return None
    return None
