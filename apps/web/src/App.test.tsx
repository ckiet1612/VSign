import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

class MockWebSocket {
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;

  constructor(url: string) {
    void url;
  }
  send(payload: string) {
    void payload;
  }
  close() {}
}

describe("App", () => {
  beforeEach(() => {
    vi.stubGlobal("WebSocket", MockWebSocket);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          backend: "mock",
          model_version: "mock-common-20-v1",
          protocol_version: "1.0",
          frame_count: 16,
          frame_width: 224,
          frame_height: 224,
          supported_image_formats: ["image/jpeg", "image/webp"],
          confidence_threshold: 0.7,
          margin_threshold: 0.15,
          labels: [],
          candidate_labels_unverified: true,
          mock: true,
          collection_enabled: false,
          collection_target_per_hand: 5,
        }),
      }),
    );
  });

  it("hiển thị cảnh báo mock và accessible names cho control chính", () => {
    render(<App />);
    expect(
      screen.getByText("Mô phỏng – chưa dùng mô hình AI thật."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Bật camera" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Giữ để ký, cũng có thể giữ phím Space",
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Thêm vào câu" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Hoàn tác từ cuối" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Xóa toàn bộ câu" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Sao chép câu" })).toBeDisabled();
  });

  it("phân biệt baseline legacy với model nguồn mới", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          backend: "pytorch",
          model_version: "multivsl1000-official-class-id-v1",
          protocol_version: "1.0",
          frame_count: 16,
          frame_width: 224,
          frame_height: 224,
          supported_image_formats: ["image/jpeg", "image/webp"],
          confidence_threshold: 0.7,
          margin_threshold: 0.15,
          labels: [],
          candidate_labels_unverified: true,
          mock: false,
          collection_enabled: false,
          collection_target_per_hand: 5,
        }),
      }),
    );

    render(<App />);
    expect(
      await screen.findByText("AI baseline legacy đang hoạt động."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/chưa phải model common‑20 của nguồn mới/),
    ).toBeInTheDocument();
  });

  it("mở chế độ thu dữ liệu khi backend cho phép", async () => {
    const labels = ["Chào", "Cảm ơn", "Cho"];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((input: string | URL | Request) => {
        const url = String(input);
        if (url.endsWith("/collection/summary")) {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              enabled: true,
              target_per_hand: 5,
              counts: {
                Chào: { right: 2, left: 1 },
                "Cảm ơn": { right: 0, left: 0 },
                Cho: { right: 0, left: 0 },
              },
            }),
          });
        }
        return Promise.resolve({
          ok: true,
          json: async () => ({
            backend: "onnx",
            model_version: "visignlanguage-common20-mvitv2s-epoch5",
            protocol_version: "1.0",
            frame_count: 16,
            frame_width: 224,
            frame_height: 224,
            supported_image_formats: ["image/jpeg", "image/webp"],
            confidence_threshold: 0.7,
            margin_threshold: 0.15,
            labels,
            candidate_labels_unverified: false,
            mock: false,
            collection_enabled: true,
            collection_target_per_hand: 5,
          }),
        });
      }),
    );
    const user = userEvent.setup();

    render(<App />);
    const collectionButton = await screen.findByRole("button", {
      name: "Thu dữ liệu AI",
    });
    expect(collectionButton).toBeEnabled();
    await user.click(collectionButton);

    expect(
      screen.getByRole("heading", { name: "Chọn mẫu cần quay" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Từ cần thực hiện" })).toHaveValue(
      "Chào",
    );
    expect(screen.getByText("2/35 · Tay phải")).toBeInTheDocument();
    expect(
      screen.getByLabelText("Video mẫu cho từ Chào"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Thêm vào câu" })).not.toBeInTheDocument();
  });
});
