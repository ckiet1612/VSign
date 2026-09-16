import { describe, expect, it } from "vitest";
import { isPredictionMessage } from "@contracts";

const validPrediction = {
  type: "prediction",
  sequence: 2,
  status: "ok",
  label: "xin chào",
  confidence: 0.88,
  top_k: [{ label: "xin chào", confidence: 0.88 }],
  model_version: "mock-common-20-v1",
};

describe("isPredictionMessage", () => {
  it("chấp nhận response đầy đủ và đúng kiểu", () => {
    expect(isPredictionMessage(validPrediction)).toBe(true);
  });

  it.each([
    { ...validPrediction, sequence: Number.MAX_SAFE_INTEGER + 1 },
    { ...validPrediction, confidence: "0.88" },
    { ...validPrediction, confidence: Number.NaN },
    { ...validPrediction, label: null },
    { ...validPrediction, top_k: [null] },
    {
      ...validPrediction,
      top_k: [{ label: "xin chào", confidence: "0.88" }],
    },
    { ...validPrediction, top_k: [] },
    { ...validPrediction, model_version: "" },
  ])("từ chối response có thể làm UI lỗi: %#", (response) => {
    expect(isPredictionMessage(response)).toBe(false);
  });
});
