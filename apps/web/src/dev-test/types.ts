import type { CaptureDistance, CaptureLighting, CollectionHand, NegativeAction } from "@contracts";

export type Outcome = "correct" | "wrong" | "uncertain" | "correct_rejection" | "false_accept" | "technical_error";
export interface Runtime {
  enabled: boolean; backend: string; model_version: string; runtime_key: string; labels: string[];
  confidence_threshold: number; margin_threshold: number; mock: boolean; candidate_labels_unverified: boolean;
}
export interface TestContext {
  expected_label: string; signer_id: string; hand: CollectionHand; distance: CaptureDistance;
  lighting: CaptureLighting; negative_action: NegativeAction | null;
}
export interface TestPayload extends TestContext {
  trial_id: string; session_id: string; captured_at: number; duration_ms: number; frames: string[];
  source_frames: string[]; runtime_key: string; pipeline: "manual-server-uniform-center-square-v1";
  technical_error?: string;
}
export interface Review { valid: boolean; notes: string; reviewer: string | null; reviewed_at?: string }
export interface Trial extends TestContext {
  trial_id: string; session_id: string; captured_at: number; duration_ms: number; outcome: Outcome;
  prediction: { status: string; label: string | null; confidence: number | null; top_k: { label: string; confidence: number }[] } | null;
  model_version: string; runtime_key: string; inference_ms: number | null; video_available: boolean;
  review: Review; review_history: Review[]; error_stage: string | null;
}
export interface Counts {
  recorded: number; excluded: number; evaluated: number; technical_error: number;
  correct: number; wrong: number; uncertain: number; correct_rejection: number; false_accept: number;
  correct_pct: number | null; wrong_pct: number | null; uncertain_pct: number | null;
  correct_rejection_pct: number | null; false_accept_pct: number | null; wrong_labels: Record<string, number>;
}
export interface Summary {
  recorded: number; independent_evaluation: boolean;
  groups: { runtime_key: string; session_id: string; model_version: string; confidence_threshold: number;
    margin_threshold: number; positive: Counts; negative: Counts; per_word: (Counts & { label: string })[] }[];
}
export const outcomeText: Record<Outcome, string> = {
  correct: "Đúng", wrong: "Nhận nhầm", uncertain: "Không xác định", correct_rejection: "Từ chối đúng",
  false_accept: "Chấp nhận sai", technical_error: "Lỗi kỹ thuật",
};
