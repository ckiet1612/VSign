import {
  emptyLandmarkFrame,
  HAND_GLOBAL_OFFSET,
  LANDMARK_FEATURE_DIM,
  mirrorLandmarkFrame,
} from "./landmarkFeatures";
import {
  BASELINE_FEATURE_DIM,
  hasBaselineHandLandmarks,
  mirrorBaselineLandmarkFrame,
} from "./landmarkFeaturesV3";

export const V5_CONTEXT_SOURCE_OFFSET = HAND_GLOBAL_OFFSET;
export const V5_CONTEXT_DIM = LANDMARK_FEATURE_DIM - V5_CONTEXT_SOURCE_OFFSET;
export const V5_CONTEXT_OFFSET = BASELINE_FEATURE_DIM;
export const V5_FEATURE_DIM = BASELINE_FEATURE_DIM + V5_CONTEXT_DIM;

/** Join the exact V3 hand frame with the body-context suffix of V4. */
export function combineV5LandmarkFrame(
  baseline: readonly number[],
  contextual: readonly number[],
): number[] {
  if (baseline.length !== BASELINE_FEATURE_DIM) {
    throw new Error(`Frame V3 phải có ${BASELINE_FEATURE_DIM} đặc trưng.`);
  }
  if (contextual.length !== LANDMARK_FEATURE_DIM) {
    throw new Error(`Frame V4 phải có ${LANDMARK_FEATURE_DIM} đặc trưng.`);
  }
  return [
    ...baseline,
    ...contextual.slice(V5_CONTEXT_SOURCE_OFFSET),
  ];
}

export function combineV5LandmarkSequence(
  baselineFrames: readonly (readonly number[])[],
  contextualFrames: readonly (readonly number[])[],
): number[][] {
  if (baselineFrames.length !== contextualFrames.length) {
    throw new Error("Chuỗi V3 và V4 phải có cùng số frame.");
  }
  return baselineFrames.map((baseline, index) =>
    combineV5LandmarkFrame(baseline, contextualFrames[index]),
  );
}

/** Mirror each source block with the same contract used during training. */
export function mirrorV5LandmarkFrame(frame: readonly number[]): number[] {
  if (frame.length !== V5_FEATURE_DIM) {
    throw new Error(`Frame phải có ${V5_FEATURE_DIM} đặc trưng V5.`);
  }
  const baseline = frame.slice(0, BASELINE_FEATURE_DIM);
  const contextual = emptyLandmarkFrame();
  contextual.splice(
    V5_CONTEXT_SOURCE_OFFSET,
    V5_CONTEXT_DIM,
    ...frame.slice(V5_CONTEXT_OFFSET),
  );
  const mirroredContext = mirrorLandmarkFrame(contextual);
  return [
    ...mirrorBaselineLandmarkFrame(baseline),
    ...mirroredContext.slice(V5_CONTEXT_SOURCE_OFFSET),
  ];
}

export function v5InferenceViews(
  frames: readonly (readonly number[])[],
): number[][][] {
  return [
    frames.map((frame) => Array.from(frame)),
    frames.map(mirrorV5LandmarkFrame),
  ];
}

export function hasV5HandLandmarks(frame: readonly number[]): boolean {
  return (
    frame.length === V5_FEATURE_DIM &&
    hasBaselineHandLandmarks(frame.slice(0, BASELINE_FEATURE_DIM))
  );
}
