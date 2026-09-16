import type { PredictionMessage, PredictionStatus } from "@contracts";

export type InferencePhase =
  | "ready"
  | "capturing"
  | "processing"
  | "ok"
  | PredictionStatus
  | "disconnected";

export interface InferenceState {
  phase: InferencePhase;
  pendingSequence: number | null;
  prediction: PredictionMessage | null;
  guidance: string | null;
}

export type InferenceAction =
  | { type: "connection_ready" }
  | { type: "connection_lost" }
  | { type: "capture_started" }
  | { type: "capture_cancelled"; message: string }
  | { type: "request_started"; sequence: number }
  | { type: "prediction_received"; prediction: PredictionMessage }
  | { type: "failed"; message: string };

export const initialInferenceState: InferenceState = {
  phase: "disconnected",
  pendingSequence: null,
  prediction: null,
  guidance: null,
};

export function inferenceReducer(
  state: InferenceState,
  action: InferenceAction,
): InferenceState {
  switch (action.type) {
    case "connection_ready":
      return state.phase === "disconnected"
        ? { ...state, phase: "ready", guidance: null }
        : state;
    case "connection_lost":
      return {
        ...state,
        phase: "disconnected",
        pendingSequence: null,
        prediction: null,
      };
    case "capture_started":
      if (state.pendingSequence !== null) return state;
      return {
        ...state,
        phase: "capturing",
        prediction: null,
        guidance: null,
      };
    case "capture_cancelled":
      return { ...state, phase: "ready", guidance: action.message };
    case "request_started":
      return {
        ...state,
        phase: "processing",
        pendingSequence: action.sequence,
        prediction: null,
        guidance: null,
      };
    case "prediction_received":
      if (
        state.pendingSequence === null ||
        action.prediction.sequence !== state.pendingSequence
      ) {
        return state;
      }
      return {
        phase: action.prediction.status,
        pendingSequence: null,
        prediction: action.prediction,
        guidance: null,
      };
    case "failed":
      return {
        ...state,
        phase: "error",
        pendingSequence: null,
        guidance: action.message,
      };
  }
}
