export interface DisplayRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface NormalizedPoint {
  x: number;
  y: number;
}

function positive(value: number): number {
  return Number.isFinite(value) && value > 0 ? value : 0;
}

export function containedVideoRect(
  containerWidth: number,
  containerHeight: number,
  videoWidth: number,
  videoHeight: number,
): DisplayRect {
  const width = positive(containerWidth);
  const height = positive(containerHeight);
  const sourceWidth = positive(videoWidth);
  const sourceHeight = positive(videoHeight);
  if (!width || !height || !sourceWidth || !sourceHeight) {
    return { x: 0, y: 0, width, height };
  }

  const scale = Math.min(width / sourceWidth, height / sourceHeight);
  const displayedWidth = sourceWidth * scale;
  const displayedHeight = sourceHeight * scale;
  return {
    x: (width - displayedWidth) / 2,
    y: (height - displayedHeight) / 2,
    width: displayedWidth,
    height: displayedHeight,
  };
}

export function mirroredDisplayPoint(
  point: NormalizedPoint,
  rect: DisplayRect,
): NormalizedPoint {
  const x = Math.min(1, Math.max(0, point.x));
  const y = Math.min(1, Math.max(0, point.y));
  return {
    x: rect.x + (1 - x) * rect.width,
    y: rect.y + y * rect.height,
  };
}
