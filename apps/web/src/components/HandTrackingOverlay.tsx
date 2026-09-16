import { useEffect, useRef, useState, type RefObject } from "react";
import type {
  HandLandmarker as HandLandmarkerType,
  HandLandmarkerResult,
  NormalizedLandmark,
  PoseLandmarker as PoseLandmarkerType,
} from "@mediapipe/tasks-vision";
import {
  containedVideoRect,
  mirroredDisplayPoint,
  type DisplayRect,
} from "../lib/cameraGeometry";
import {
  calculateAdaptiveFraming,
  smoothCropRegion,
  type AdaptiveFraming,
  type NormalizedCropRegion,
} from "../lib/adaptiveFraming";
import {
  isUsableUpperBodyPose,
  packLandmarkFrame,
} from "../lib/landmarkFeatures";
import { packBaselineLandmarkFrame } from "../lib/landmarkFeaturesV3";

export interface HandTrackingFrame {
  crop: NormalizedCropRegion | null;
  handCount: number;
  features: number[] | null;
  baselineFeatures: number[] | null;
  updatedAt: number;
}

interface HandTrackingOverlayProps {
  videoRef: RefObject<HTMLVideoElement | null>;
  active: boolean;
  onTrackingFrame: (frame: HandTrackingFrame) => void;
}

type TrackerPhase = "off" | "loading" | "ready" | "tracking" | "error";

interface TrackerReadout {
  phase: TrackerPhase;
  handCount: number;
  fps: number;
  distance: AdaptiveFraming["distance"] | null;
}

const TARGET_INTERVAL_MS = 30;
// V4.2 was trained from independent IMAGE-mode pose detections. VIDEO-mode pose
// tracking shifts the shoulder-relative features enough to pull unrelated signs
// toward "Đâu". Refreshing an IMAGE-mode pose every ~60 ms preserves that
// feature contract while hand tracking stays in the faster VIDEO mode.
const POSE_INTERVAL_MS = 60;
const HAND_TRACKING_CONFIDENCE = 0.35;
const POSE_TRACKING_CONFIDENCE = 0.3;
const HAND_COLORS = ["#dff36b", "#62ead1"] as const;
const UPPER_BODY_CONNECTIONS = [
  { start: 0, end: 2 },
  { start: 0, end: 5 },
  { start: 2, end: 5 },
  { start: 2, end: 7 },
  { start: 5, end: 8 },
  { start: 9, end: 10 },
  { start: 11, end: 12 },
  { start: 11, end: 13 },
  { start: 13, end: 15 },
  { start: 12, end: 14 },
  { start: 14, end: 16 },
  { start: 0, end: 11 },
  { start: 0, end: 12 },
] as const;

function trackerText(readout: TrackerReadout): string {
  if (readout.phase === "loading") return "Đang tải tracking tay + cơ thể…";
  if (readout.phase === "error") return "Tracking cơ thể chưa sẵn sàng";
  if (readout.phase === "off") return "Tracking đang tắt";
  const speed = `${readout.fps || "—"} fps`;
  if (!readout.handCount) return `Đưa tay vào vùng thu · ${speed}`;
  if (readout.distance === "too-far") {
    return `${readout.handCount} tay · ${speed} · Tự phóng gần`;
  }
  if (readout.distance === "too-close") {
    return `${readout.handCount} tay · ${speed} · Tự thu khung`;
  }
  return `${readout.handCount} tay · ${speed} · Tỷ lệ tốt`;
}

function prepareCanvas(
  canvas: HTMLCanvasElement,
): { context: CanvasRenderingContext2D; width: number; height: number } | null {
  const bounds = canvas.getBoundingClientRect();
  const width = Math.max(1, bounds.width);
  const height = Math.max(1, bounds.height);
  const pixelRatio = Math.min(window.devicePixelRatio || 1, 1.5);
  const outputWidth = Math.round(width * pixelRatio);
  const outputHeight = Math.round(height * pixelRatio);
  if (canvas.width !== outputWidth || canvas.height !== outputHeight) {
    canvas.width = outputWidth;
    canvas.height = outputHeight;
  }
  const context = canvas.getContext("2d");
  if (!context) return null;
  context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  context.clearRect(0, 0, width, height);
  return { context, width, height };
}

function handBounds(landmarks: NormalizedLandmark[], rect: DisplayRect) {
  const points = landmarks.map((landmark) => mirroredDisplayPoint(landmark, rect));
  const xs = points.map((point) => point.x);
  const ys = points.map((point) => point.y);
  return {
    points,
    left: Math.min(...xs),
    top: Math.min(...ys),
    right: Math.max(...xs),
    bottom: Math.max(...ys),
  };
}

function roundedTrackingBox(
  context: CanvasRenderingContext2D,
  left: number,
  top: number,
  width: number,
  height: number,
  color: string,
) {
  const corner = Math.min(18, width / 4, height / 4);
  const length = Math.min(28, width / 3, height / 3);
  context.save();
  context.strokeStyle = color;
  context.lineWidth = 2.4;
  context.lineCap = "round";
  context.shadowColor = color;
  context.shadowBlur = 9;
  context.beginPath();
  context.moveTo(left, top + length);
  context.lineTo(left, top + corner);
  context.quadraticCurveTo(left, top, left + corner, top);
  context.lineTo(left + length, top);
  context.moveTo(left + width - length, top);
  context.lineTo(left + width - corner, top);
  context.quadraticCurveTo(left + width, top, left + width, top + corner);
  context.lineTo(left + width, top + length);
  context.moveTo(left + width, top + height - length);
  context.lineTo(left + width, top + height - corner);
  context.quadraticCurveTo(
    left + width,
    top + height,
    left + width - corner,
    top + height,
  );
  context.lineTo(left + width - length, top + height);
  context.moveTo(left + length, top + height);
  context.lineTo(left + corner, top + height);
  context.quadraticCurveTo(left, top + height, left, top + height - corner);
  context.lineTo(left, top + height - length);
  context.stroke();
  context.restore();
}

function drawHands(
  canvas: HTMLCanvasElement,
  video: HTMLVideoElement,
  result: HandLandmarkerResult,
  connections: readonly { start: number; end: number }[],
  framing: AdaptiveFraming | null,
  pose: readonly NormalizedLandmark[] | null,
) {
  const prepared = prepareCanvas(canvas);
  if (!prepared) return;
  const { context, width, height } = prepared;
  const rect = containedVideoRect(
    width,
    height,
    video.videoWidth,
    video.videoHeight,
  );

  if (isUsableUpperBodyPose(pose)) {
    const points = pose.map((point) => mirroredDisplayPoint(point, rect));
    context.save();
    context.strokeStyle = "rgba(125, 211, 252, 0.72)";
    context.fillStyle = "rgba(224, 242, 254, 0.92)";
    context.lineWidth = 2.2;
    context.lineCap = "round";
    context.lineJoin = "round";
    context.shadowColor = "rgba(56, 189, 248, 0.7)";
    context.shadowBlur = 6;
    for (const connection of UPPER_BODY_CONNECTIONS) {
      const startLandmark = pose[connection.start];
      const endLandmark = pose[connection.end];
      if (
        !startLandmark ||
        !endLandmark ||
        startLandmark.visibility < 0.35 ||
        endLandmark.visibility < 0.35
      ) continue;
      context.beginPath();
      context.moveTo(points[connection.start].x, points[connection.start].y);
      context.lineTo(points[connection.end].x, points[connection.end].y);
      context.stroke();
    }
    for (const index of [0, 2, 5, 9, 10, 11, 12, 13, 14, 15, 16]) {
      if (!pose[index] || pose[index].visibility < 0.35) continue;
      context.beginPath();
      context.arc(points[index].x, points[index].y, index >= 11 ? 3.5 : 2.7, 0, Math.PI * 2);
      context.fill();
    }
    context.restore();
  }

  if (framing) {
    const crop = framing.crop;
    const cropLeft = rect.x + (1 - crop.x - crop.width) * rect.width;
    const cropTop = rect.y + crop.y * rect.height;
    context.save();
    context.strokeStyle = "rgba(255, 255, 255, 0.58)";
    context.lineWidth = 1.2;
    context.setLineDash([8, 7]);
    context.strokeRect(
      cropLeft,
      cropTop,
      crop.width * rect.width,
      crop.height * rect.height,
    );
    context.restore();
  }

  result.landmarks.forEach((landmarks, handIndex) => {
    const color = HAND_COLORS[handIndex % HAND_COLORS.length];
    const bounds = handBounds(landmarks, rect);
    const padding = 16;
    const left = Math.max(rect.x + 3, bounds.left - padding);
    const top = Math.max(rect.y + 3, bounds.top - padding);
    const right = Math.min(rect.x + rect.width - 3, bounds.right + padding);
    const bottom = Math.min(rect.y + rect.height - 3, bounds.bottom + padding);

    context.save();
    context.strokeStyle = color;
    context.lineWidth = 2;
    context.globalAlpha = 0.82;
    context.lineJoin = "round";
    for (const connection of connections) {
      const start = bounds.points[connection.start];
      const end = bounds.points[connection.end];
      if (!start || !end) continue;
      context.beginPath();
      context.moveTo(start.x, start.y);
      context.lineTo(end.x, end.y);
      context.stroke();
    }
    context.globalAlpha = 1;
    for (const [index, point] of bounds.points.entries()) {
      context.beginPath();
      context.arc(point.x, point.y, index % 4 === 0 ? 3.7 : 2.6, 0, Math.PI * 2);
      context.fillStyle = index % 4 === 0 ? "#ffffff" : color;
      context.fill();
    }
    context.restore();
    roundedTrackingBox(context, left, top, right - left, bottom - top, color);
  });
}

export function HandTrackingOverlay({
  videoRef,
  active,
  onTrackingFrame,
}: HandTrackingOverlayProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const landmarkerRef = useRef<HandLandmarkerType | null>(null);
  const poseLandmarkerRef = useRef<PoseLandmarkerType | null>(null);
  const loadingRef = useRef(false);
  const disposedRef = useRef(false);
  const smoothedCropRef = useRef<NormalizedCropRegion | null>(null);
  const [modelReady, setModelReady] = useState(false);
  const [readout, setReadout] = useState<TrackerReadout>({
    phase: "off",
    handCount: 0,
    fps: 0,
    distance: null,
  });

  useEffect(() => {
    disposedRef.current = false;
    return () => {
      disposedRef.current = true;
      landmarkerRef.current?.close();
      landmarkerRef.current = null;
      poseLandmarkerRef.current?.close();
      poseLandmarkerRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (
      !active ||
      (landmarkerRef.current && poseLandmarkerRef.current) ||
      loadingRef.current
    ) return;
    loadingRef.current = true;
    setReadout({ phase: "loading", handCount: 0, fps: 0, distance: null });
    const baseUrl = import.meta.env.BASE_URL;

    void import("@mediapipe/tasks-vision")
      .then(async ({ FilesetResolver, HandLandmarker, PoseLandmarker }) => {
        const fileset = await FilesetResolver.forVisionTasks(
          `${baseUrl}mediapipe/wasm`,
        );
        const options = {
          runningMode: "VIDEO" as const,
          numHands: 2,
          // Match the landmark extraction pipeline so partially occluded or
          // farther-away hands are not discarded only at live inference time.
          minHandDetectionConfidence: HAND_TRACKING_CONFIDENCE,
          minHandPresenceConfidence: HAND_TRACKING_CONFIDENCE,
          minTrackingConfidence: HAND_TRACKING_CONFIDENCE,
        };
        let landmarker: HandLandmarkerType;
        try {
          landmarker = await HandLandmarker.createFromOptions(fileset, {
            ...options,
            baseOptions: {
              modelAssetPath: `${baseUrl}models/hand_landmarker.task`,
              delegate: "GPU",
            },
          });
        } catch {
          landmarker = await HandLandmarker.createFromOptions(fileset, {
            ...options,
            baseOptions: {
              modelAssetPath: `${baseUrl}models/hand_landmarker.task`,
              delegate: "CPU",
            },
          });
        }
        const poseOptions = {
          runningMode: "IMAGE" as const,
          numPoses: 1,
          minPoseDetectionConfidence: POSE_TRACKING_CONFIDENCE,
          minPosePresenceConfidence: POSE_TRACKING_CONFIDENCE,
          minTrackingConfidence: POSE_TRACKING_CONFIDENCE,
          outputSegmentationMasks: false,
        };
        // Keep pose extraction identical to the CPU pipeline that produced the
        // V4.2 training features and the frozen A/B replay. Small GPU/CPU pose
        // shifts are amplified by shoulder-relative normalization. Hands stay
        // on the GPU/VIDEO path because they dominate visible tracking latency.
        const poseLandmarker = await PoseLandmarker.createFromOptions(fileset, {
          ...poseOptions,
          baseOptions: {
            modelAssetPath: `${baseUrl}models/pose_landmarker_lite.task`,
            delegate: "CPU",
          },
        });
        if (disposedRef.current) {
          landmarker.close();
          poseLandmarker.close();
          return;
        }
        landmarkerRef.current = landmarker;
        poseLandmarkerRef.current = poseLandmarker;
        setModelReady(true);
        setReadout({ phase: "ready", handCount: 0, fps: 0, distance: null });
      })
      .catch(() => {
        if (!disposedRef.current) {
          setReadout({ phase: "error", handCount: 0, fps: 0, distance: null });
        }
      })
      .finally(() => {
        loadingRef.current = false;
      });
  }, [active]);

  useEffect(() => {
    if (!active) {
      const canvas = canvasRef.current;
      if (canvas) {
        const currentWidth = canvas.width;
        canvas.width = currentWidth;
      }
      setReadout((current) => ({ ...current, phase: "off", handCount: 0, fps: 0 }));
      smoothedCropRef.current = null;
      onTrackingFrame({
        crop: null,
        handCount: 0,
        features: null,
        baselineFeatures: null,
        updatedAt: performance.now(),
      });
      return;
    }
    if (!modelReady || !landmarkerRef.current) return;

    let animationFrame = 0;
    let videoFrame = 0;
    let scheduledVideo: HTMLVideoElement | null = null;
    let lastInferenceAt = 0;
    let lastPoseInferenceAt = -POSE_INTERVAL_MS;
    let lastVideoTime = -1;
    let latestPose: readonly NormalizedLandmark[] | null = null;
    let samples = 0;
    let fpsWindowStarted = performance.now();
    let visibleFps = 0;
    let previousHands = -1;
    const connections = landmarkerRef.current.constructor as typeof HandLandmarkerType;

    const scheduleNextFrame = () => {
      const video = videoRef.current;
      if (video?.requestVideoFrameCallback) {
        scheduledVideo = video;
        videoFrame = video.requestVideoFrameCallback((timestamp) => track(timestamp));
      } else {
        animationFrame = window.requestAnimationFrame(track);
      }
    };

    const track = (timestamp: number) => {
      const video = videoRef.current;
      const canvas = canvasRef.current;
      const landmarker = landmarkerRef.current;
      const poseLandmarker = poseLandmarkerRef.current;
      if (
        video &&
        canvas &&
        landmarker &&
        poseLandmarker &&
        video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA &&
        video.currentTime !== lastVideoTime &&
        timestamp - lastInferenceAt >= TARGET_INTERVAL_MS
      ) {
        try {
          const result = landmarker.detectForVideo(video, timestamp);
          if (timestamp - lastPoseInferenceAt >= POSE_INTERVAL_MS) {
            const poseResult = poseLandmarker.detect(video);
            latestPose = poseResult.landmarks[0] ?? null;
            lastPoseInferenceAt = timestamp;
          }
          const calculated = calculateAdaptiveFraming(
            result.landmarks,
            video.videoWidth,
            video.videoHeight,
          );
          const framing = calculated
            ? {
                ...calculated,
                crop: smoothCropRegion(smoothedCropRef.current, calculated.crop),
              }
            : null;
          smoothedCropRef.current = framing?.crop ?? null;
          drawHands(
            canvas,
            video,
            result,
            connections.HAND_CONNECTIONS,
            framing,
            latestPose,
          );
          onTrackingFrame({
            crop: framing?.crop ?? null,
            handCount: result.landmarks.length,
            features: packLandmarkFrame(result.landmarks, latestPose),
            baselineFeatures: packBaselineLandmarkFrame(result.landmarks),
            updatedAt: timestamp,
          });
          lastInferenceAt = timestamp;
          lastVideoTime = video.currentTime;
          samples += 1;
          const elapsed = timestamp - fpsWindowStarted;
          if (elapsed >= 900) {
            visibleFps = Math.round((samples * 1000) / elapsed);
            samples = 0;
            fpsWindowStarted = timestamp;
          }
          const handCount = result.landmarks.length;
          if (handCount !== previousHands || elapsed >= 900) {
            previousHands = handCount;
            setReadout({
              phase: handCount ? "tracking" : "ready",
              handCount,
              fps: visibleFps,
              distance: framing?.distance ?? null,
            });
          }
        } catch {
          setReadout({ phase: "error", handCount: 0, fps: 0, distance: null });
          onTrackingFrame({
            crop: null,
            handCount: 0,
            features: null,
            baselineFeatures: null,
            updatedAt: timestamp,
          });
          return;
        }
      }
      scheduleNextFrame();
    };

    scheduleNextFrame();
    return () => {
      window.cancelAnimationFrame(animationFrame);
      if (videoFrame && scheduledVideo?.cancelVideoFrameCallback) {
        scheduledVideo.cancelVideoFrameCallback(videoFrame);
      }
    };
  }, [active, modelReady, onTrackingFrame, videoRef]);

  return (
    <div className={`tracking-overlay tracking-${readout.phase}`} aria-hidden="true">
      <canvas ref={canvasRef} className="tracking-canvas" />
      {active && <span className="tracking-scan" />}
      <div className="tracking-readout">
        <span className="tracking-status-dot" />
        <span>{trackerText(readout)}</span>
      </div>
    </div>
  );
}
