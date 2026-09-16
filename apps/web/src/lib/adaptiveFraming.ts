export interface TrackingPoint {
  x: number;
  y: number;
}

export interface NormalizedCropRegion {
  x: number;
  y: number;
  width: number;
  height: number;
}

export type HandDistance = "too-far" | "good" | "too-close";

export interface AdaptiveFraming {
  crop: NormalizedCropRegion;
  distance: HandDistance;
  handScale: number;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

export function calculateAdaptiveFraming(
  hands: readonly (readonly TrackingPoint[])[],
  videoWidth: number,
  videoHeight: number,
): AdaptiveFraming | null {
  if (videoWidth <= 0 || videoHeight <= 0) return null;
  const validHands = hands.filter((hand) => hand.length > 0);
  if (!validHands.length) return null;

  const bounds = validHands.map((hand) => {
    const xs = hand.map((point) => clamp(point.x, 0, 1));
    const ys = hand.map((point) => clamp(point.y, 0, 1));
    return {
      left: Math.min(...xs) * videoWidth,
      right: Math.max(...xs) * videoWidth,
      top: Math.min(...ys) * videoHeight,
      bottom: Math.max(...ys) * videoHeight,
    };
  });
  const union = {
    left: Math.min(...bounds.map((item) => item.left)),
    right: Math.max(...bounds.map((item) => item.right)),
    top: Math.min(...bounds.map((item) => item.top)),
    bottom: Math.max(...bounds.map((item) => item.bottom)),
  };
  const handScale =
    bounds.reduce(
      (sum, item) =>
        sum + Math.max(item.right - item.left, item.bottom - item.top) / videoHeight,
      0,
    ) / bounds.length;
  const distance: HandDistance =
    handScale < 0.13 ? "too-far" : handScale > 0.38 ? "too-close" : "good";

  // A smaller hand means the signer is farther away, so use a tighter square.
  // The union guard keeps two widely separated hands inside that square.
  const distanceSide = clamp(handScale / 0.23, 0.6, 1) * videoHeight;
  const requiredSide = Math.max(
    union.right - union.left + videoHeight * 0.16,
    union.bottom - union.top + videoHeight * 0.28,
  );
  const side = clamp(Math.max(distanceSide, requiredSide), videoHeight * 0.6, videoHeight);

  const handCenterX = (union.left + union.right) / 2;
  const handCenterY = (union.top + union.bottom) / 2;
  let centerX = videoWidth * 0.5 * 0.7 + handCenterX * 0.3;
  let centerY = videoHeight * 0.47 * 0.76 + handCenterY * 0.24;

  // Shift just enough to retain every detected hand, while keeping head and
  // upper torso near the stable center learned from the training videos.
  const horizontalPadding = videoHeight * 0.06;
  const verticalPadding = videoHeight * 0.1;
  centerX = Math.min(centerX, union.left - horizontalPadding + side / 2);
  centerX = Math.max(centerX, union.right + horizontalPadding - side / 2);
  centerY = Math.min(centerY, union.top - verticalPadding + side / 2);
  centerY = Math.max(centerY, union.bottom + verticalPadding - side / 2);
  centerX = clamp(centerX, side / 2, videoWidth - side / 2);
  centerY = clamp(centerY, side / 2, videoHeight - side / 2);

  return {
    crop: {
      x: (centerX - side / 2) / videoWidth,
      y: (centerY - side / 2) / videoHeight,
      width: side / videoWidth,
      height: side / videoHeight,
    },
    distance,
    handScale,
  };
}

export function smoothCropRegion(
  previous: NormalizedCropRegion | null,
  next: NormalizedCropRegion,
  amount = 0.42,
): NormalizedCropRegion {
  if (!previous) return next;
  const mix = (from: number, to: number) => from + (to - from) * amount;
  return {
    x: mix(previous.x, next.x),
    y: mix(previous.y, next.y),
    width: mix(previous.width, next.width),
    height: mix(previous.height, next.height),
  };
}
