import type { NormalizedCropRegion } from "./adaptiveFraming";

/**
 * Browser port of `ml/body_framing.py` (`trim-bodycrop-v1`). Both implementations
 * are checked against `contracts/v1/framing_golden.json`; change them together.
 */
export const BODY_FRAMING_VERSION = "trim-bodycrop-v1";
// MediaPipe pose: nose, left/right shoulder, left/right elbow, left/right wrist.
export const FRAMING_POSE_INDICES = [0, 11, 12, 13, 14, 15, 16] as const;
const LEFT_SHOULDER = 1;
const RIGHT_SHOULDER = 2;
const LEFT_WRIST = 5;
const RIGHT_WRIST = 6;

const VISIBLE = 0.5;
const MIN_SHOULDER_FRAMES = 3;
// Distances below are in shoulder widths, measured from the shoulder midpoint.
const REST_LINE = 1.1;
const BOX_SIDE = 2.6;
const BOX_CENTER_DROP = -0.15; // negative: centre above the shoulder line
const MIN_BOX_FRACTION = 0.25;
const SPAN_PAD_MS = 100;
const LIVE_BOX_WINDOW_MS = 1500;

/** Normalized, unmirrored MediaPipe coordinates; pose is [x, y, visibility] per FRAMING_POSE_INDICES. */
export interface FramingFrame {
  t: number;
  pose: readonly (readonly number[])[] | null;
  /** [wrist x, wrist y, min x, min y, max x, max y] per detected hand. */
  hands: readonly (readonly number[])[];
}

interface Anchor {
  centerX: number;
  shoulderY: number;
  shoulderWidth: number;
}

interface PointLike {
  x: number;
  y: number;
  visibility?: number;
}

export function framingFrame(
  t: number,
  hands: readonly (readonly PointLike[])[],
  pose: readonly PointLike[] | null | undefined,
): FramingFrame {
  return {
    t,
    pose: pose && pose.length > 16
      ? FRAMING_POSE_INDICES.map((index) => [pose[index].x, pose[index].y, pose[index].visibility ?? 0])
      : null,
    hands: hands.filter((hand) => hand.length > 0).map((hand) => {
      const xs = hand.map((point) => point.x);
      const ys = hand.map((point) => point.y);
      return [hand[0].x, hand[0].y, Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
    }),
  };
}

function median(values: readonly number[]): number {
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function shoulders(frame: FramingFrame, width: number, height: number): Anchor | null {
  const left = frame.pose?.[LEFT_SHOULDER];
  const right = frame.pose?.[RIGHT_SHOULDER];
  if (!left || !right || left[2] <= VISIBLE || right[2] <= VISIBLE) return null;
  const leftX = left[0] * width;
  const leftY = left[1] * height;
  const rightX = right[0] * width;
  const rightY = right[1] * height;
  const span = Math.hypot(leftX - rightX, leftY - rightY);
  if (span <= 0) return null;
  return { centerX: (leftX + rightX) / 2, shoulderY: (leftY + rightY) / 2, shoulderWidth: span };
}

export function bodyAnchor(frames: readonly FramingFrame[], width: number, height: number): Anchor | null {
  const found = frames.map((frame) => shoulders(frame, width, height)).filter((value) => value !== null);
  if (found.length < MIN_SHOULDER_FRAMES) return null;
  return {
    centerX: median(found.map((value) => value.centerX)),
    shoulderY: median(found.map((value) => value.shoulderY)),
    shoulderWidth: median(found.map((value) => value.shoulderWidth)),
  };
}

function isActive(frame: FramingFrame, restY: number | null, height: number): boolean {
  for (const hand of frame.hands) {
    if (restY === null || hand[1] * height < restY) return true;
  }
  if (restY !== null && frame.pose) {
    for (const index of [LEFT_WRIST, RIGHT_WRIST]) {
      const [, y, visibility] = frame.pose[index];
      if (visibility > VISIBLE && y * height < restY) return true;
    }
  }
  return false;
}

/** Inclusive [start, end] from the first to the last raised hand, padded by SPAN_PAD_MS. */
export function trimSpan(frames: readonly FramingFrame[], width: number, height: number): [number, number] {
  if (!frames.length) throw new Error("Không có frame để cắt đoạn ký.");
  const anchor = bodyAnchor(frames, width, height);
  const restY = anchor ? anchor.shoulderY + REST_LINE * anchor.shoulderWidth : null;
  const active = frames.flatMap((frame, index) => isActive(frame, restY, height) ? [index] : []);
  if (active.length < 2) return [0, frames.length - 1];
  const firstTime = frames[active[0]].t - SPAN_PAD_MS;
  const lastTime = frames[active[active.length - 1]].t + SPAN_PAD_MS;
  const start = frames.findIndex((frame) => frame.t >= firstTime);
  let end = frames.length - 1;
  while (frames[end].t > lastTime) end -= 1;
  return [start, end];
}

/** Square crop around the signer; it may extend past the image edges (padded black). */
export function bodyBox(frames: readonly FramingFrame[], width: number, height: number): NormalizedCropRegion | null {
  const anchor = bodyAnchor(frames, width, height);
  if (!anchor) return null;
  const side = Math.max(BOX_SIDE * anchor.shoulderWidth, MIN_BOX_FRACTION * Math.min(width, height));
  const centerY = anchor.shoulderY + BOX_CENTER_DROP * anchor.shoulderWidth;
  return {
    x: (anchor.centerX - side / 2) / width,
    y: (centerY - side / 2) / height,
    width: side / width,
    height: side / height,
  };
}

export function centerSquareBox(width: number, height: number): NormalizedCropRegion {
  const side = Math.min(width, height);
  return { x: (width - side) / 2 / width, y: (height - side) / 2 / height, width: side / width, height: side / height };
}

export interface DrawPlan {
  source: { x: number; y: number; width: number; height: number };
  destination: { x: number; y: number; width: number; height: number };
}

/** Source rectangle (inside the image) and integer destination rectangle for a padded crop. */
export function drawPlan(box: NormalizedCropRegion, width: number, height: number, size: number): DrawPlan | null {
  const left = box.x * width;
  const top = box.y * height;
  const cropWidth = box.width * width;
  const cropHeight = box.height * height;
  const sourceLeft = Math.max(0, left);
  const sourceTop = Math.max(0, top);
  const sourceRight = Math.min(width, left + cropWidth);
  const sourceBottom = Math.min(height, top + cropHeight);
  if (sourceRight <= sourceLeft || sourceBottom <= sourceTop) return null;
  const scaleX = size / cropWidth;
  const scaleY = size / cropHeight;
  const destinationLeft = Math.round((sourceLeft - left) * scaleX);
  const destinationTop = Math.round((sourceTop - top) * scaleY);
  const destinationRight = Math.round((sourceRight - left) * scaleX);
  const destinationBottom = Math.round((sourceBottom - top) * scaleY);
  if (destinationRight <= destinationLeft || destinationBottom <= destinationTop) return null;
  return {
    source: { x: sourceLeft, y: sourceTop, width: sourceRight - sourceLeft, height: sourceBottom - sourceTop },
    destination: {
      x: destinationLeft,
      y: destinationTop,
      width: destinationRight - destinationLeft,
      height: destinationBottom - destinationTop,
    },
  };
}

type DrawContext = CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D;

/** Draw `box` of `source` onto a black `size` square, matching `apply_box` in Python. */
export function drawBoxed(
  context: DrawContext,
  source: CanvasImageSource,
  sourceWidth: number,
  sourceHeight: number,
  box: NormalizedCropRegion,
  size: number,
  quality?: ImageSmoothingQuality,
): void {
  context.fillStyle = "#000";
  context.fillRect(0, 0, size, size);
  const plan = drawPlan(box, sourceWidth, sourceHeight, size);
  if (!plan) return;
  context.imageSmoothingEnabled = true;
  if (quality) context.imageSmoothingQuality = quality;
  context.drawImage(
    source,
    plan.source.x, plan.source.y, plan.source.width, plan.source.height,
    plan.destination.x, plan.destination.y, plan.destination.width, plan.destination.height,
  );
}

// Crops may extend past the frame (body framing); the uncovered area stays black.
// Only body framing sends cropped full-resolution frames to the server, and it was
// matched against a high-quality downscale; the center-square path keeps the default.
export function drawCapturedFrame(
  context: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D,
  frame: { bitmap: ImageBitmap; crop: NormalizedCropRegion | null },
  size: number,
): void {
  const { bitmap, crop } = frame;
  drawBoxed(
    context, bitmap, bitmap.width, bitmap.height,
    crop ?? centerSquareBox(bitmap.width, bitmap.height), size,
    crop ? "high" : undefined,
  );
}

/** Live counterpart of the per-clip median: the box over the most recent pose detections. */
export class BodyBoxTracker {
  private frames: FramingFrame[] = [];

  push(frame: FramingFrame): void {
    this.frames.push(frame);
    const oldest = frame.t - LIVE_BOX_WINDOW_MS;
    while (this.frames.length && this.frames[0].t < oldest) this.frames.shift();
  }

  box(width: number, height: number): NormalizedCropRegion | null {
    return bodyBox(this.frames, width, height);
  }

  reset(): void {
    this.frames = [];
  }
}
