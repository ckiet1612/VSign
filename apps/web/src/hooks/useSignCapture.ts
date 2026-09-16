import { type RefObject, useCallback, useEffect, useRef, useState } from "react";
import type { NormalizedCropRegion } from "../lib/adaptiveFraming";
import {
  emptyLandmarkFrame,
  LANDMARK_FEATURE_DIM,
} from "../lib/landmarkFeatures";
import {
  BASELINE_FEATURE_DIM,
  emptyBaselineLandmarkFrame,
} from "../lib/landmarkFeaturesV3";
import { encodeFrames, type CapturedBitmap } from "../lib/frameEncoder";
import { landmarkMotion } from "../lib/autoSegmentation";
import {
  MAX_CAPTURED_BITMAPS,
  MAX_CAPTURE_MS,
  motionWeightedSampleIndices,
  TARGET_FRAME_COUNT,
  validateCaptureDuration,
} from "../lib/sampling";

export type CaptureStatus = "idle" | "capturing" | "encoding";

interface SignCaptureOptions {
  videoRef: RefObject<HTMLVideoElement | null>;
  canStart: boolean;
  encodeVideoFrames?: boolean;
  preserveSourceFrames?: boolean;
  getCropRegion?: () => NormalizedCropRegion | null;
  getLandmarkFeatures?: () => readonly number[] | null;
  getBaselineLandmarkFeatures?: () => readonly number[] | null;
  onCaptureStart: () => void;
  onCaptureCancel: () => void;
  onTooShort: (message: string) => void;
  onFrames: (capture: CapturedFrames) => void;
  onError: (message: string) => void;
}

export interface CapturedFrames {
  frames: string[];
  sourceFrames: string[] | null;
  landmarkFrames: number[][];
  baselineLandmarkFrames: number[][];
  durationMs: number;
}

export interface SignCaptureController {
  status: CaptureStatus;
  start: () => void;
  stop: () => void;
  cancel: () => void;
}

export function useSignCapture({
  videoRef,
  canStart,
  encodeVideoFrames = true,
  preserveSourceFrames = false,
  getCropRegion,
  getLandmarkFeatures,
  getBaselineLandmarkFeatures,
  onCaptureStart,
  onCaptureCancel,
  onTooShort,
  onFrames,
  onError,
}: SignCaptureOptions): SignCaptureController {
  const [status, setStatus] = useState<CaptureStatus>("idle");
  const activeRef = useRef(false);
  const startAtRef = useRef(0);
  const bitmapsRef = useRef<CapturedBitmap[]>([]);
  const frameInFlightRef = useRef(false);
  const intervalRef = useRef<number | undefined>(undefined);
  const timeoutRef = useRef<number | undefined>(undefined);

  const clearTimers = useCallback(() => {
    if (intervalRef.current !== undefined) window.clearInterval(intervalRef.current);
    if (timeoutRef.current !== undefined) window.clearTimeout(timeoutRef.current);
    intervalRef.current = undefined;
    timeoutRef.current = undefined;
  }, []);

  const closeBufferedFrames = useCallback(() => {
    for (const frame of bitmapsRef.current) frame.bitmap.close();
    bitmapsRef.current = [];
  }, []);

  const captureFrame = useCallback(async () => {
    const video = videoRef.current;
    if (
      !activeRef.current ||
      frameInFlightRef.current ||
      !video ||
      video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA
    ) {
      return;
    }
    frameInFlightRef.current = true;
    try {
      const bitmap = await createImageBitmap(video);
      if (!activeRef.current || bitmapsRef.current.length >= MAX_CAPTURED_BITMAPS) {
        bitmap.close();
      } else {
        bitmapsRef.current.push({
          bitmap,
          crop: getCropRegion?.() ?? null,
          landmarks: getLandmarkFeatures?.() ?? null,
          baselineLandmarks: getBaselineLandmarkFeatures?.() ?? null,
        });
      }
    } catch {
      // A single missed camera frame is harmless; final validation handles an empty clip.
    } finally {
      frameInFlightRef.current = false;
    }
  }, [getBaselineLandmarkFeatures, getCropRegion, getLandmarkFeatures, videoRef]);

  const finish = useCallback(async () => {
    if (!activeRef.current) return;
    activeRef.current = false;
    clearTimers();
    const duration = performance.now() - startAtRef.current;
    const validation = validateCaptureDuration(duration);
    if (!validation.valid) {
      closeBufferedFrames();
      setStatus("idle");
      onTooShort(validation.message ?? "Clip chưa hợp lệ.");
      return;
    }
    if (!bitmapsRef.current.length) {
      setStatus("idle");
      onError("Không thu được hình từ camera. Hãy kiểm tra camera và thử lại.");
      return;
    }

    setStatus("encoding");
    const source = bitmapsRef.current;
    bitmapsRef.current = [];
    const sourceLandmarks = source.map((frame) => {
      const landmarks = frame.landmarks;
      return landmarks?.length === LANDMARK_FEATURE_DIM
        ? Array.from(landmarks)
        : emptyLandmarkFrame();
    });
    const sourceBaselineLandmarks = source.map((frame) => {
      const landmarks = frame.baselineLandmarks;
      return landmarks?.length === BASELINE_FEATURE_DIM
        ? Array.from(landmarks)
        : emptyBaselineLandmarkFrame();
    });
    const motionScores = sourceLandmarks.map((frame, index) =>
      index === 0 ? 0 : landmarkMotion(sourceLandmarks[index - 1], frame),
    );
    const samplePlan = motionWeightedSampleIndices(
      source.length,
      TARGET_FRAME_COUNT,
      motionScores,
    );
    const landmarkFrames = samplePlan.map(
      (sourceIndex) => sourceLandmarks[sourceIndex],
    );
    const baselineLandmarkFrames = samplePlan.map(
      (sourceIndex) => sourceBaselineLandmarks[sourceIndex],
    );
    const uniqueIndices = [...new Set(samplePlan)];
    const selected = uniqueIndices.map((index) => source[index]);
    if (!preserveSourceFrames) {
      const selectedSet = new Set(selected);
      for (const frame of source) {
        if (!selectedSet.has(frame)) frame.bitmap.close();
      }
    }
    try {
      let sampled: string[] = [];
      let sourceFrames: string[] | null = null;
      if (encodeVideoFrames) {
        if (preserveSourceFrames) {
          sourceFrames = await encodeFrames(source);
          sampled = samplePlan.map((sourceIndex) => sourceFrames![sourceIndex]);
        } else {
          const uniqueEncoded = await encodeFrames(selected);
          const encodedByIndex = new Map(
            uniqueIndices.map((sourceIndex, resultIndex) => [
              sourceIndex,
              uniqueEncoded[resultIndex],
            ]),
          );
          sampled = samplePlan.map((sourceIndex) => {
            const frame = encodedByIndex.get(sourceIndex);
            if (!frame) throw new Error("Thiếu frame sau khi encode.");
            return frame;
          });
        }
      } else {
        for (const frame of preserveSourceFrames ? source : selected) {
          frame.bitmap.close();
        }
      }
      onFrames({
        frames: sampled,
        sourceFrames,
        landmarkFrames,
        baselineLandmarkFrames,
        durationMs: Math.round(duration),
      });
    } catch (error) {
      onError(error instanceof Error ? error.message : "Không thể xử lý frame camera.");
    } finally {
      setStatus("idle");
    }
  }, [
    clearTimers,
    closeBufferedFrames,
    encodeVideoFrames,
    onError,
    onFrames,
    onTooShort,
    preserveSourceFrames,
  ]);

  const start = useCallback(() => {
    if (!canStart || activeRef.current || status !== "idle") return;
    closeBufferedFrames();
    activeRef.current = true;
    startAtRef.current = performance.now();
    setStatus("capturing");
    onCaptureStart();
    void captureFrame();
    intervalRef.current = window.setInterval(() => void captureFrame(), 75);
    timeoutRef.current = window.setTimeout(() => void finish(), MAX_CAPTURE_MS);
  }, [canStart, captureFrame, closeBufferedFrames, finish, onCaptureStart, status]);

  const cancel = useCallback(() => {
    if (!activeRef.current) return;
    activeRef.current = false;
    clearTimers();
    closeBufferedFrames();
    setStatus("idle");
    onCaptureCancel();
  }, [clearTimers, closeBufferedFrames, onCaptureCancel]);

  useEffect(
    () => () => {
      activeRef.current = false;
      clearTimers();
      closeBufferedFrames();
    },
    [clearTimers, closeBufferedFrames],
  );

  return { status, start, stop: () => void finish(), cancel };
}
