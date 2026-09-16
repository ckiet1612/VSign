import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { PredictionMessage } from "@contracts";
import { ResultPanel } from "./ResultPanel";

const previousPrediction: PredictionMessage = {
  type: "prediction",
  sequence: 1,
  status: "ok",
  label: "cảm ơn",
  confidence: 0.9,
  top_k: [{ label: "cảm ơn", confidence: 0.9 }],
  model_version: "mock-common-20-v1",
};

describe("ResultPanel", () => {
  it("không cho thêm prediction cũ khi request mới đang xử lý", () => {
    render(
      <ResultPanel
        phase="processing"
        prediction={previousPrediction}
        guidance={null}
        onAdd={vi.fn()}
        canUseLabels
      />,
    );
    expect(screen.getByRole("button", { name: "Thêm vào câu" })).toBeDisabled();
  });

  it("không ghép câu khi label map chưa được xác minh", () => {
    render(
      <ResultPanel
        phase="ok"
        prediction={{ ...previousPrediction, label: "Ký hiệu #0136" }}
        guidance={null}
        onAdd={vi.fn()}
        canUseLabels={false}
      />,
    );
    expect(screen.getByRole("button", { name: "Thêm vào câu" })).toBeDisabled();
    expect(screen.getByText(/checkpoint và label map cùng phiên bản/)).toBeInTheDocument();
  });
});
