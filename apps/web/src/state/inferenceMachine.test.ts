import { describe, expect, it } from "vitest";
import type { PredictionMessage, PredictionStatus } from "@contracts";
import {
  inferenceReducer,
  initialInferenceState,
} from "./inferenceMachine";

function prediction(
  sequence: number,
  status: PredictionStatus,
): PredictionMessage {
  return {
    type: "prediction",
    sequence,
    status,
    label: status === "ok" ? "cảm ơn" : null,
    confidence: status === "ok" ? 0.9 : null,
    top_k: status === "ok" ? [{ label: "cảm ơn", confidence: 0.9 }] : [],
    model_version: "mock-common-20-v1",
  };
}

describe("inferenceReducer", () => {
  it.each<PredictionStatus>([
    "ok",
    "uncertain",
    "no_hands",
    "bad_framing",
    "busy",
    "error",
  ])("xử lý status %s", (status) => {
    const processing = inferenceReducer(initialInferenceState, {
      type: "request_started",
      sequence: 5,
    });
    const next = inferenceReducer(processing, {
      type: "prediction_received",
      prediction: prediction(5, status),
    });
    expect(next.phase).toBe(status);
    expect(next.pendingSequence).toBeNull();
  });

  it("bỏ qua prediction cũ hoặc sai thứ tự", () => {
    const processing = inferenceReducer(initialInferenceState, {
      type: "request_started",
      sequence: 8,
    });
    const next = inferenceReducer(processing, {
      type: "prediction_received",
      prediction: prediction(7, "ok"),
    });
    expect(next).toBe(processing);
  });

  it("xóa prediction cũ khi bắt đầu và hủy lượt capture mới", () => {
    const processing = inferenceReducer(initialInferenceState, {
      type: "request_started",
      sequence: 1,
    });
    const succeeded = inferenceReducer(processing, {
      type: "prediction_received",
      prediction: prediction(1, "ok"),
    });
    const capturing = inferenceReducer(succeeded, { type: "capture_started" });
    expect(capturing.phase).toBe("capturing");
    expect(capturing.prediction).toBeNull();

    const cancelled = inferenceReducer(capturing, {
      type: "capture_cancelled",
      message: "Đã hủy lượt thu.",
    });
    expect(cancelled.phase).toBe("ready");
    expect(cancelled.guidance).toBe("Đã hủy lượt thu.");
  });
});
