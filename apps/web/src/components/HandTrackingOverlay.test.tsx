import { act, render, screen, waitFor } from "@testing-library/react";
import type { NormalizedLandmark } from "@mediapipe/tasks-vision";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HandTrackingOverlay } from "./HandTrackingOverlay";
import { HAND_PRESENCE_OFFSET, POSE_COORDINATE_OFFSET } from "../lib/landmarkFeatures";
import { calculateAdaptiveFraming, smoothCropRegion } from "../lib/adaptiveFraming";

const detector = vi.hoisted(() => ({
  hands: [] as NormalizedLandmark[][],
  pose: [] as NormalizedLandmark[],
  fail: false,
  onDetect: null as (() => void) | null,
}));

vi.mock("@mediapipe/tasks-vision", () => {
  class HandLandmarker {
    static HAND_CONNECTIONS = [{ start: 0, end: 1 }];
    static async createFromOptions() { return new HandLandmarker(); }
    detectForVideo() {
      if (detector.fail) throw new Error("Detector failed");
      detector.onDetect?.();
      return {
        landmarks: detector.hands,
        worldLandmarks: [],
        handedness: detector.hands.map(() => [{ categoryName: "Left", score: 0.99 }]),
        handednesses: [],
      };
    }
    close() {}
  }
  class PoseLandmarker {
    static async createFromOptions() { return new PoseLandmarker(); }
    detect() { return { landmarks: detector.pose.length ? [detector.pose] : [], worldLandmarks: [] }; }
    close() {}
  }
  return {
    FilesetResolver: { forVisionTasks: async () => ({}) },
    HandLandmarker,
    PoseLandmarker,
  };
});

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

describe("HandTrackingOverlay display isolation", () => {
  let now: number;
  let nextCallback: number;
  let animationCallbacks: Map<number, FrameRequestCallback>;
  let videoCallbacks: Map<number, VideoFrameRequestCallback>;
  let dots: { x: number; radius: number; opacity: number }[];
  let context: Record<string, unknown>;
  let video: HTMLVideoElement;

  beforeEach(() => {
    now = 1000;
    nextCallback = 0;
    animationCallbacks = new Map();
    videoCallbacks = new Map();
    dots = [];
    detector.hands = [hand(0.3)];
    detector.pose = body();
    detector.fail = false;
    detector.onDetect = null;
    vi.spyOn(performance, "now").mockImplementation(() => now);
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      animationCallbacks.set(++nextCallback, callback);
      return nextCallback;
    });
    vi.stubGlobal("cancelAnimationFrame", (id: number) => animationCallbacks.delete(id));
    context = {
      globalAlpha: 1,
      setTransform: vi.fn(),
      clearRect: () => { dots = []; },
      save: vi.fn(), restore: vi.fn(), beginPath: vi.fn(),
      moveTo: vi.fn(), lineTo: vi.fn(), quadraticCurveTo: vi.fn(),
      stroke: vi.fn(), fill: vi.fn(), setLineDash: vi.fn(), strokeRect: vi.fn(),
      arc: (x: number, _y: number, radius: number) => {
        dots.push({ x, radius, opacity: Number(context.globalAlpha) });
      },
    };
    vi.spyOn(HTMLCanvasElement.prototype, "getContext")
      .mockReturnValue(context as unknown as CanvasRenderingContext2D);
    vi.spyOn(HTMLCanvasElement.prototype, "getBoundingClientRect")
      .mockReturnValue({ x: 0, y: 0, left: 0, top: 0, right: 640, bottom: 360, width: 640, height: 360, toJSON: () => ({}) });
    video = document.createElement("video");
    Object.defineProperties(video, {
      readyState: { value: 4 }, videoWidth: { value: 640 }, videoHeight: { value: 360 },
    });
    video.requestVideoFrameCallback = (callback) => {
      videoCallbacks.set(++nextCallback, callback);
      return nextCallback;
    };
    video.cancelVideoFrameCallback = (id) => { videoCallbacks.delete(id); };
  });

  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  async function open(framingMode: "fixed" | "adaptive" = "fixed") {
    const onTrackingFrame = vi.fn();
    const props = { videoRef: { current: video }, active: true, framingMode, onTrackingFrame };
    const view = render(<HandTrackingOverlay {...props} />);
    await screen.findByText(/Đưa tay vào/);
    await waitFor(() => expect(animationCallbacks.size).toBeGreaterThan(0));
    return { ...view, props, onTrackingFrame };
  }

  function advance(timestamp: number, detect = true) {
    act(() => {
      now = timestamp;
      if (detect) {
        video.currentTime += 0.033;
        const callbacks = [...videoCallbacks.values()];
        videoCallbacks.clear();
        callbacks.forEach((callback) => callback(timestamp, {} as VideoFrameCallbackMetadata));
      }
      const callbacks = [...animationCallbacks.values()];
      animationCallbacks.clear();
      callbacks.forEach((callback) => callback(now));
    });
  }

  const handDots = () => dots.filter((dot) => dot.radius === 3.7);

  it("smooths the drawing without smoothing recognition features", async () => {
    const { onTrackingFrame } = await open();
    advance(1000);
    detector.hands = [hand(0.304)];
    advance(1033);
    expect(handDots()[0].x).toBeGreaterThan((1 - 0.304) * 640);
    expect(handDots()[0].x).toBeLessThan((1 - 0.3) * 640);
    const raw = onTrackingFrame.mock.lastCall![0];
    expect(raw.baselineFeatures[0]).toBe(0.304);
    expect(raw.handCount).toBe(1);
    expect(raw.updatedAt).toBe(1033);
    expect(raw.crop).toBeNull();
  });

  it("fades a briefly missing hand but emits raw absence and expires without new video frames", async () => {
    const { onTrackingFrame } = await open();
    advance(1000);
    detector.hands = [];
    advance(1033);
    expect(handDots().length).toBeGreaterThan(0);
    expect(handDots()[0].opacity).toBeLessThan(1);
    expect(onTrackingFrame.mock.lastCall![0].handCount).toBe(0);
    expect(onTrackingFrame.mock.lastCall![0].baselineFeatures).toBeNull();
    expect(onTrackingFrame.mock.lastCall![0].features.slice(HAND_PRESENCE_OFFSET, HAND_PRESENCE_OFFSET + 2))
      .toEqual([0, 0]);
    advance(1149, false);
    expect(handDots().length).toBeGreaterThan(0);
    advance(1150, false);
    expect(handDots()).toEqual([]);
  });

  it("smooths the body drawing but preserves original shoulder-relative pose features", async () => {
    const { onTrackingFrame } = await open();
    advance(1000);
    detector.pose[0].x = 0.506;
    advance(1066);
    const nose = dots.find((dot) => dot.radius === 2.7)!;
    expect(nose.x).toBeGreaterThan((1 - 0.506) * 640);
    expect(nose.x).toBeLessThan(320);
    expect(onTrackingFrame.mock.lastCall![0].features[POSE_COORDINATE_OFFSET]).toBeCloseTo(0.02);
  });

  it("preserves the existing adaptive crop calculation independently of display smoothing", async () => {
    const { onTrackingFrame } = await open("adaptive");
    const initialCrop = calculateAdaptiveFraming(detector.hands, 640, 360)!.crop;
    advance(1000);
    detector.hands = [hand(0.304)];
    const nextCrop = calculateAdaptiveFraming(detector.hands, 640, 360)!.crop;
    advance(1033);
    expect(onTrackingFrame.mock.lastCall![0].crop).toEqual(smoothCropRegion(initialCrop, nextCrop));
    expect(onTrackingFrame.mock.lastCall![0].baselineFeatures[0]).toBe(0.304);
    expect(handDots()[0].x).toBeGreaterThan((1 - 0.304) * 640);
  });

  it("expires held points with the animation-frame fallback when video callbacks are unavailable", async () => {
    Object.defineProperty(video, "requestVideoFrameCallback", { value: undefined });
    const { onTrackingFrame } = await open();
    advance(1000);
    expect(handDots().length).toBeGreaterThan(0);
    detector.hands = [];
    advance(1033);
    expect(handDots()[0].opacity).toBeLessThan(1);
    expect(onTrackingFrame.mock.lastCall![0].handCount).toBe(0);
    advance(1150, false);
    expect(handDots()).toEqual([]);
    expect(videoCallbacks.size).toBe(0);
  });

  it("cancels both render and detector callbacks when the overlay unmounts", async () => {
    const { unmount } = await open();
    advance(1000);
    expect(animationCallbacks.size).toBe(1);
    expect(videoCallbacks.size).toBe(1);
    unmount();
    expect(animationCallbacks.size).toBe(0);
    expect(videoCallbacks.size).toBe(0);
  });

  it("clears held points and callbacks when the camera is turned off", async () => {
    const { rerender, props, onTrackingFrame } = await open();
    advance(1000);
    rerender(<HandTrackingOverlay {...props} active={false} />);
    expect(animationCallbacks.size).toBe(0);
    expect(videoCallbacks.size).toBe(0);
    expect(onTrackingFrame.mock.lastCall![0]).toMatchObject({ handCount: 0, features: null, baselineFeatures: null });
    detector.hands = [];
    rerender(<HandTrackingOverlay {...props} />);
    advance(1033);
    expect(handDots()).toEqual([]);
  });

  it("clears the overlay on detector failure instead of leaving frozen hands", async () => {
    const { onTrackingFrame } = await open();
    advance(1000);
    detector.fail = true;
    advance(1033);
    expect(handDots()).toEqual([]);
    expect(onTrackingFrame.mock.lastCall![0]).toMatchObject({ handCount: 0, features: null, baselineFeatures: null });
    expect(screen.getByText("Tracking cơ thể chưa sẵn sàng")).toBeInTheDocument();
  });

  it("renders a fresh result after slow detection without changing the capture timestamp", async () => {
    const { onTrackingFrame } = await open();
    detector.onDetect = () => { now += 200; };
    advance(1000);
    expect(handDots().length).toBeGreaterThan(0);
    expect(onTrackingFrame.mock.lastCall![0].updatedAt).toBe(1000);
  });
});
