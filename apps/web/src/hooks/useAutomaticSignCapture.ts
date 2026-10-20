import { type RefObject, useCallback, useEffect, useRef, useState } from "react";
import type { HandTrackingFrame } from "../components/HandTrackingOverlay";
import {
  AutomaticSignSegmenter,
  PRE_ROLL_MS,
  type AutomaticCapturePhase,
  type SegmentWindow,
} from "../lib/autoSegmentation";
import {
  BodyBoxTracker,
  centerSquareBox,
  drawBoxed,
  trimSpan,
  type FramingFrame,
} from "../lib/bodyFraming";
import { centeredSquareRect } from "../lib/cameraGeometry";
import { createStreamingEncoder, type StreamingFrameEncoder } from "../lib/frameEncoder";
import { TARGET_FRAME_COUNT, uniformSampleIndices } from "../lib/sampling";
import type { AutomaticCaptureTiming } from "../lib/automaticInferenceQueue";

interface TimedBitmap {
  timestamp: number;
  framing?: FramingFrame;
  /** Owned until the snapshot is handed to the encoder. */
  bitmap: ImageBitmap | null;
  encoded: Promise<string> | null;
}

function release(item: TimedBitmap): void {
  item.bitmap?.close();
  item.bitmap = null;
}

const RGB_INTERVAL_MS = 75;
const MAX_RGB_BITMAPS = 64;
const RGB_SIZE = 224;
const MIN_RGB_FRAMES = 4;

/** Keep only bitmaps inside the raised-hand span (trim-bodycrop-v1). */
function trimToSigning(source: TimedBitmap[], width: number, height: number): TimedBitmap[] {
  const observations = source.map((item) => item.framing);
  if (!observations.length || observations.some((item) => !item)) return source;
  const [start, end] = trimSpan(
    observations.map((item, index) => ({ ...item!, t: source[index].timestamp })), width, height,
  );
  const trimmed = source.slice(start, end + 1);
  return trimmed.length >= MIN_RGB_FRAMES ? trimmed : source;
}

interface AutomaticSignCaptureOptions {
  enabled: boolean;
  paused: boolean;
  videoRef?: RefObject<HTMLVideoElement | null>;
  captureVideoFrames?: boolean;
  /** Crop around the signer and send only the raised-hand span (trim-bodycrop-v1 models). */
  bodyFraming?: boolean;
  captureContextKey?: string;
  onSequence: (
    frames: number[][],
    baselineFrames: number[][],
    rgbFrames?: string[],
    timing?: AutomaticCaptureTiming,
    /** Set when this sign is a provisional segment already handed to onProvisional. */
    confirmedProvisional?: number,
  ) => void;
  /**
   * Server RGB only: the hands just came to rest, so this segment is likely final.
   * Run inference now and keep the result until onSequence confirms the id.
   */
  onProvisional?: (
    id: number,
    frames: number[][],
    baselineFrames: number[][],
    rgbFrames: string[],
    timing: AutomaticCaptureTiming,
  ) => void;
  /** The hands moved again: drop that provisional result. */
  onProvisionalCancel?: (id: number) => void;
  onCaptureStart?: () => void;
  onCaptureCancel?: () => void;
  onError?: (message: string) => void;
}

export interface AutomaticSignCaptureController {
  phase: AutomaticCapturePhase;
  ingest: (frame: HandTrackingFrame) => void;
  isBusy: () => boolean;
}

export function useAutomaticSignCapture({
  enabled,
  paused,
  videoRef,
  captureVideoFrames = false,
  bodyFraming = false,
  captureContextKey = "default",
  onSequence,
  onProvisional,
  onProvisionalCancel,
  onCaptureStart,
  onCaptureCancel,
  onError,
}: AutomaticSignCaptureOptions): AutomaticSignCaptureController {
  const segmenterRef = useRef(new AutomaticSignSegmenter());
  const enabledRef = useRef(enabled);
  const pausedRef = useRef(paused);
  const onSequenceRef = useRef(onSequence);
  const onStartRef = useRef(onCaptureStart);
  const onCancelRef = useRef(onCaptureCancel);
  const onErrorRef = useRef(onError);
  const onProvisionalRef = useRef(onProvisional);
  const onProvisionalCancelRef = useRef(onProvisionalCancel);
  const provisionalsRef = useRef(new Map<number, { rgb: Promise<string[]>; sent: boolean; settled: boolean }>());
  const generationRef = useRef(0);
  const inFlightRef = useRef<object | null>(null);
  const processingRef = useRef(false);
  const bitmapsRef = useRef<TimedBitmap[]>([]);
  const encoderRef = useRef<StreamingFrameEncoder | null>(null);
  const lastBitmapAtRef = useRef(-Infinity);
  const bodyBoxRef = useRef(new BodyBoxTracker());
  const rgbCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const [phase, setPhase] = useState<AutomaticCapturePhase>("off");
  enabledRef.current = enabled;
  pausedRef.current = paused;
  onSequenceRef.current = onSequence;
  onStartRef.current = onCaptureStart;
  onCancelRef.current = onCaptureCancel;
  onErrorRef.current = onError;
  onProvisionalRef.current = onProvisional;
  onProvisionalCancelRef.current = onProvisionalCancel;
  const speculate = captureVideoFrames && Boolean(onProvisional);

  const dropProvisionals = useCallback(() => {
    for (const [id, entry] of provisionalsRef.current) {
      entry.settled = true;
      if (entry.sent) onProvisionalCancelRef.current?.(id);
    }
    provisionalsRef.current.clear();
  }, []);

  const closeBitmaps = useCallback(() => {
    bitmapsRef.current.forEach(release);
    bitmapsRef.current = [];
  }, []);

  // Snapshots are encoded while the user signs, so a finished sign only waits
  // for its last few frames. Unused results are simply dropped.
  const startEncoding = useCallback((item: TimedBitmap) => {
    if (item.encoded || !item.bitmap) return;
    encoderRef.current ??= createStreamingEncoder();
    item.encoded = encoderRef.current.encode({ bitmap: item.bitmap, crop: null });
    item.encoded.catch(() => undefined);
    item.bitmap = null;
  }, []);

  useEffect(() => {
    const segmenter = segmenterRef.current;
    generationRef.current += 1;
    processingRef.current = false;
    inFlightRef.current = null;
    lastBitmapAtRef.current = -Infinity;
    bodyBoxRef.current.reset();
    closeBitmaps();
    dropProvisionals();
    segmenter.reset(enabled);
    segmenter.setSpeculation(speculate);
    setPhase(enabled ? "waiting" : "off");
    return () => {
      const wasActive = processingRef.current ||
        segmenter.phase === "capturing" ||
        segmenter.phase === "postroll";
      generationRef.current += 1;
      closeBitmaps();
      dropProvisionals();
      encoderRef.current?.dispose();
      encoderRef.current = null;
      segmenter.reset(false);
      if (wasActive) onCancelRef.current?.();
    };
  }, [bodyFraming, captureContextKey, captureVideoFrames, closeBitmaps, dropProvisionals, enabled, speculate]);

  useEffect(() => {
    const segmenter = segmenterRef.current;
    if (!paused) return;
    const wasActive = processingRef.current ||
      segmenter.phase === "capturing" ||
      segmenter.phase === "postroll";
    generationRef.current += 1;
    processingRef.current = false;
    inFlightRef.current = null;
    closeBitmaps();
    dropProvisionals();
    segmenter.reset(enabled, true);
    lastBitmapAtRef.current = -Infinity;
    setPhase(segmenter.phase);
    if (wasActive) onCancelRef.current?.();
  }, [closeBitmaps, dropProvisionals, enabled, paused]);

  /** The 16 encoded RGB frames for a segment window, from snapshots already encoding. */
  const rgbFor = useCallback((window: SegmentWindow | null | undefined, video: HTMLVideoElement | null | undefined) => {
    const windowed = bitmapsRef.current.filter((item) =>
      window && item.timestamp >= window.startAt && item.timestamp <= window.endAt,
    );
    const source = bodyFraming && video
      ? trimToSigning(windowed, video.videoWidth, video.videoHeight)
      : windowed;
    const indices = source.length >= MIN_RGB_FRAMES
      ? uniformSampleIndices(source.length, TARGET_FRAME_COUNT)
      : [];
    const selected = [...new Set(indices)].map((index) => source[index]);
    selected.forEach(startEncoding);
    if (!selected.length) {
      return Promise.reject(new Error("Không thu được đủ ảnh camera cho ký hiệu. Hãy thử lại."));
    }
    return Promise.all(selected.map((item) => item.encoded!)).then((encoded) => {
      const byFrame = new Map(selected.map((item, index) => [item, encoded[index]]));
      const frames = indices.map((index) => byFrame.get(source[index])!);
      if (frames.length !== TARGET_FRAME_COUNT || frames.some((url) => !url)) {
        throw new Error("Ảnh ký hiệu chưa đủ 16 frame. Hãy thử lại.");
      }
      return frames;
    });
  }, [bodyFraming, startEncoding]);

  const ingest = useCallback((frame: HandTrackingFrame) => {
    if (!enabledRef.current || pausedRef.current || processingRef.current || inFlightRef.current) return;
    const generation = generationRef.current;
    const token = {};
    inFlightRef.current = token;
    const valid = () =>
      generation === generationRef.current &&
      enabledRef.current && !pausedRef.current;
    void (async () => {
      try {
        const video = videoRef?.current;
        if (frame.framing) bodyBoxRef.current.push(frame.framing);
        if (
          captureVideoFrames && video &&
          video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA &&
          video.videoWidth > 0 && video.videoHeight > 0 &&
          frame.updatedAt - lastBitmapAtRef.current >= RGB_INTERVAL_MS
        ) {
          lastBitmapAtRef.current = frame.updatedAt;
          // Keep the RGB ring small; crop to 224 when the frame is captured.
          try {
            let bitmap: ImageBitmap;
            if (bodyFraming) {
              // The live box follows the median pose of the last moments, which the
              // body barely leaves while signing; training uses the per-clip median.
              const canvas = rgbCanvasRef.current ?? document.createElement("canvas");
              rgbCanvasRef.current = canvas;
              canvas.width = RGB_SIZE;
              canvas.height = RGB_SIZE;
              const context = canvas.getContext("2d", { alpha: false });
              if (!context) throw new Error("Không tạo được canvas.");
              const box = bodyBoxRef.current.box(video.videoWidth, video.videoHeight) ??
                centerSquareBox(video.videoWidth, video.videoHeight);
              drawBoxed(context, video, video.videoWidth, video.videoHeight, box, RGB_SIZE, "high");
              bitmap = await createImageBitmap(canvas);
            } else {
              // Same center-square crop as manual Sales30.
              const crop = centeredSquareRect({
                x: 0, y: 0, width: video.videoWidth, height: video.videoHeight,
              });
              bitmap = await createImageBitmap(
                video, crop.x, crop.y, crop.width, crop.height,
                { resizeWidth: RGB_SIZE, resizeHeight: RGB_SIZE, resizeQuality: "low" },
              );
            }
            if (!valid()) {
              bitmap.close();
              return;
            }
            bitmapsRef.current.push({
              bitmap, encoded: null, timestamp: frame.updatedAt, framing: frame.framing,
            });
          } catch {
            // A missing snapshot must not change the landmark segment boundaries.
          }
        }
        if (!valid()) return;
        const previousPhase = segmenterRef.current.phase;
        const update = segmenterRef.current.push(
          frame.features, frame.updatedAt, frame.baselineFeatures,
        );
        setPhase(update.phase);
        if (previousPhase === "waiting" && update.phase === "capturing") {
          onStartRef.current?.();
        }
        const resting = update.phase === "waiting" || update.phase === "cooldown" ||
          update.phase === "rearming";
        const oldestAllowed = resting && !update.sequence
          ? frame.updatedAt - PRE_ROLL_MS
          : -Infinity;
        while (bitmapsRef.current.length && (
          bitmapsRef.current[0].timestamp < oldestAllowed || bitmapsRef.current.length > MAX_RGB_BITMAPS
        )) release(bitmapsRef.current.shift()!);
        // Resting snapshots stay raw; from the first moving frame on, everything is encoded.
        if (captureVideoFrames && (
          update.phase === "capturing" || update.phase === "postroll" || update.sequence
        )) bitmapsRef.current.forEach(startEncoding);

        if (update.provisionalCancelled !== undefined) {
          const entry = provisionalsRef.current.get(update.provisionalCancelled);
          provisionalsRef.current.delete(update.provisionalCancelled);
          if (entry) {
            entry.settled = true;
            if (entry.sent) onProvisionalCancelRef.current?.(update.provisionalCancelled);
          }
        }
        const provisional = update.provisional;
        if (provisional && speculate) {
          // Built off the ingest path so tracking keeps flowing while the frames finish encoding.
          const entry = { rgb: rgbFor(provisional.sourceWindow, video), sent: false, settled: false };
          entry.rgb.catch(() => undefined);
          provisionalsRef.current.set(provisional.id, entry);
          void entry.rgb.then((rgbFrames) => {
            if (!valid() || entry.settled) return;
            entry.sent = true;
            onProvisionalRef.current?.(
              provisional.id, provisional.sequence, provisional.baselineSequence, rgbFrames,
              { captureMs: Math.max(0, provisional.sourceWindow.endAt - provisional.sourceWindow.startAt), encodeMs: 0 },
            );
          }, () => undefined);
        }

        if (!update.sequence || !update.baselineSequence) {
          if (resting && (previousPhase === "capturing" || previousPhase === "postroll")) {
            closeBitmaps();
            onCancelRef.current?.();
          }
          return;
        }
        processingRef.current = true;
        const encodeStartedAt = performance.now();
        let rgbFrames: string[] | undefined;
        let confirmed: number | undefined;
        if (captureVideoFrames) {
          setPhase("encoding");
          const id = update.confirmedProvisional;
          const entry = id === undefined ? undefined : provisionalsRef.current.get(id);
          if (entry) {
            provisionalsRef.current.delete(id!);
            entry.settled = true;
            // Already with the server: the sign ended on the rest it was cut at.
            if (entry.sent) confirmed = id;
          }
          const pending = entry?.rgb ?? rgbFor(update.sourceWindow, video);
          closeBitmaps();
          rgbFrames = await pending;
          if (!valid()) return;
        }
        if (valid()) {
          setPhase(segmenterRef.current.phase);
          onSequenceRef.current(
            update.sequence, update.baselineSequence, rgbFrames,
            {
              captureMs: update.sourceWindow
                ? Math.max(0, update.sourceWindow.endAt - update.sourceWindow.startAt)
                : 0,
              encodeMs: captureVideoFrames ? Math.max(0, performance.now() - encodeStartedAt) : 0,
            },
            confirmed,
          );
        }
      } catch (error) {
        if (valid()) {
          closeBitmaps();
          setPhase(segmenterRef.current.phase);
          onErrorRef.current?.(
            error instanceof Error ? error.message : "Không thể xử lý ký hiệu tự động.",
          );
        }
      } finally {
        if (inFlightRef.current === token) inFlightRef.current = null;
        if (generation === generationRef.current) processingRef.current = false;
      }
    })();
  }, [bodyFraming, captureVideoFrames, closeBitmaps, rgbFor, speculate, startEncoding, videoRef]);

  const isBusy = useCallback(() => processingRef.current || inFlightRef.current !== null ||
    segmenterRef.current.phase === "capturing" || segmenterRef.current.phase === "postroll", []);
  return { phase, ingest, isBusy };
}
