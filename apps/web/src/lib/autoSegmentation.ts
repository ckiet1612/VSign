import {
  emptyLandmarkFrame,
  HAND_GLOBAL_OFFSET,
  HAND_PRESENCE_OFFSET,
  hasHandLandmarks,
  LANDMARK_FEATURE_DIM,
  POSE_COORDINATE_OFFSET,
  POSE_PRESENCE_OFFSET,
} from "./landmarkFeatures";
import {
  BASELINE_FEATURE_DIM,
  emptyBaselineLandmarkFrame,
} from "./landmarkFeaturesV3";
import { motionWeightedSampleIndices, TARGET_FRAME_COUNT } from "./sampling";

export type AutomaticCapturePhase =
  | "off"
  | "waiting"
  | "capturing"
  | "postroll"
  | "encoding"
  | "cooldown"
  | "rearming";

export interface SegmentWindow {
  startAt: number;
  endAt: number;
}

/**
 * A segment cut as soon as the hands have been still for SPECULATE_AFTER_MS. If the
 * sign then ends on that same rest, the final segment is exactly this one.
 */
export interface ProvisionalSegment {
  id: number;
  sequence: number[][];
  baselineSequence: number[][];
  sourceWindow: SegmentWindow;
}

export interface AutomaticSegmentUpdate {
  phase: AutomaticCapturePhase;
  sequence: number[][] | null;
  baselineSequence?: number[][] | null;
  sourceWindow?: SegmentWindow | null;
  motion: number;
  /** Emitted once per rest; run inference on it right away. */
  provisional?: ProvisionalSegment;
  /** The hands moved again: discard this provisional segment's result. */
  provisionalCancelled?: number;
  /** The final `sequence` is this provisional segment, already sent. */
  confirmedProvisional?: number;
}

interface TimedLandmarkFrame {
  features: number[];
  baselineFeatures: number[];
  timestamp: number;
}

// Time-based buffers keep the same behavior when MediaPipe fluctuates between
// roughly 15 and 30 FPS.
export const PRE_ROLL_MS = 650;
const POST_ROLL_MS = 240;
const START_MOTION_THRESHOLD = 0.009;
const END_MOTION_THRESHOLD = 0.0045;
const START_CONFIRM_MS = 55;
const START_CANDIDATE_GAP_MS = 180;
const READY_QUIET_MS = 260;
const MINIMUM_GESTURE_MS = 650;
const QUIET_TO_FINISH_MS = 420;
// Start inference this long into a rest instead of waiting for the full quiet + post-roll.
export const SPECULATE_AFTER_MS = 150;
const MISSING_SIGNAL_TO_FINISH_MS = 420;
const MAXIMUM_GESTURE_MS = 3_000;
const COOLDOWN_MS = 700;
const MINIMUM_HAND_FRAMES = 4;
const MOTION_REFERENCE_FRAME_MS = 1000 / 30;
const MOTION_POINT_INDICES = [0, 4, 8, 12, 16, 20] as const;

function hasArmPose(frame: readonly number[]): boolean {
  for (let point = 7; point <= 10; point += 1) {
    if (frame[POSE_PRESENCE_OFFSET + point] > 0.5) return true;
  }
  return false;
}

function copyFrame(features: readonly number[] | null): number[] {
  return features?.length === LANDMARK_FEATURE_DIM
    ? Array.from(features)
    : emptyLandmarkFrame();
}

function copyBaselineFrame(features: readonly number[] | null): number[] {
  return features?.length === BASELINE_FEATURE_DIM
    ? Array.from(features)
    : emptyBaselineLandmarkFrame();
}

function trimMissingEdges(
  frames: readonly TimedLandmarkFrame[],
): TimedLandmarkFrame[] {
  const firstHand = frames.findIndex((item) =>
    hasHandLandmarks(item.features),
  );
  if (firstHand < 0) return [];
  let lastHand = frames.length - 1;
  while (
    lastHand > firstHand &&
    !hasHandLandmarks(frames[lastHand].features)
  ) {
    lastHand -= 1;
  }

  // Pose-only context is useful before/after a sign and while hands overlap,
  // but it must never make a body-only clip eligible for inference.
  let firstUsable = firstHand;
  while (firstUsable > 0 && hasArmPose(frames[firstUsable - 1].features)) {
    firstUsable -= 1;
  }
  let lastUsable = lastHand;
  while (
    lastUsable + 1 < frames.length &&
    hasArmPose(frames[lastUsable + 1].features)
  ) {
    lastUsable += 1;
  }
  return frames.slice(firstUsable, lastUsable + 1);
}

export function landmarkMotion(
  previous: readonly number[] | null,
  current: readonly number[] | null,
): number {
  if (!previous || !current) return 0;
  const previousHasSignal = hasHandLandmarks(previous) || hasArmPose(previous);
  const currentHasSignal = hasHandLandmarks(current) || hasArmPose(current);
  if (!previousHasSignal && currentHasSignal) return 0.05;
  if (!previousHasSignal || !currentHasSignal) return 0;

  let distance = 0;
  let points = 0;
  for (let hand = 0; hand < 2; hand += 1) {
    const presenceIndex = HAND_PRESENCE_OFFSET + hand;
    const present =
      previous[presenceIndex] > 0.5 && current[presenceIndex] > 0.5;
    if (!present) continue;
    const globalOffset = HAND_GLOBAL_OFFSET + hand * 3;
    distance += Math.hypot(
      current[globalOffset] - previous[globalOffset],
      current[globalOffset + 1] - previous[globalOffset + 1],
    );
    points += 1;
    for (const point of MOTION_POINT_INDICES) {
      const offset = hand * 63 + point * 3;
      const dx = current[offset] - previous[offset];
      const dy = current[offset + 1] - previous[offset + 1];
      distance += Math.hypot(dx, dy);
      points += 1;
    }
  }
  // Pose elbows/wrists keep motion continuous while detailed hand landmarks
  // disappear behind the other hand. Pose slots 7..10 map to elbows/wrists.
  for (let posePoint = 7; posePoint <= 10; posePoint += 1) {
    const presenceIndex = POSE_PRESENCE_OFFSET + posePoint;
    if (
      previous[presenceIndex] <= 0.5 ||
      current[presenceIndex] <= 0.5
    ) continue;
    const offset = POSE_COORDINATE_OFFSET + posePoint * 3;
    distance += Math.hypot(
      current[offset] - previous[offset],
      current[offset + 1] - previous[offset + 1],
    );
    points += 1;
  }
  if (!points) return 0;
  return distance / points;
}

function normalizedMotion(
  previous: TimedLandmarkFrame | null,
  current: TimedLandmarkFrame,
): number {
  if (!previous) return 0;
  const elapsed = current.timestamp - previous.timestamp;
  if (!Number.isFinite(elapsed) || elapsed <= 0) return 0;
  // Cap extreme callback gaps. A resumed/backgrounded tab must not look like a
  // sudden gesture, while ordinary 15–30 FPS motion remains comparable.
  const normalizedElapsed = Math.min(160, Math.max(16, elapsed));
  return (
    landmarkMotion(previous.features, current.features) *
    (MOTION_REFERENCE_FRAME_MS / normalizedElapsed)
  );
}

function median(values: readonly number[]): number {
  if (!values.length) return 0;
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2
    ? sorted[middle]
    : (sorted[middle - 1] + sorted[middle]) / 2;
}

export class AutomaticSignSegmenter {
  private currentPhase: AutomaticCapturePhase = "off";
  private previous: TimedLandmarkFrame | null = null;
  private motionWindow: number[] = [];
  private preRoll: TimedLandmarkFrame[] = [];
  private recording: TimedLandmarkFrame[] = [];
  private startedAt = 0;
  private quietStartedAt: number | null = null;
  private missingStartedAt: number | null = null;
  private postRollUntil = 0;
  private cooldownUntil = 0;
  private readyQuietStartedAt: number | null = null;
  private startCandidateAt: number | null = null;
  private startCandidateLastAt: number | null = null;
  private startCandidateFrames = 0;
  private provisional: ProvisionalSegment | null = null;
  private provisionalCount = 0;
  private speculate = false;

  /** Only the server RGB path speculates; landmark models keep their full segments. */
  setSpeculation(enabled: boolean): void {
    this.speculate = enabled;
    if (!enabled) this.provisional = null;
  }

  get phase(): AutomaticCapturePhase {
    return this.currentPhase;
  }

  reset(enabled: boolean, requireQuiet = false): void {
    this.currentPhase = enabled ? requireQuiet ? "rearming" : "waiting" : "off";
    this.previous = null;
    this.motionWindow = [];
    this.preRoll = [];
    this.recording = [];
    this.startedAt = 0;
    this.quietStartedAt = null;
    this.missingStartedAt = null;
    this.postRollUntil = 0;
    this.cooldownUntil = 0;
    this.readyQuietStartedAt = null;
    this.provisional = null;
    this.resetStartCandidate();
  }

  push(
    features: readonly number[] | null,
    timestamp: number,
    baselineFeatures: readonly number[] | null = null,
  ): AutomaticSegmentUpdate {
    const current: TimedLandmarkFrame = {
      features: copyFrame(features),
      baselineFeatures: copyBaselineFrame(baselineFeatures),
      timestamp,
    };
    const rawMotion = normalizedMotion(this.previous, current);
    this.motionWindow.push(rawMotion);
    if (this.motionWindow.length > 3) this.motionWindow.shift();
    const motion = median(this.motionWindow);
    const handsVisible = hasHandLandmarks(current.features);
    const gestureSignalVisible = handsVisible || hasArmPose(current.features);
    this.previous = current;

    if (this.currentPhase === "off") {
      return { phase: "off", sequence: null, motion };
    }

    if (
      this.currentPhase === "waiting" || this.currentPhase === "cooldown" ||
      this.currentPhase === "rearming"
    ) {
      this.preRoll.push(current);
      const oldestAllowed = timestamp - PRE_ROLL_MS;
      while (
        this.preRoll.length > 1 &&
        this.preRoll[0].timestamp < oldestAllowed
      ) {
        this.preRoll.shift();
      }

    }

    if (this.currentPhase === "cooldown" || this.currentPhase === "rearming") {
      if (!handsVisible || motion <= END_MOTION_THRESHOLD) {
        this.readyQuietStartedAt ??= timestamp;
      } else {
        this.readyQuietStartedAt = null;
      }
      const quietReady = this.readyQuietStartedAt !== null &&
        timestamp - this.readyQuietStartedAt >= READY_QUIET_MS;
      // Observe the rest during the safety cooldown, not in another wait afterwards.
      this.currentPhase = timestamp < this.cooldownUntil ? "cooldown"
        : quietReady ? "waiting" : "rearming";
      return { phase: this.currentPhase, sequence: null, motion };
    }

    if (this.currentPhase === "waiting") {
      if (handsVisible && motion >= START_MOTION_THRESHOLD) {
        this.startCandidateAt ??= timestamp;
        this.startCandidateLastAt = timestamp;
        this.startCandidateFrames += 1;
      } else if (
        !handsVisible ||
        motion <= END_MOTION_THRESHOLD ||
        (this.startCandidateLastAt !== null &&
          timestamp - this.startCandidateLastAt > START_CANDIDATE_GAP_MS)
      ) {
        this.resetStartCandidate();
      }

      if (
        this.startCandidateAt !== null &&
        this.startCandidateFrames >= 2 &&
        timestamp - this.startCandidateAt >= START_CONFIRM_MS
      ) {
        this.currentPhase = "capturing";
        this.recording = this.preRoll.map((item) => ({
          features: Array.from(item.features),
          baselineFeatures: Array.from(item.baselineFeatures),
          timestamp: item.timestamp,
        }));
        this.preRoll = [];
        this.startedAt = this.startCandidateAt;
        this.quietStartedAt = null;
        this.missingStartedAt = null;
        this.resetStartCandidate();
      }
      return { phase: this.currentPhase, sequence: null, motion };
    }

    this.recording.push(current);
    if (this.currentPhase === "postroll") {
      if (gestureSignalVisible && motion > END_MOTION_THRESHOLD) {
        this.currentPhase = "capturing";
        this.postRollUntil = 0;
        this.quietStartedAt = null;
        this.missingStartedAt = null;
        return { phase: "capturing", sequence: null, motion, provisionalCancelled: this.dropProvisional() };
      }
      if (timestamp < this.postRollUntil) {
        return { phase: "postroll", sequence: null, motion };
      }
      return this.finish(timestamp, motion, true);
    }

    if (!gestureSignalVisible) {
      this.missingStartedAt ??= timestamp;
    } else {
      this.missingStartedAt = null;
    }
    let provisionalCancelled: number | undefined;
    if (motion <= END_MOTION_THRESHOLD) {
      this.quietStartedAt ??= timestamp;
    } else {
      this.quietStartedAt = null;
      provisionalCancelled = this.dropProvisional();
    }

    const elapsed = timestamp - this.startedAt;
    const quietFor =
      this.quietStartedAt === null ? 0 : timestamp - this.quietStartedAt;
    const missingFor =
      this.missingStartedAt === null ? 0 : timestamp - this.missingStartedAt;
    // The hard limit cannot enter resumable post-roll, otherwise continuous
    // motion could bounce between capturing/postroll forever.
    if (elapsed >= MAXIMUM_GESTURE_MS) {
      return this.finish(timestamp, motion);
    }
    const shouldFinish =
      elapsed >= MINIMUM_GESTURE_MS &&
      (quietFor >= QUIET_TO_FINISH_MS ||
        missingFor >= MISSING_SIGNAL_TO_FINISH_MS);
    if (!shouldFinish) {
      let provisional: ProvisionalSegment | undefined;
      if (
        this.speculate && !this.provisional && elapsed >= MINIMUM_GESTURE_MS &&
        quietFor >= SPECULATE_AFTER_MS
      ) {
        const segment = this.segment(this.recording);
        if (segment) {
          this.provisionalCount += 1;
          this.provisional = { id: this.provisionalCount, ...segment };
          provisional = this.provisional;
        }
      }
      return { phase: "capturing", sequence: null, motion, provisional, provisionalCancelled };
    }

    this.currentPhase = "postroll";
    this.postRollUntil = timestamp + POST_ROLL_MS;
    return { phase: "postroll", sequence: null, motion };
  }

  private resetStartCandidate(): void {
    this.startCandidateAt = null;
    this.startCandidateLastAt = null;
    this.startCandidateFrames = 0;
  }

  private dropProvisional(): number | undefined {
    const id = this.provisional?.id;
    this.provisional = null;
    return id;
  }

  private segment(frames: readonly TimedLandmarkFrame[]): Omit<ProvisionalSegment, "id"> | null {
    const usableFrames = trimMissingEdges(frames);
    const detectedFrames = usableFrames.filter((item) =>
      hasHandLandmarks(item.features),
    ).length;
    const motionScores = usableFrames.map((item, index) =>
      index === 0
        ? 0
        : normalizedMotion(usableFrames[index - 1], item),
    );
    const sampleIndices =
      detectedFrames >= MINIMUM_HAND_FRAMES
        ? motionWeightedSampleIndices(
            usableFrames.length,
            TARGET_FRAME_COUNT,
            motionScores,
          )
        : null;
    const sequence = sampleIndices
      ? sampleIndices.map((index) => usableFrames[index].features)
      : null;
    const baselineSequence = sampleIndices
      ? sampleIndices.map((index) => usableFrames[index].baselineFeatures)
      : null;
    if (!sequence || !baselineSequence || !frames.length) return null;
    return {
      sequence,
      baselineSequence,
      sourceWindow: { startAt: frames[0].timestamp, endAt: frames[frames.length - 1].timestamp },
    };
  }

  private finish(timestamp: number, motion: number, endedOnRest = false): AutomaticSegmentUpdate {
    // A rest that was already speculated on ends the sign exactly where the provisional
    // segment was cut; anything else (e.g. the length cap) cuts the full recording.
    const confirmed = endedOnRest ? this.provisional : null;
    const provisionalCancelled = confirmed ? undefined : this.dropProvisional();
    this.provisional = null;
    const segment = confirmed ?? this.segment(this.recording);
    const sequence = segment?.sequence ?? null;
    const baselineSequence = segment?.baselineSequence ?? null;
    const sourceWindow = segment?.sourceWindow ?? null;
    this.preRoll = this.recording.filter((item) => item.timestamp >= timestamp - PRE_ROLL_MS);
    this.recording = [];
    // A completed quiet/post-roll boundary already establishes the rest between signs.
    this.currentPhase = endedOnRest && sequence ? "waiting" : "cooldown";
    this.cooldownUntil = this.currentPhase === "cooldown" ? timestamp + COOLDOWN_MS : 0;
    this.readyQuietStartedAt = endedOnRest ? this.quietStartedAt : null;
    this.quietStartedAt = null;
    this.missingStartedAt = null;
    this.postRollUntil = 0;
    this.resetStartCandidate();
    return {
      phase: this.currentPhase, sequence, baselineSequence, sourceWindow, motion,
      confirmedProvisional: confirmed?.id, provisionalCancelled,
    };
  }
}
