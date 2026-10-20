export const TARGET_FRAME_COUNT = 16;
export const MIN_CAPTURE_MS = 650;
export const MAX_CAPTURE_MS = 3_000;
export const MAX_CAPTURED_BITMAPS = 42;

export interface CaptureValidation {
  valid: boolean;
  message: string | null;
}

export type CaptureSamplingStrategy = "uniform" | "motion-weighted";

function roundHalfToEven(value: number): number {
  const lower = Math.floor(value);
  const fraction = value - lower;
  if (Math.abs(fraction - 0.5) <= 1e-9) {
    return lower % 2 === 0 ? lower : lower + 1;
  }
  return Math.round(value);
}

export function validateCaptureDuration(durationMs: number): CaptureValidation {
  if (!Number.isFinite(durationMs) || durationMs < MIN_CAPTURE_MS) {
    return {
      valid: false,
      message: "Giữ lâu hơn một chút và thực hiện trọn vẹn một ký hiệu.",
    };
  }
  if (durationMs > MAX_CAPTURE_MS + 150) {
    return {
      valid: false,
      message: "Ký hiệu quá dài. Hãy thử lại trong tối đa 3 giây.",
    };
  }
  return { valid: true, message: null };
}

export function uniformSampleIndices(length: number, count: number): number[] {
  if (!Number.isInteger(length) || length <= 0) {
    throw new Error("Không có frame để lấy mẫu.");
  }
  if (!Number.isInteger(count) || count <= 0) {
    throw new Error("Số frame đích phải lớn hơn 0.");
  }
  if (count === 1) return [Math.floor((length - 1) / 2)];
  return Array.from({ length: count }, (_, index) =>
    roundHalfToEven((index * (length - 1)) / (count - 1)),
  );
}

export function uniformSample<T>(items: readonly T[], count: number): T[] {
  return uniformSampleIndices(items.length, count).map((index) => items[index]);
}

/**
 * Keep the complete trajectory while spending more of the fixed frame budget
 * around meaningful motion. The first/last frame are always retained and the
 * strongest transition is explicitly represented.
 */
export function motionWeightedSampleIndices(
  length: number,
  count: number,
  motionScores: readonly number[],
): number[] {
  if (motionScores.length !== length) {
    throw new Error("Motion score phải khớp số frame nguồn.");
  }
  if (length <= count) return uniformSampleIndices(length, count);

  const motion = motionScores.map((value) =>
    Number.isFinite(value) ? Math.max(0, value) : 0,
  );
  const peak = Math.max(...motion);
  if (peak <= 1e-8) return uniformSampleIndices(length, count);

  // A non-zero base weight preserves slow/static portions; motion only biases
  // the density and therefore cannot collapse the sequence to one keyframe.
  const weights = motion.map((value) => 0.6 + Math.min(value / peak, 2) * 1.4);
  const cumulative: number[] = [];
  let total = 0;
  for (const weight of weights) {
    total += weight;
    cumulative.push(total);
  }

  const chosen = new Set<number>([0, length - 1]);
  for (let slot = 1; slot < count - 1; slot += 1) {
    const target = (total * slot) / (count - 1);
    const index = cumulative.findIndex((value) => value >= target);
    chosen.add(Math.max(1, Math.min(length - 2, index)));
  }

  // Guarantee that the most informative transition reaches the model.
  const peakIndex = motion.indexOf(peak);
  if (peakIndex > 0 && peakIndex < length - 1 && !chosen.has(peakIndex)) {
    const replaceable = [...chosen]
      .filter((index) => index > 0 && index < length - 1)
      .sort(
        (left, right) =>
          Math.abs(left - peakIndex) - Math.abs(right - peakIndex),
      )[0];
    if (replaceable !== undefined) chosen.delete(replaceable);
    chosen.add(peakIndex);
  }

  for (const index of uniformSampleIndices(length, count)) {
    if (chosen.size >= count) break;
    chosen.add(index);
  }
  for (let index = 1; chosen.size < count && index < length - 1; index += 1) {
    chosen.add(index);
  }
  return [...chosen].sort((left, right) => left - right);
}

export function motionWeightedSample<T>(
  items: readonly T[],
  count: number,
  motionScores: readonly number[],
): T[] {
  return motionWeightedSampleIndices(items.length, count, motionScores).map(
    (index) => items[index],
  );
}

export function captureSampleIndices(
  length: number,
  count: number,
  motionScores: readonly number[],
  strategy: CaptureSamplingStrategy,
): number[] {
  return strategy === "uniform"
    ? uniformSampleIndices(length, count)
    : motionWeightedSampleIndices(length, count, motionScores);
}
