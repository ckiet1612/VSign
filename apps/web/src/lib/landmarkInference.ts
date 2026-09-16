import type { PredictionMessage } from "@contracts";
import {
  hasHandLandmarks,
  LANDMARK_FEATURE_DIM,
  LANDMARK_SEQUENCE_LENGTH,
  mirrorLandmarkFrame,
} from "./landmarkFeatures";

export const LANDMARK_MODEL_VERSION = "unified-landmark-v4.2-personalized";
export const BASELINE_MODEL_VERSION = "landmark-keyframe-v3-personalized";
export const V5_MODEL_VERSION = "guarded-landmark-v5-bootstrap";
export type LandmarkRuntime = "v3" | "v4_2" | "v5";
export const DEFAULT_LANDMARK_RUNTIME: LandmarkRuntime = "v3";
export const LOCAL_CONFIDENCE_THRESHOLD = 0.56;
export const LOCAL_MARGIN_THRESHOLD = 0.18;
export const MINIMUM_DETECTED_FRAMES = 4;
export const IDLE_LABEL = "Không ký hiệu";

export interface PredictionThresholds {
  confidence: number;
  margin: number;
}

export interface PredictionRuntime {
  modelVersion: string;
  hasHands: (frame: readonly number[]) => boolean;
}

export function flattenLandmarkSequence(
  frames: readonly (readonly number[])[],
  featureDim = LANDMARK_FEATURE_DIM,
): Float32Array {
  if (frames.length !== LANDMARK_SEQUENCE_LENGTH) {
    throw new Error(`AI cần đúng ${LANDMARK_SEQUENCE_LENGTH} frame điểm tay.`);
  }
  const output = new Float32Array(
    LANDMARK_SEQUENCE_LENGTH * featureDim,
  );
  frames.forEach((frame, index) => {
    if (frame.length !== featureDim) {
      throw new Error(`Frame ${index + 1} không đủ điểm tay.`);
    }
    output.set(frame, index * featureDim);
  });
  return output;
}

export function mirrorLandmarkSequence(
  frames: readonly (readonly number[])[],
): number[][] {
  return frames.map((frame) => mirrorLandmarkFrame(frame));
}

export function landmarkInferenceViews(
  frames: readonly (readonly number[])[],
): number[][][] {
  return [frames.map((frame) => Array.from(frame)), mirrorLandmarkSequence(frames)];
}

export function flattenLandmarkBatch(
  sequences: readonly (readonly (readonly number[])[])[],
  featureDim = LANDMARK_FEATURE_DIM,
): Float32Array {
  if (!sequences.length) throw new Error("AI cần ít nhất một chuỗi điểm tay.");
  const sequenceSize = LANDMARK_SEQUENCE_LENGTH * featureDim;
  const output = new Float32Array(sequences.length * sequenceSize);
  sequences.forEach((sequence, index) => {
    output.set(flattenLandmarkSequence(sequence, featureDim), index * sequenceSize);
  });
  return output;
}

export function averageLogitViews(
  logits: readonly number[],
  viewCount: number,
  labelCount: number,
): number[] {
  if (
    !Number.isInteger(viewCount) ||
    viewCount <= 0 ||
    !Number.isInteger(labelCount) ||
    labelCount <= 0 ||
    logits.length !== viewCount * labelCount
  ) {
    throw new Error("Kích thước kết quả ensemble của AI không hợp lệ.");
  }
  const averaged = new Array<number>(labelCount).fill(0);
  for (let view = 0; view < viewCount; view += 1) {
    for (let label = 0; label < labelCount; label += 1) {
      averaged[label] += logits[view * labelCount + label] / viewCount;
    }
  }
  return averaged;
}

export function weightedLogitEnsemble(
  models: readonly { logits: readonly number[]; weight: number }[],
): number[] {
  if (!models.length) throw new Error("AI cần ít nhất một model để ensemble.");
  const labelCount = models[0].logits.length;
  if (!labelCount || models.some((model) => model.logits.length !== labelCount)) {
    throw new Error("Các model AI không có cùng số nhãn.");
  }
  const totalWeight = models.reduce((sum, model) => sum + model.weight, 0);
  if (!Number.isFinite(totalWeight) || totalWeight <= 0) {
    throw new Error("Trọng số ensemble của AI không hợp lệ.");
  }
  const output = new Array<number>(labelCount).fill(0);
  for (const model of models) {
    const mean =
      model.logits.reduce((sum, value) => sum + value, 0) / labelCount;
    const variance =
      model.logits.reduce((sum, value) => sum + (value - mean) ** 2, 0) /
      Math.max(1, labelCount - 1);
    const deviation = Math.max(Math.sqrt(variance), 1e-6);
    for (let label = 0; label < labelCount; label += 1) {
      output[label] +=
        ((model.logits[label] - mean) / deviation) *
        (model.weight / totalWeight);
    }
  }
  return output;
}

export function selectFocusedExpertLogits(
  generalLogits: readonly number[],
  expertLogits: readonly number[],
  labels: readonly string[],
  focusLabels: readonly string[],
  thresholds: PredictionThresholds,
): number[] {
  if (
    generalLogits.length !== expertLogits.length ||
    labels.length !== expertLogits.length
  ) {
    throw new Error("Kết quả model chuyên gia không khớp model chính.");
  }
  const probabilities = softmax(expertLogits);
  const ranked = probabilities
    .map((confidence, index) => ({ index, confidence }))
    .sort((left, right) => right.confidence - left.confidence);
  const best = ranked[0];
  const margin = best.confidence - (ranked[1]?.confidence ?? 0);
  const useExpert =
    focusLabels.includes(labels[best.index]) &&
    best.confidence >= thresholds.confidence &&
    margin >= thresholds.margin;
  return Array.from(useExpert ? expertLogits : generalLogits);
}

function softmax(logits: readonly number[]): number[] {
  const maximum = Math.max(...logits);
  const exponentials = logits.map((value) => Math.exp(value - maximum));
  const total = exponentials.reduce((sum, value) => sum + value, 0);
  return exponentials.map((value) => value / total);
}

export function predictionFromLogits(
  logits: readonly number[],
  labels: readonly string[],
  frames: readonly (readonly number[])[],
  sequence: number,
  thresholds: PredictionThresholds = {
    confidence: LOCAL_CONFIDENCE_THRESHOLD,
    margin: LOCAL_MARGIN_THRESHOLD,
  },
  runtime: PredictionRuntime = {
    modelVersion: LANDMARK_MODEL_VERSION,
    hasHands: hasHandLandmarks,
  },
): PredictionMessage {
  const detectedFrames = frames.filter(runtime.hasHands).length;
  if (detectedFrames < MINIMUM_DETECTED_FRAMES) {
    return {
      type: "prediction",
      sequence,
      status: "no_hands",
      label: null,
      confidence: null,
      top_k: [],
      model_version: runtime.modelVersion,
    };
  }
  if (logits.length !== labels.length || !logits.length) {
    throw new Error("Số đầu ra của model không khớp nhãn.");
  }
  const probabilities = softmax(logits);
  const rankedAll = probabilities
    .map((confidence, index) => ({ label: labels[index], confidence }))
    .sort((left, right) => right.confidence - left.confidence);
  const ranked = rankedAll.filter((candidate) => candidate.label !== IDLE_LABEL).slice(0, 3);
  const confidence = rankedAll[0].confidence;
  const margin = confidence - (rankedAll[1]?.confidence ?? 0);
  if (rankedAll[0].label === IDLE_LABEL) {
    return {
      type: "prediction",
      sequence,
      status: "uncertain",
      label: null,
      confidence: null,
      top_k: ranked,
      model_version: runtime.modelVersion,
    };
  }
  const accepted =
    confidence >= thresholds.confidence && margin >= thresholds.margin;
  return {
    type: "prediction",
    sequence,
    status: accepted ? "ok" : "uncertain",
    label: accepted ? rankedAll[0].label : null,
    confidence: accepted ? confidence : null,
    top_k: ranked,
    model_version: runtime.modelVersion,
  };
}
