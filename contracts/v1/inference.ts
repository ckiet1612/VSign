export const PROTOCOL_VERSION = "1.0" as const;
export const FRAME_COUNT = 16 as const;
export const FRAME_SIZE = 224 as const;

export type PredictionStatus =
  | "ok"
  | "uncertain"
  | "no_hands"
  | "bad_framing"
  | "busy"
  | "error";

export interface FramesMessage {
  type: "frames";
  session_id: string;
  sequence: number;
  captured_at: number;
  frames: string[];
  /** Words already in the sentence (at most 8); the runtime may rank this sign with them. */
  context_words?: string[];
}

export interface PredictionCandidate {
  label: string;
  confidence: number;
}

export interface PredictionMessage {
  type: "prediction";
  sequence: number;
  status: PredictionStatus;
  label: string | null;
  confidence: number | null;
  top_k: PredictionCandidate[];
  model_version: string;
  /** Decision steps that changed the fixed-threshold result; absent on older runtimes. */
  adjusted?: PredictionAdjustment[];
}

export type PredictionAdjustment = "calibrated" | "context";

export interface InferenceMetadata {
  backend: string;
  model_version: string;
  protocol_version: string;
  frame_count: number;
  frame_width: number;
  frame_height: number;
  supported_image_formats: string[];
  confidence_threshold: number;
  margin_threshold: number;
  labels: string[];
  collection_labels: string[];
  candidate_labels_unverified: boolean;
  mock: boolean;
  collection_enabled: boolean;
  collection_target_per_hand: number;
  sentence_ai_enabled: boolean;
  /** Absent on older runtimes, which always expect the center square. */
  input_framing?: InputFraming;
}

export type InputFraming = "center-square" | "trim-bodycrop-v1";

export interface SentenceComposeRequest {
  words: string[];
}

export interface SentenceComposeResponse {
  sentence: string;
  provider: "openai" | "local";
  model: string | null;
  warnings?: string[];
}

export type CollectionHand = "right" | "left";
export type CaptureDistance = "near" | "standard" | "far";
export type CaptureLighting = "normal" | "low" | "side";
export type NegativeAction =
  | "still"
  | "hand_enter_exit"
  | "adjust_hair_glasses"
  | "touch_face"
  | "turn_body"
  | "random_motion"
  | "overlap_hands"
  | "other_sign";

export interface CollectionSampleRequest {
  session_id: string;
  batch?: "personal-100";
  sample_key?: string;
  captured_at: number;
  duration_ms: number;
  expected_label: string;
  hand: CollectionHand;
  frames: string[];
  predicted_label: string | null;
  predicted_confidence: number | null;
  distance: CaptureDistance;
  lighting: CaptureLighting;
  negative_action: NegativeAction | null;
}

export interface CollectionHandCounts {
  right: number;
  left: number;
}

export interface CollectionSummaryResponse {
  enabled: boolean;
  target_per_hand: number;
  counts: Record<string, CollectionHandCounts>;
  batch?: "personal-100" | null;
  target_per_label?: number | null;
}

export interface CollectionSampleResponse {
  status: "saved";
  sample_id: string;
  expected_label: string;
  hand: CollectionHand;
  relative_video_path: string;
  label_hand_count: number;
  label_count?: number | null;
}

const predictionStatuses: ReadonlySet<PredictionStatus> = new Set([
  "ok",
  "uncertain",
  "no_hands",
  "bad_framing",
  "busy",
  "error",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isConfidence(value: unknown): value is number {
  return (
    typeof value === "number" &&
    Number.isFinite(value) &&
    value >= 0 &&
    value <= 1
  );
}

function isPredictionCandidate(value: unknown): value is PredictionCandidate {
  if (!isRecord(value)) return false;
  return (
    typeof value.label === "string" &&
    value.label.trim().length > 0 &&
    isConfidence(value.confidence)
  );
}

export function isPredictionMessage(value: unknown): value is PredictionMessage {
  if (!isRecord(value)) return false;
  if (
    value.type !== "prediction" ||
    !Number.isSafeInteger(value.sequence) ||
    (value.sequence as number) < 0 ||
    typeof value.status !== "string" ||
    !predictionStatuses.has(value.status as PredictionStatus) ||
    (value.label !== null &&
      (typeof value.label !== "string" || value.label.trim().length === 0)) ||
    (value.confidence !== null && !isConfidence(value.confidence)) ||
    !Array.isArray(value.top_k) ||
    value.top_k.length > 3 ||
    !value.top_k.every(isPredictionCandidate) ||
    typeof value.model_version !== "string" ||
    value.model_version.trim().length === 0 ||
    (value.adjusted !== undefined &&
      (!Array.isArray(value.adjusted) ||
        !value.adjusted.every((item) => item === "calibrated" || item === "context")))
  ) {
    return false;
  }

  if (value.status === "ok") {
    return (
      typeof value.label === "string" &&
      isConfidence(value.confidence) &&
      value.top_k.length > 0
    );
  }
  return true;
}
