import type { NormalizedLandmark } from "@mediapipe/tasks-vision";
import { describe, expect, it } from "vitest";
import { TrackingDisplayFilter } from "./trackingDisplay";

function hand(x: number): NormalizedLandmark[] {
  return Array.from({ length: 21 }, (_, index) => ({
    x: x + index * 0.001, y: 0.6 - index * 0.005, z: 0, visibility: 1,
  }));
}

function body(): NormalizedLandmark[] {
  const points = Array.from({ length: 33 }, () => ({ x: 0.5, y: 0.4, z: 0, visibility: 1 }));
  points[0] = { x: 0.5, y: 0.1, z: 0, visibility: 1 };
  points[11] = { x: 0.35, y: 0.4, z: 0, visibility: 1 };
  points[12] = { x: 0.65, y: 0.4, z: 0, visibility: 1 };
  return points;
}

describe("TrackingDisplayFilter", () => {
  it("reduces stationary jitter instead of copying every noisy point", () => {
    const filter = new TrackingDisplayFilter();
    filter.update([hand(0.3)], 1000);
    const positions: number[] = [];
    for (let frame = 1; frame <= 40; frame++) {
      const at = 1000 + frame * 33;
      filter.update([hand(0.3 + (frame % 2 ? 0.004 : -0.004))], at);
      positions.push(filter.read(at).hands[0].landmarks[0].x);
    }
    const rms = Math.sqrt(positions.reduce((sum, x) => sum + (x - 0.3) ** 2, 0) / positions.length);
    expect(rms).toBeLessThan(0.004 * 0.45);
  });

  it("follows a fast movement without the lag of a fixed slow filter", () => {
    const filter = new TrackingDisplayFilter();
    filter.update([hand(0.3)], 1000);
    filter.update([hand(0.6)], 1033);
    expect(filter.read(1033).hands[0].landmarks[0].x).toBeGreaterThan(0.55);
    expect(filter.read(1033).hands[0].landmarks[0].x).toBeLessThan(0.6);
  });

  it("keeps each hand's identity when the detector changes result order", () => {
    const filter = new TrackingDisplayFilter();
    filter.update([hand(0.3), hand(0.7)], 1000, { handedness: ["Left", "Right"] });
    filter.update([hand(0.7), hand(0.3)], 1033, { handedness: ["Right", "Left"] });
    expect(filter.read(1033).hands.map((item) => [item.id, item.landmarks[0].x]))
      .toEqual([[0, 0.3], [1, 0.7]]);
  });

  it("preserves identity through a crossing with consistent handedness", () => {
    const filter = new TrackingDisplayFilter();
    filter.update([hand(0.4), hand(0.6)], 1000, { handedness: ["Left", "Right"] });
    filter.update([hand(0.49), hand(0.51)], 1050, { handedness: ["Left", "Right"] });
    filter.update([hand(0.42), hand(0.58)], 1100, { handedness: ["Right", "Left"] });
    const [left, right] = filter.read(1100).hands;
    expect(left.id).toBe(0);
    expect(right.id).toBe(1);
    expect(left.landmarks[0].x).toBeGreaterThan(right.landmarks[0].x);
  });

  it("uses wrist trajectories when handedness is unavailable", () => {
    const filter = new TrackingDisplayFilter();
    filter.update([hand(0.2), hand(0.8)], 1000);
    filter.update([hand(0.35), hand(0.7)], 1050);
    filter.update([hand(0.54), hand(0.58)], 1100);
    filter.update([hand(0.46), hand(0.7)], 1150);
    const [first, second] = filter.read(1150).hands;
    expect(first.id).toBe(0);
    expect(first.landmarks[0].x).toBeGreaterThan(0.6);
    expect(second.id).toBe(1);
    expect(second.landmarks[0].x).toBeLessThan(0.55);
  });

  it("fades and expires missing hands at 150 ms without inventing new observations", () => {
    const filter = new TrackingDisplayFilter();
    filter.update([hand(0.3)], 1000);
    filter.update([], 1033);
    const fading = filter.read(1033).hands[0];
    expect(fading.held).toBe(true);
    expect(fading.opacity).toBeGreaterThan(0);
    expect(fading.opacity).toBeLessThan(1);
    expect(filter.read(1100).hands[0].opacity).toBeLessThan(fading.opacity);
    expect(filter.read(1149).hands).toHaveLength(1);
    expect(filter.read(1150).hands).toEqual([]);
  });

  it("keeps identity after a brief loss and marks a real reacquisition as observed", () => {
    const filter = new TrackingDisplayFilter();
    filter.update([hand(0.3)], 1000, { handedness: ["Left"] });
    filter.update([], 1033);
    filter.update([hand(0.35)], 1080, { handedness: ["Left"] });
    expect(filter.read(1080).hands[0]).toMatchObject({ id: 0, held: false, opacity: 1 });
  });

  it("starts a fresh filter after a long loss instead of pulling the hand to its old position", () => {
    const filter = new TrackingDisplayFilter();
    filter.update([hand(0.3)], 1000);
    filter.update([hand(0.8)], 1200);
    expect(filter.read(1200).hands[0].landmarks[0].x).toBe(0.8);
  });

  it("keeps valid pose wrists without reconstructing hand or finger landmarks", () => {
    const filter = new TrackingDisplayFilter();
    filter.update([hand(0.3)], 1000, { pose: body() });
    filter.update([], 1200, { pose: body() });
    expect(filter.read(1200).hands).toEqual([]);
    expect(filter.read(1200).pose?.landmarks).toHaveLength(33);
  });

  it("does not refresh stale pose when only a new hand frame was detected", () => {
    const filter = new TrackingDisplayFilter();
    filter.update([], 1000, { pose: body() });
    filter.update([], 1100);
    expect(filter.read(1149).pose).not.toBeNull();
    filter.update([], 1150);
    expect(filter.read(1150).pose).toBeNull();
  });

  it("preserves pose visibility rather than turning an occluded wrist into a visible one", () => {
    const filter = new TrackingDisplayFilter();
    const pose = body();
    pose[15].visibility = 0.1;
    filter.update([], 1000, { pose });
    expect(filter.read(1000).pose?.landmarks[15].visibility).toBe(0.1);
  });

  it("clears every history entry on reset", () => {
    const filter = new TrackingDisplayFilter();
    filter.update([hand(0.3)], 1000, { pose: body() });
    filter.reset();
    expect(filter.read(1033)).toEqual({ hands: [], pose: null });
    filter.update([hand(0.8)], 1033);
    expect(filter.read(1033).hands[0].landmarks[0].x).toBe(0.8);
  });

  it("never mutates detector results that recognition also consumes", () => {
    const filter = new TrackingDisplayFilter();
    const raw = Object.freeze(hand(0.3).map((point) => Object.freeze(point)));
    filter.update([raw], 1000);
    filter.update([raw], 1033);
    expect(filter.read(1033).hands[0].landmarks).not.toBe(raw);
    expect(raw[0].x).toBe(0.3);
  });

  it("does not draw incomplete or non-finite finger detections", () => {
    const filter = new TrackingDisplayFilter();
    const invalid = hand(0.3);
    invalid[8].x = Number.NaN;
    filter.update([hand(0.3).slice(0, 20), invalid], 1000);
    expect(filter.read(1000).hands).toEqual([]);
  });

  it("resets history if a detection clock restarts", () => {
    const filter = new TrackingDisplayFilter();
    filter.update([hand(0.3)], 1000);
    filter.update([hand(0.8)], 100);
    expect(filter.read(100).hands[0].landmarks[0].x).toBe(0.8);
  });

  it("uses distinct color slots when one hand is replaced", () => {
    const filter = new TrackingDisplayFilter();
    filter.update([hand(0.2), hand(0.7)], 1000);
    filter.update([hand(0.2)], 1100);
    filter.update([hand(0.2), hand(0.8)], 1160);
    expect(filter.read(1160).hands.map((item) => item.id)).toEqual([0, 1]);
  });
});
