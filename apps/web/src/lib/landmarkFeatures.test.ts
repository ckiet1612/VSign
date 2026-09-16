import { describe, expect, it } from "vitest";
import type { NormalizedLandmark } from "@mediapipe/tasks-vision";
import {
  FEATURES_PER_HAND,
  HAND_GLOBAL_OFFSET,
  HAND_PRESENCE_OFFSET,
  LANDMARK_FEATURE_DIM,
  mirrorLandmarkFrame,
  PAIR_GEOMETRY_OFFSET,
  PAIR_PRESENCE_OFFSET,
  packLandmarkFrame,
  POSE_PRESENCE_OFFSET,
} from "./landmarkFeatures";

function hand(wristX: number): NormalizedLandmark[] {
  return Array.from({ length: 21 }, (_, index) => ({
    x: index === 9 ? wristX + 0.1 : wristX,
    y: 0.65 - index / 100,
    z: index / 1000,
    visibility: 1,
  }));
}

function pose(): NormalizedLandmark[] {
  const points = Array.from({ length: 33 }, () => ({
    x: 0.5,
    y: 0.4,
    z: 0,
    visibility: 1,
  }));
  points[0] = { x: 0.5, y: 0.15, z: 0, visibility: 1 };
  points[11] = { x: 0.3, y: 0.4, z: 0, visibility: 1 };
  points[12] = { x: 0.7, y: 0.4, z: 0, visibility: 1 };
  points[15] = { x: 0.2, y: 0.65, z: 0, visibility: 1 };
  points[16] = { x: 0.8, y: 0.65, z: 0, visibility: 1 };
  return points;
}

describe("packLandmarkFrame V4", () => {
  it("ghép tay theo cổ tay pose và chuẩn hóa theo vai", () => {
    const packed = packLandmarkFrame([hand(0.79), hand(0.21)], pose());
    expect(packed).not.toBeNull();
    expect(packed).toHaveLength(LANDMARK_FEATURE_DIM);
    expect(packed?.[HAND_GLOBAL_OFFSET]).toBeCloseTo(-0.725, 2);
    expect(packed?.[HAND_GLOBAL_OFFSET + 3]).toBeCloseTo(0.725, 2);
    expect(packed?.slice(HAND_PRESENCE_OFFSET, POSE_PRESENCE_OFFSET)).toEqual([1, 1]);
    expect(packed?.[PAIR_PRESENCE_OFFSET]).toBe(1);
    expect(packed?.[PAIR_GEOMETRY_OFFSET]).toBeCloseTo(1.45, 1);
    expect(packed?.[PAIR_GEOMETRY_OFFSET + 3]).toBeGreaterThan(1.4);
  });

  it("giữ pose và mask thay vì tạo tay giả khi bị che", () => {
    const packed = packLandmarkFrame([], pose());
    expect(packed).not.toBeNull();
    expect(packed?.slice(HAND_PRESENCE_OFFSET, POSE_PRESENCE_OFFSET)).toEqual([0, 0]);
    expect(packed?.[POSE_PRESENCE_OFFSET + 10]).toBe(1);
    expect(packed?.[PAIR_PRESENCE_OFFSET]).toBe(1);
  });

  it("bỏ qua tay không đủ 21 điểm", () => {
    const packed = packLandmarkFrame([hand(0.2).slice(0, 20)], null);
    expect(packed).toBeNull();
  });

  it("không tạo pose giả ở sát đáy khung", () => {
    const invalid = pose();
    invalid[0].y = 0.95;
    invalid[11].y = 0.94;
    invalid[12].y = 0.94;
    expect(packLandmarkFrame([], invalid)).toBeNull();
  });

  it("lật V4 hai lần trả lại đúng đặc trưng", () => {
    const packed = packLandmarkFrame([hand(0.21), hand(0.79)], pose());
    expect(packed).not.toBeNull();
    const mirroredTwice = mirrorLandmarkFrame(mirrorLandmarkFrame(packed!));
    expect(mirroredTwice).toHaveLength(LANDMARK_FEATURE_DIM);
    mirroredTwice.forEach((value, index) => expect(value).toBeCloseTo(packed![index]));
    expect(FEATURES_PER_HAND).toBe(63);
  });
});
