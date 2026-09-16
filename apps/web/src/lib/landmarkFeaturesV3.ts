import type { NormalizedLandmark } from "@mediapipe/tasks-vision";
import { LANDMARK_SEQUENCE_LENGTH } from "./landmarkFeatures";

export { LANDMARK_SEQUENCE_LENGTH };
export const BASELINE_MAX_HANDS = 2;
export const BASELINE_LANDMARKS_PER_HAND = 21;
export const BASELINE_FEATURES_PER_HAND = BASELINE_LANDMARKS_PER_HAND * 3;
export const BASELINE_HAND_PRESENCE_OFFSET =
  BASELINE_MAX_HANDS * BASELINE_FEATURES_PER_HAND;
export const BASELINE_FEATURE_DIM =
  BASELINE_HAND_PRESENCE_OFFSET + BASELINE_MAX_HANDS;

/** Exact browser implementation of ml.landmarks_v2.pack_landmarks. */
export function packBaselineLandmarkFrame(
  hands: readonly (readonly NormalizedLandmark[])[],
): number[] | null {
  const valid = hands
    .filter((hand) => hand.length === BASELINE_LANDMARKS_PER_HAND)
    .slice(0, BASELINE_MAX_HANDS)
    .sort((left, right) => left[0].x - right[0].x);
  if (!valid.length) return null;

  const packed = emptyBaselineLandmarkFrame();
  valid.forEach((hand, handIndex) => {
    hand.forEach((point, pointIndex) => {
      const offset = handIndex * BASELINE_FEATURES_PER_HAND + pointIndex * 3;
      packed[offset] = point.x;
      packed[offset + 1] = point.y;
      packed[offset + 2] = point.z;
    });
    packed[BASELINE_HAND_PRESENCE_OFFSET + handIndex] = 1;
  });
  return packed;
}

export function emptyBaselineLandmarkFrame(): number[] {
  return new Array<number>(BASELINE_FEATURE_DIM).fill(0);
}

export function hasBaselineHandLandmarks(frame: readonly number[]): boolean {
  return (
    frame.length === BASELINE_FEATURE_DIM &&
    (frame[BASELINE_HAND_PRESENCE_OFFSET] > 0.5 ||
      frame[BASELINE_HAND_PRESENCE_OFFSET + 1] > 0.5)
  );
}

/** Exact browser implementation of ml.landmarks_v2.mirror_sequence. */
export function mirrorBaselineLandmarkFrame(
  frame: readonly number[],
): number[] {
  if (frame.length !== BASELINE_FEATURE_DIM) {
    throw new Error(`Frame phải có ${BASELINE_FEATURE_DIM} đặc trưng V3.`);
  }
  const output = Array.from(frame);
  for (let hand = 0; hand < BASELINE_MAX_HANDS; hand += 1) {
    for (let point = 0; point < BASELINE_LANDMARKS_PER_HAND; point += 1) {
      const offset = hand * BASELINE_FEATURES_PER_HAND + point * 3;
      output[offset] = 1 - output[offset];
    }
  }
  if (
    output[BASELINE_HAND_PRESENCE_OFFSET] > 0.5 &&
    output[BASELINE_HAND_PRESENCE_OFFSET + 1] > 0.5
  ) {
    const left = output.slice(0, BASELINE_FEATURES_PER_HAND);
    const right = output.slice(
      BASELINE_FEATURES_PER_HAND,
      BASELINE_HAND_PRESENCE_OFFSET,
    );
    output.splice(0, BASELINE_FEATURES_PER_HAND, ...right);
    output.splice(
      BASELINE_FEATURES_PER_HAND,
      BASELINE_FEATURES_PER_HAND,
      ...left,
    );
  }
  return output;
}

export function baselineInferenceViews(
  frames: readonly (readonly number[])[],
): number[][][] {
  return [
    frames.map((frame) => Array.from(frame)),
    frames.map(mirrorBaselineLandmarkFrame),
  ];
}
