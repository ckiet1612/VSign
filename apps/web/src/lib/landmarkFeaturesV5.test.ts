import { describe, expect, it } from "vitest";
import { LANDMARK_FEATURE_DIM } from "./landmarkFeatures";
import { BASELINE_FEATURE_DIM } from "./landmarkFeaturesV3";
import {
  combineV5LandmarkFrame,
  hasV5HandLandmarks,
  mirrorV5LandmarkFrame,
  V5_CONTEXT_DIM,
  V5_FEATURE_DIM,
} from "./landmarkFeaturesV5";

describe("landmarkFeaturesV5", () => {
  it("keeps the exact V3 block and appends only compact context", () => {
    const baseline = Array.from({ length: BASELINE_FEATURE_DIM }, (_, index) => index);
    const contextual = Array.from({ length: LANDMARK_FEATURE_DIM }, (_, index) => 1000 + index);
    const combined = combineV5LandmarkFrame(baseline, contextual);
    expect(combined).toHaveLength(V5_FEATURE_DIM);
    expect(combined.slice(0, BASELINE_FEATURE_DIM)).toEqual(baseline);
    expect(combined.slice(BASELINE_FEATURE_DIM)).toHaveLength(V5_CONTEXT_DIM);
    expect(combined.at(-1)).toBe(contextual.at(-1));
  });

  it("returns to the same values after two mirrors", () => {
    const baseline = new Array<number>(BASELINE_FEATURE_DIM).fill(0);
    const contextual = new Array<number>(LANDMARK_FEATURE_DIM).fill(0);
    for (let hand = 0; hand < 2; hand += 1) {
      const offset = hand * 63;
      baseline[offset] = 0.2 + hand * 0.5;
      baseline[offset + 1] = 0.4;
      baseline[BASELINE_FEATURE_DIM - 2 + hand] = 1;
    }
    contextual.fill(0.25, 126, 170);
    contextual.fill(1, 170);
    const combined = combineV5LandmarkFrame(baseline, contextual);
    const twice = mirrorV5LandmarkFrame(mirrorV5LandmarkFrame(combined));
    twice.forEach((value, index) => expect(value).toBeCloseTo(combined[index], 12));
    expect(hasV5HandLandmarks(combined)).toBe(true);
  });
});
