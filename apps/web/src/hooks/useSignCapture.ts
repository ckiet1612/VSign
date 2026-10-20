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
import {
  createStreamingEncoder,
  encodeFrames,
  type CapturedBitmap,
  type StreamingFrameEncoder,
} from "../lib/frameEncoder";
import {
  centerSquareBox,
  drawBoxed,
  trimSpan,
  type FramingFrame,
} from "../lib/bodyFraming";
import { landmarkMotion } from "../lib/autoSegmentation";
import {
  captureSampleIndices,
  type CaptureSamplingStrategy,
  MAX_CAPTURED_BITMAPS,
  MAX_CAPTURE_MS,
  TARGET_FRAME_COUNT,
  validateCaptureDuration,
} from "../lib/sampling";

export type CaptureStatus = "idle" | "capturing" | "encoding";

interface TimedCapture extends Omit<CapturedBitmap, "bitmap"> {
  /** Full camera frame, kept only when frames are encoded after capture. */
  bitmap: ImageBitmap | null;
  /** Streamed 224 px frame, already encoding while the user signs. */
  encoded?: Promise<string>;
  timestamp: number;
  framing?: FramingFrame | null;
}

interface LockedFraming {
  width: number;
  height: number;
  box: NormalizedCropRegion;
}

const STREAM_SIZE = 224;
const MIN_FRAMED_FRAMES = 4;

/** trim-bodycrop-v1: keep only the raised-hand span of the clip. */
function trimToSigning(source: TimedCapture[], width: number, height: number): TimedCapture[] {
  if (!width || !height || !source.length || source.some((frame) => !frame.framing)) return source;
  const observations = source.map((frame) => ({ ...frame.framing!, t: frame.timestamp }));
  const [start, end] = trimSpan(observations, width, height);
  return end - start + 1 >= MIN_FRAMED_FRAMES ? source.slice(start, end + 1) : source;
}

interface SignCaptureOptions {
  videoRef: RefObject<HTMLVideoElement | null>;
  canStart: boolean;
  captureContextKey?: string;
  encodeVideoFrames?: boolean;
  preserveSourceFrames?: boolean;
  samplingStrategy?: CaptureSamplingStrategy;
  getCropRegion?: () => NormalizedCropRegion | null;
  /**
   * Crop to 224 px and encode each frame as it is captured instead of after
   * the sign. The crop is locked when capture starts.
   */
  streamFrames?: boolean;
  /** Trim to the signing span and crop around the signer (trim-bodycrop-v1, streamed). */
  bodyFraming?: boolean;
  getFramingFrame?: () => FramingFrame | null;
  /** Live body box over the latest pose detections, locked at capture start. */
  getBodyBox?: (width: number, height: number) => NormalizedCropRegion | null;
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
  captureContextKey = "default",
  encodeVideoFrames = true,
  preserveSourceFrames = false,
  samplingStrategy = "motion-weighted",
  getCropRegion,
  streamFrames = false,
  bodyFraming = false,
  getFramingFrame,
  getBodyBox,
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
  const inProgressRef = useRef(false);
  const captureGenerationRef = useRef(0);
  const startAtRef = useRef(0);
  const bitmapsRef = useRef<TimedCapture[]>([]);
  const frameInFlightRef = useRef(false);
  const intervalRef = useRef<number | undefined>(undefined);
  const timeoutRef = useRef<number | undefined>(undefined);
  const captureContextKeyRef = useRef(captureContextKey);
  const encoderRef = useRef<StreamingFrameEncoder | null>(null);
  const streamCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const lockedFramingRef = useRef<LockedFraming | null>(null);
  const framed = streamFrames && bodyFraming;

  const clearTimers = useCallback(() => {
    if (intervalRef.current !== undefined) window.clearInterval(intervalRef.current);
    if (timeoutRef.current !== undefined) window.clearTimeout(timeoutRef.current);
    intervalRef.current = undefined;
    timeoutRef.current = undefined;
  }, []);

  const closeBufferedFrames = useCallback(() => {
    for (const frame of bitmapsRef.current) frame.bitmap?.close();
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
    const generation = captureGenerationRef.current;
    frameInFlightRef.current = true;
    try {
      if (streamFrames) {
        const width = video.videoWidth;
        const height = video.videoHeight;
        if (!width || !height) return;
        // One box per clip, as in training; the pose before signing is the steadiest.
        lockedFramingRef.current ??= {
          width, height,
          box: (framed ? getBodyBox?.(width, height) : null) ?? centerSquareBox(width, height),
        };
        const locked = lockedFramingRef.current;
        if (locked.width !== width || locked.height !== height) return;
        const canvas = streamCanvasRef.current ?? document.createElement("canvas");
        streamCanvasRef.current = canvas;
        canvas.width = STREAM_SIZE;
        canvas.height = STREAM_SIZE;
        const context = canvas.getContext("2d", { alpha: false });
        if (!context) return;
        drawBoxed(context, video, width, height, locked.box, STREAM_SIZE, framed ? "high" : undefined);
        const bitmap = await createImageBitmap(canvas);
        if (
          !activeRef.current ||
          generation !== captureGenerationRef.current ||
          bitmapsRef.current.length >= MAX_CAPTURED_BITMAPS
        ) {
          bitmap.close();
          return;
        }
        encoderRef.current ??= createStreamingEncoder();
        const encoded = encoderRef.current.encode({ bitmap, crop: null });
        encoded.catch(() => undefined);
        bitmapsRef.current.push({
          bitmap: null,
          encoded,
          timestamp: performance.now(),
          framing: framed ? getFramingFrame?.() ?? null : null,
          crop: null,
          landmarks: getLandmarkFeatures?.() ?? null,
          baselineLandmarks: getBaselineLandmarkFeatures?.() ?? null,
        });
        return;
      }
      const bitmap = await createImageBitmap(video);
      if (
        !activeRef.current ||
        generation !== captureGenerationRef.current ||
        bitmapsRef.current.length >= MAX_CAPTURED_BITMAPS
      ) {
        bitmap.close();
      } else {
        bitmapsRef.current.push({
          bitmap,
          timestamp: performance.now(),
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
  }, [framed, getBaselineLandmarkFeatures, getBodyBox, getCropRegion, getFramingFrame, getLandmarkFeatures, streamFrames, videoRef]);

  const finish = useCallback(async () => {
    if (!activeRef.current) return;
    const generation = captureGenerationRef.current;
    activeRef.current = false;
    clearTimers();
    const duration = performance.now() - startAtRef.current;
    const validation = validateCaptureDuration(duration);
    if (!validation.valid) {
      closeBufferedFrames();
      inProgressRef.current = false;
      setStatus("idle");
      onTooShort(validation.message ?? "Clip chưa hợp lệ.");
      return;
    }
    if (!bitmapsRef.current.length) {
      inProgressRef.current = false;
      setStatus("idle");
      onError("Không thu được hình từ camera. Hãy kiểm tra camera và thử lại.");
      return;
    }

    setStatus("encoding");
    const locked = lockedFramingRef.current;
    const source = framed && locked
      ? trimToSigning(bitmapsRef.current, locked.width, locked.height)
      : bitmapsRef.current;
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
    const samplePlan = captureSampleIndices(
      source.length,
      TARGET_FRAME_COUNT,
      motionScores,
      samplingStrategy,
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
        if (!selectedSet.has(frame)) frame.bitmap?.close();
      }
    }
    // Unencoded full frames for the post-capture encoder.
    const raw = (frames: TimedCapture[]): CapturedBitmap[] =>
      frames.map((frame) => ({ bitmap: frame.bitmap!, crop: frame.crop }));
    try {
      let sampled: string[] = [];
      let sourceFrames: string[] | null = null;
      if (streamFrames) {
        // Most frames finished encoding while the user was signing.
        const uniqueEncoded = await Promise.all(selected.map((frame) => frame.encoded!));
        if (generation !== captureGenerationRef.current) return;
        const encodedByIndex = new Map(
          uniqueIndices.map((sourceIndex, resultIndex) => [sourceIndex, uniqueEncoded[resultIndex]]),
        );
        sampled = samplePlan.map((sourceIndex) => encodedByIndex.get(sourceIndex)!);
      } else if (encodeVideoFrames) {
        if (preserveSourceFrames) {
          sourceFrames = await encodeFrames(raw(source));
          if (generation !== captureGenerationRef.current) return;
          sampled = samplePlan.map((sourceIndex) => sourceFrames![sourceIndex]);
        } else {
          const uniqueEncoded = await encodeFrames(raw(selected));
          if (generation !== captureGenerationRef.current) return;
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
          frame.bitmap?.close();
        }
      }
      if (generation !== captureGenerationRef.current) return;
      onFrames({
        frames: sampled,
        sourceFrames,
        landmarkFrames,
        baselineLandmarkFrames,
        durationMs: Math.round(duration),
      });
    } catch (error) {
      if (generation === captureGenerationRef.current) {
        onError(error instanceof Error ? error.message : "Không thể xử lý frame camera.");
      }
    } finally {
      if (generation === captureGenerationRef.current) {
        inProgressRef.current = false;
        setStatus("idle");
      }
    }
  }, [
    framed,
    streamFrames,
    clearTimers,
    closeBufferedFrames,
    encodeVideoFrames,
    onError,
    onFrames,
    onTooShort,
    preserveSourceFrames,
    samplingStrategy,
  ]);

  const start = useCallback(() => {
    if (!canStart || inProgressRef.current || status !== "idle") return;
    closeBufferedFrames();
    lockedFramingRef.current = null;
    captureGenerationRef.current += 1;
    inProgressRef.current = true;
    activeRef.current = true;
    startAtRef.current = performance.now();
    setStatus("capturing");
    onCaptureStart();
    void captureFrame();
    intervalRef.current = window.setInterval(() => void captureFrame(), 75);
    timeoutRef.current = window.setTimeout(() => void finish(), MAX_CAPTURE_MS);
  }, [canStart, captureFrame, closeBufferedFrames, finish, onCaptureStart, status]);

  const cancel = useCallback(() => {
    if (!inProgressRef.current) return;
    captureGenerationRef.current += 1;
    inProgressRef.current = false;
    activeRef.current = false;
    clearTimers();
    closeBufferedFrames();
    setStatus("idle");
    onCaptureCancel();
  }, [clearTimers, closeBufferedFrames, onCaptureCancel]);

  useEffect(() => {
    if (captureContextKeyRef.current === captureContextKey) return;
    captureContextKeyRef.current = captureContextKey;
    cancel();
  }, [cancel, captureContextKey]);

  useEffect(
    () => () => {
      captureGenerationRef.current += 1;
      inProgressRef.current = false;
      activeRef.current = false;
      clearTimers();
      closeBufferedFrames();
      encoderRef.current?.dispose();
      encoderRef.current = null;
    },
    [clearTimers, closeBufferedFrames],
  );

  return { status, start, stop: () => void finish(), cancel };
}
