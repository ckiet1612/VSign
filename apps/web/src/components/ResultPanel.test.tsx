import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

const insertionProps = {
  wordInsertionMode: "manual" as const,
  onWordInsertionModeChange: vi.fn(),
  automaticInsertionAvailable: true,
  automaticAdded: false,
};

describe("ResultPanel", () => {
  it("chỉ báo đã xét ngữ cảnh câu khi server dùng ngữ cảnh", () => {
    const view = render(<ResultPanel {...insertionProps} phase="ok"
      prediction={{ ...previousPrediction, adjusted: ["calibrated", "context"] }}
      guidance={null} onAdd={vi.fn()} canUseLabels />);
    expect(screen.getByText("Đã xét ngữ cảnh câu")).toBeInTheDocument();
    view.rerender(<ResultPanel {...insertionProps} phase="ok"
      prediction={{ ...previousPrediction, adjusted: ["calibrated"] }}
      guidance={null} onAdd={vi.fn()} canUseLabels />);
    expect(screen.queryByText("Đã xét ngữ cảnh câu")).not.toBeInTheDocument();
  });
  it("hiển thị tiêu đề riêng cho khung kết quả và giữ nút thêm cạnh dự đoán", () => {
    render(<ResultPanel {...insertionProps} phase="ok" prediction={previousPrediction}
      guidance={null} onAdd={vi.fn()} canUseLabels />);
    expect(screen.getByRole("heading", { name: "Kết quả nhận dạng" })).not.toHaveClass("sr-only");
    const entry = document.querySelector(".result-entry");
    expect(entry).toContainElement(screen.getByRole("button", { name: "Thêm vào câu" }));
    expect(entry).toContainElement(document.querySelector(".primary-prediction"));
  });
  it("giữ kết quả chưa bắt đầu và cấu hình thêm từ khi camera tắt, không giấu lỗi", async () => {
    const view = render(<ResultPanel {...insertionProps} phase="ready" prediction={null}
      guidance={null} onAdd={vi.fn()} canUseLabels cameraReady={false} />);
    expect(view.container.querySelector(".result-panel")).toBeVisible();
    expect(screen.getByText("Chưa bắt đầu", { exact: true })).toBeVisible();
    expect(screen.queryByText("Sẵn sàng", { exact: true })).not.toBeInTheDocument();
    await userEvent.click(screen.getByText("Cách thêm từ", { exact: true }));
    expect(screen.getByRole("radio", { name: "Thêm từ thủ công" })).toBeChecked();
    view.rerender(<ResultPanel {...insertionProps} phase="disconnected" prediction={null}
      guidance={null} onAdd={vi.fn()} canUseLabels cameraReady={false} />);
    expect(screen.getByText(/Mất kết nối tới máy chủ/)).toBeVisible();
  });

  it("đưa lựa chọn thêm từ vào mục mở rộng và giữ mặc định thủ công", async () => {
    render(<ResultPanel {...insertionProps} phase="ready" prediction={null}
      guidance={null} onAdd={vi.fn()} canUseLabels />);
    const manual = screen.getByRole("radio", { name: "Thêm từ thủ công", hidden: true });
    expect(manual).toBeChecked();
    expect(manual).not.toBeVisible();
    await userEvent.click(screen.getByText("Cách thêm từ", { exact: true }));
    expect(screen.getByRole("radio", { name: "Thêm từ thủ công" })).toBeVisible();
  });

  it("không lặp hướng dẫn và gợi ý trống khi chưa có dự đoán", () => {
    const { container } = render(<ResultPanel {...insertionProps} phase="ready" prediction={null}
      guidance={null} onAdd={vi.fn()} canUseLabels />);
    expect(container.querySelector(".phase-message")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Top 3 gợi ý" })).not.toBeInTheDocument();
    expect(screen.getByText("Chưa có kết quả")).toBeInTheDocument();
  });

  it("giữ thông báo có thể hành động ngay cả khi trạng thái sẵn sàng", () => {
    render(<ResultPanel {...insertionProps} phase="ready" prediction={null}
      guidance="Lượt ký quá ngắn, hãy thử lại." onAdd={vi.fn()} canUseLabels />);
    expect(screen.getByText("Lượt ký quá ngắn, hãy thử lại.")).toBeInTheDocument();
  });

  it("giữ hướng dẫn khi kết quả chưa chắc chắn", () => {
    render(<ResultPanel {...insertionProps} phase="uncertain" prediction={previousPrediction}
      guidance={null} onAdd={vi.fn()} canUseLabels />);
    expect(screen.getByText(/Chưa nhận ra rõ/)).toBeInTheDocument();
  });
  it.each([
    ["ready", "Sẵn sàng"],
    ["capturing", "Đang thu"],
    ["processing", "Đang nhận dạng"],
    ["uncertain", "Chưa chắc chắn"],
    ["no_hands", "Chưa thấy tay"],
    ["bad_framing", "Cần chỉnh khung"],
    ["busy", "Máy chủ bận"],
    ["error", "Nhận dạng lỗi"],
    ["disconnected", "Mất kết nối"],
  ] as const)("hiển thị trạng thái %s mà không báo chờ xác nhận", (phase, label) => {
    render(<ResultPanel {...insertionProps} phase={phase} prediction={null}
      guidance={null} onAdd={vi.fn()} canUseLabels />);
    expect(screen.getByText(label, { exact: true })).toBeInTheDocument();
    expect(screen.queryByText("Chờ xác nhận", { exact: true })).not.toBeInTheDocument();
    expect(document.querySelector(".add-button")).toBeDisabled();
  });

  it("phân biệt dự đoán trước với lượt mới đang xử lý", () => {
    render(<ResultPanel {...insertionProps} phase="processing" prediction={previousPrediction}
      guidance={null} onAdd={vi.fn()} canUseLabels />);
    expect(screen.getByText("Kết quả lượt trước")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Thêm vào câu" })).toBeDisabled();
  });

  it("không cho thêm prediction cũ khi request mới đang xử lý", () => {
    render(
      <ResultPanel
        {...insertionProps}
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
        {...insertionProps}
        phase="ok"
        prediction={{ ...previousPrediction, label: "Ký hiệu #0136" }}
        guidance={null}
        onAdd={vi.fn()}
        canUseLabels={false}
      />,
    );
    expect(screen.getByRole("button", { name: "Thêm vào câu" })).toBeDisabled();
    expect(screen.getByText("Chưa xác minh nhãn của mô hình.")).toBeInTheDocument();
  });

  it("tách lựa chọn thêm từ khỏi cách thu ký hiệu", async () => {
    const onModeChange = vi.fn();
    render(
      <ResultPanel
        {...insertionProps}
        phase="ready" prediction={null} guidance={null} onAdd={vi.fn()} canUseLabels
        automaticCapture onWordInsertionModeChange={onModeChange}
      />,
    );
    expect(screen.getByRole("radio", { name: "Thêm từ thủ công" })).toBeChecked();
    await userEvent.click(screen.getByText("Cách thêm từ", { exact: true }));
    await userEvent.click(screen.getByRole("radio", { name: "Thêm từ tự động" }));
    expect(onModeChange).toHaveBeenCalledWith("automatic");
  });

  it("ẩn nút thêm bằng click và báo kết quả đã tự thêm", () => {
    render(
      <ResultPanel
        {...insertionProps}
        phase="ok" prediction={previousPrediction} guidance={null} onAdd={vi.fn()} canUseLabels
        wordInsertionMode="automatic" automaticAdded
      />,
    );
    expect(screen.queryByRole("button", { name: "Thêm vào câu" })).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Đã tự thêm vào câu.");
  });

  it("báo tạm dừng khi model chưa hợp lệ", () => {
    render(
      <ResultPanel
        {...insertionProps}
        phase="ok" prediction={previousPrediction} guidance={null} onAdd={vi.fn()} canUseLabels={false}
        wordInsertionMode="automatic" automaticInsertionAvailable={false}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Tự động thêm đang tạm dừng.");
    expect(screen.queryByRole("button", { name: "Thêm vào câu" })).not.toBeInTheDocument();
  });

  it("không hiển thị lựa chọn thêm từ trong luồng thu dữ liệu", () => {
    render(
      <ResultPanel
        {...insertionProps}
        phase="ok" prediction={previousPrediction} guidance={null} onAdd={vi.fn()} canUseLabels
        collectionReview
      />,
    );
    expect(screen.queryByRole("radio", { name: "Thêm từ tự động" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Thêm vào câu" })).not.toBeInTheDocument();
  });
});
