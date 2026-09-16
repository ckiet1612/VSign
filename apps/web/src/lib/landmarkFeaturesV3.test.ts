import { describe, expect, it } from "vitest";
import type { NormalizedLandmark } from "@mediapipe/tasks-vision";
import {
  BASELINE_FEATURE_DIM,
  BASELINE_HAND_PRESENCE_OFFSET,
  mirrorBaselineLandmarkFrame,
  packBaselineLandmarkFrame,
} from "./landmarkFeaturesV3";

function hand(wristX: number): NormalizedLandmark[] {
  return Array.from({ length: 21 }, (_, index) => ({
    x: wristX + index * 0.001,
    y: 0.3 + index * 0.002,
    z: -index * 0.001,
    visibility: 1,
  }));
}

describe("V3 baseline landmark features", () => {
  it("đóng gói hai tay theo thứ tự trái-phải giống Python", () => {
    const packed = packBaselineLandmarkFrame([hand(0.8), hand(0.2)]);
    expect(packed).toHaveLength(BASELINE_FEATURE_DIM);
    expect(packed?.[0]).toBeCloseTo(0.2);
    expect(packed?.[63]).toBeCloseTo(0.8);
    expect(packed?.slice(BASELINE_HAND_PRESENCE_OFFSET)).toEqual([1, 1]);
  });

  it("lật ảnh và đổi slot khi có đủ hai tay", () => {
    const packed = packBaselineLandmarkFrame([hand(0.2), hand(0.8)])!;
    const mirrored = mirrorBaselineLandmarkFrame(packed);
    expect(mirrored[0]).toBeCloseTo(0.2);
    expect(mirrored[63]).toBeCloseTo(0.8);
    expect(mirrored.slice(BASELINE_HAND_PRESENCE_OFFSET)).toEqual([1, 1]);
  });
});
