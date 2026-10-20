import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

vi.mock("./hooks/useWorkspacePlatform", async () => {
  const { localWorkspacePlatform } = await import("./test/workspacePlatformFixture");
  return { useWorkspacePlatform: localWorkspacePlatform };
});

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
    window.history.replaceState({}, "", "/");
    vi.stubGlobal("WebSocket", MockWebSocket);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async (input: string | URL | Request) => ({
        ok: true,
        json: async () => String(input).endsWith("/health") ? ({ status: "ok", backend: "mock", model_version: "mock-common-20-v1", protocol_version: "1.0" }) : ({
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
          collection_labels: [],
          candidate_labels_unverified: true,
          mock: true,
          collection_enabled: false,
          collection_target_per_hand: 5,
          sentence_ai_enabled: false,
        }),
      })),
    );
  });

  it("đặt nội dung câu trước dự đoán và đưa thu dữ liệu vào công cụ phụ", async () => {
    render(<App />);
    const transcript = screen.getByRole("region", { name: "Câu của bạn" });
    const result = screen.getByRole("region", { name: "Kết quả nhận dạng", hidden: true });
    expect(transcript).not.toContainElement(result);
    expect(transcript.nextElementSibling).toBe(result);
    expect(screen.getByRole("button", { name: "Thu dữ liệu AI", hidden: true })).not.toBeVisible();
    await userEvent.click(screen.getByText("Công cụ", { exact: true }));
    expect(screen.getByRole("button", { name: "Thu dữ liệu AI" })).toBeVisible();
  });

  it("điều hướng sidebar sang trang model mà không đổi workflow nhận dạng", async () => {
    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Mô hình nhận dạng" }));
    expect(screen.getByRole("heading", { name: "Mô hình nhận dạng" })).toBeInTheDocument();
    expect(screen.queryByText("Protocol 1.0", { exact: true })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Đăng nhập VSign/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Bật camera" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Nhận dạng" }));
    expect(screen.getByRole("heading", { name: "Nhận dạng ký hiệu" })).toBeInTheDocument();
    window.history.replaceState({}, "", "/");
  });

  it("hiển thị cảnh báo mock và accessible names cho control chính", async () => {
    render(<App />);
    expect(
      await screen.findByText("Mô phỏng – chưa dùng mô hình AI thật."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Bật camera" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "Giữ để ký, cũng có thể giữ phím Space",
      }),
    ).not.toBeInTheDocument();
    expect(document.querySelector(".add-button")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Hoàn tác từ cuối", hidden: true })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Xóa toàn bộ câu", hidden: true })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Sao chép câu", hidden: true })).toBeDisabled();
  });

  it("không mở công cụ kỹ thuật cho doanh nghiệp và vẫn cảnh báo mô phỏng", async () => {
    render(<App />);
    expect(screen.queryByLabelText("Model máy chủ")).not.toBeInTheDocument();
    expect(await screen.findByText("Mô phỏng – chưa dùng mô hình AI thật.")).toBeVisible();
    expect(screen.queryByText("Cấu hình AI", { exact: true })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Dev / Test", hidden: true })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Nhận dạng" })).toHaveAttribute("aria-pressed", "true");
  });

  it("bỏ cụm logo và mô tả lặp khỏi khu vực làm việc", () => {
    render(<App />);
    expect(screen.queryByRole("link", { name: /VSign/ })).not.toBeInTheDocument();
    expect(screen.queryByText("Ngôn ngữ ký hiệu Việt Nam")).not.toBeInTheDocument();
    expect(screen.queryByText("Kết quả từng từ · Xác nhận trước khi thêm vào câu")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Nhận dạng ký hiệu" })).toBeInTheDocument();
  });

  it("giữ tên vùng làm việc cho trình đọc màn hình khi giảm tầng tiêu đề", () => {
    render(<App />);
    const workspace = screen.getByRole("main", { name: "Nhận dạng ký hiệu" });
    expect(workspace).toContainElement(screen.getByRole("heading", { name: "Nhận dạng ký hiệu" }));
  });

  it("giữ tiêu đề workspace hiển thị và tooltip cho điều hướng dạng icon", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: "Nhận dạng ký hiệu" })).not.toHaveClass("sr-only");
    expect(screen.getByRole("button", { name: "Nhận dạng" })).toHaveAttribute("title", "Nhận dạng");
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
          collection_labels: [],
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
    const collectionLabels = [
      "Chào",
      "Tôi",
      "Muốn",
      "Mua",
      "Cho",
      "Xem",
      "Thử",
      "Siêu thị",
      "Có",
      "Cần",
      "Điện thoại",
      "Laptop",
      "Tivi",
      "Tủ lạnh",
      "Máy giặt",
      "Nồi cơm điện",
      "Gạo",
      "Sữa",
      "Cà phê",
      "Mới",
      "Cũ",
      "Rẻ",
      "Đắt",
      "Sử dụng",
      "Mua bán",
      "Ngân hàng",
      "Cung cấp",
      "Thay đổi",
      "Từ chối",
      "Cảm ơn",
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((input: string | URL | Request) => {
        const url = String(input);
        if (url.includes("/collection/summary")) {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              enabled: true,
              batch: "personal-100",
              target_per_label: 100,
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
            collection_labels: collectionLabels,
            candidate_labels_unverified: false,
            mock: false,
            collection_enabled: true,
            collection_target_per_hand: 50,
          }),
        });
      }),
    );
    const user = userEvent.setup();

    render(<App />);
    await userEvent.click(screen.getByText("Công cụ", { exact: true }));
    const collectionButton = await screen.findByRole("button", {
      name: "Thu dữ liệu AI",
    });
    expect(collectionButton).toBeEnabled();
    await user.click(collectionButton);

    expect(
      screen.getByRole("heading", { name: "Thu 100 mẫu mỗi từ" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Từ cần thực hiện" })).toHaveValue(
      "Chào",
    );
    const labelSelect = screen.getByRole("combobox", { name: "Từ cần thực hiện" });
    expect(
      Array.from((labelSelect as HTMLSelectElement).options).map(
        (option) => option.value,
      ),
    ).toEqual([...collectionLabels, "Không ký hiệu"]);
    expect(screen.getByText("3/100")).toBeInTheDocument();
    const firstVideo = screen.getByLabelText("Video mẫu cho từ Chào");
    expect(firstVideo.querySelector("source")).toHaveAttribute(
      "src",
      expect.stringContaining("reference-videos/sales30/01-chao.mp4"),
    );
    await user.selectOptions(labelSelect, "Điện thoại");
    expect(screen.getByText("0/100")).toBeInTheDocument();
    const phoneVideo = screen.getByLabelText("Video mẫu cho từ Điện thoại");
    expect(phoneVideo.querySelector("source")).toHaveAttribute(
      "src",
      expect.stringContaining("reference-videos/sales30/11-dien-thoai.mp4"),
    );
    expect(phoneVideo).toHaveAttribute("controls");
    expect(phoneVideo).toHaveAttribute("loop");
    expect(phoneVideo).toHaveAttribute("playsinline");
    expect(firstVideo).not.toBeInTheDocument();
    expect(screen.queryByText("Chưa có video mẫu cho nhãn này.")).not.toBeInTheDocument();
    await user.selectOptions(labelSelect, "Cảm ơn");
    expect(screen.getByLabelText("Video mẫu cho từ Cảm ơn").querySelector("source"))
      .toHaveAttribute("src", expect.stringContaining("reference-videos/sales30/30-cam-on.mp4"));
    await user.selectOptions(labelSelect, "Không ký hiệu");
    expect(
      screen.getByText(/Không làm một từ nào: đứng yên/),
    ).toBeInTheDocument();
    expect(
      screen.queryByLabelText(/Video mẫu cho từ/),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Thêm vào câu" })).not.toBeInTheDocument();
  });
});
