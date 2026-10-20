import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

vi.mock("./hooks/useWorkspacePlatform", async () => {
  const { localWorkspacePlatform } = await import("./test/workspacePlatformFixture");
  return { useWorkspacePlatform: () => ({ ...localWorkspacePlatform(), user: controls.internal
    ? { id: "internal", email: "internal@example.com", display_name: "Internal", role: "model_admin" } : null }) };
});
import { emptyLandmarkFrame, HAND_GLOBAL_OFFSET, HAND_PRESENCE_OFFSET } from "./lib/landmarkFeatures";
import type { HandTrackingFrame } from "./components/HandTrackingOverlay";

const controls = vi.hoisted(() => ({
  internal: false,
  cameraStatus: "ready",
  localStatus: "unavailable",
  ingest: null as ((frame: HandTrackingFrame) => void) | null,
  predictLocal: vi.fn(),
  metadataOverrides: {} as Record<string, unknown>,
}));
vi.mock("./hooks/useCamera", () => ({ useCamera: () => ({
  status: controls.cameraStatus, message: "Camera sẵn sàng.",
  enable: vi.fn(), disable: vi.fn(() => { controls.cameraStatus = "off"; }),
}) }));
vi.mock("./hooks/useLandmarkInference", () => ({ useLandmarkInference: () => ({
  status: controls.localStatus, error: "test", predict: controls.predictLocal,
  labels: ["Chào", "Mua"], modelVersion: "local-v3", runtime: "v3",
}) }));
vi.mock("./components/HandTrackingOverlay", () => ({ HandTrackingOverlay: ({ onTrackingFrame }: { onTrackingFrame: (frame: HandTrackingFrame) => void }) => {
  controls.ingest = onTrackingFrame;
  return null;
} }));
const encoder = vi.hoisted(() => ({ encode: vi.fn(), dispose: vi.fn() }));
vi.mock("./lib/frameEncoder", () => ({ createStreamingEncoder: () => encoder }));
const encodeNow = async (frame: { bitmap: ImageBitmap }) => {
  frame.bitmap.close();
  return "data:image/webp;base64,AAAA";
};

class Socket {
  static instances: Socket[] = [];
  readyState = 1;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror = null;
  onclose: (() => void) | null = null;
  send = vi.fn();
  close = vi.fn();
  constructor() { Socket.instances.push(this); queueMicrotask(() => this.onopen?.()); }
}

async function feedGesture(start = 0, from = 0, to = 56) {
  for (let i = from; i < to; i += 1) {
    const x = i < 16 ? 0.2 : i < 36 ? 0.2 + (i - 16) * 0.025 : 0.675;
    const features = emptyLandmarkFrame();
    for (let point = 0; point < 21; point += 1) {
      features[point * 3] = x + point * 0.001;
      features[point * 3 + 1] = 0.5;
    }
    features[HAND_GLOBAL_OFFSET] = x;
    features[HAND_GLOBAL_OFFSET + 1] = 0.5;
    features[HAND_PRESENCE_OFFSET] = 1;
    await act(async () => controls.ingest?.({ features, baselineFeatures: new Array(128).fill(0), crop: null, handCount: 1, updatedAt: start + i * 50 }));
  }
}

async function feedManualGesture() {
  vi.useFakeTimers();
  const clock = vi.spyOn(performance, "now").mockReturnValue(100);
  try {
    fireEvent.keyDown(window, { code: "Space", key: " " });
    await act(async () => vi.advanceTimersByTimeAsync(900));
    clock.mockReturnValue(1000);
    fireEvent.keyUp(window, { code: "Space", key: " " });
    await act(async () => { await Promise.resolve(); });
  } finally {
    clock.mockRestore();
    vi.useRealTimers();
  }
}

describe("Sales30 automatic server workflow", () => {
  beforeEach(() => {
    controls.internal = false;
    controls.cameraStatus = "ready";
    controls.localStatus = "unavailable";
    controls.predictLocal.mockReset();
    controls.metadataOverrides = {};
    Socket.instances = [];
    vi.stubGlobal("WebSocket", Socket);
    vi.stubGlobal("createImageBitmap", vi.fn(async () => ({ width: 224, height: 224, close: vi.fn() })));
    encoder.encode.mockReset().mockImplementation(encodeNow);
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      fillRect: vi.fn(), drawImage: vi.fn(),
    } as unknown as CanvasRenderingContext2D);
    vi.stubGlobal("fetch", vi.fn(async (url: string) => ({ ok: true, json: async () =>
      url.endsWith("/collection/summary") ? { counts: {} } : ({
      backend: "pytorch", model_version: "sales30-mvitv2s-seated-v3-epoch5",
      protocol_version: "1.0", frame_count: 16, frame_width: 224, frame_height: 224,
      labels: ["Chào", "Mua"], collection_labels: ["Chào"], supported_image_formats: ["image/webp"],
      confidence_threshold: 0.70, margin_threshold: 0.15,
      candidate_labels_unverified: false, mock: false, collection_enabled: false,
      collection_target_per_hand: 50,
      ...controls.metadataOverrides,
    }) })));
  });
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  async function open(captureMode: "manual" | "automatic" = "automatic") {
    const view = render(<App />);
    await act(async () => { await Promise.resolve(); });
    const video = screen.getByLabelText("Hình ảnh camera trực tiếp");
    Object.defineProperties(video, {
      readyState: { value: HTMLMediaElement.HAVE_CURRENT_DATA, configurable: true },
      videoWidth: { value: 1280, configurable: true },
      videoHeight: { value: 720, configurable: true },
    });
    await userEvent.click(screen.getByText("Cách thêm từ", { exact: true }));
    const automatic = screen.getByRole("button", { name: "Tự động beta" });
    expect(automatic).toBeEnabled();
    if (captureMode === "automatic") await userEvent.click(automatic);
    return { ...view, socket: Socket.instances[0] };
  }

  it("locks server model switching through manual capture, encoding and pending inference", async () => {
    controls.internal = true;
    controls.metadataOverrides.labels = ["Chào", "Mua", ...Array.from({ length: 28 }, (_, i) => `word-${i}`), "Không ký hiệu"];
    const waiting: Array<() => void> = [];
    const finishEncoding = () => waiting.splice(0).forEach((resolve) => resolve());
    encoder.encode.mockImplementation((frame) => {
      frame.bitmap.close();
      return new Promise<string>(resolve => waiting.push(() => resolve("data:image/webp;base64,AAAA")));
    });
    const { socket } = await open("manual");
    await userEvent.click(screen.getByText("Cấu hình AI", { exact: true }));
    const select = screen.getByRole("combobox", { name: "Model máy chủ" });
    expect(select).toBeEnabled();
    vi.useFakeTimers();
    const clock = vi.spyOn(performance, "now").mockReturnValue(100);
    try {
      fireEvent.keyDown(window, { code: "Space", key: " " });
      expect(select).toBeDisabled();
      await act(async () => vi.advanceTimersByTimeAsync(900));
      clock.mockReturnValue(1000);
      fireEvent.keyUp(window, { code: "Space", key: " " });
      await act(async () => { await Promise.resolve(); });
      expect(select).toBeDisabled();
      expect(waiting.length).toBeGreaterThan(8);
      await act(async () => finishEncoding());
      expect(socket.send).toHaveBeenCalledTimes(1);
      expect(select).toBeDisabled();
      respond(socket, 0);
      expect(select).toBeEnabled();
    } finally { clock.mockRestore(); vi.useRealTimers(); }
  });

  it("locks server model switching until all queued automatic jobs complete", async () => {
    controls.internal = true;
    controls.metadataOverrides.labels = ["Chào", "Mua", ...Array.from({ length: 28 }, (_, i) => `word-${i}`), "Không ký hiệu"];
    const { socket } = await open();
    await userEvent.click(screen.getByText("Cấu hình AI", { exact: true }));
    const select = screen.getByRole("combobox", { name: "Model máy chủ" });
    expect(select).toBeEnabled();
    await feedGesture();
    await feedGesture(4000);
    expect(select).toBeDisabled();
    respond(socket, 0);
    expect(select).toBeDisabled();
    respond(socket, 1);
    expect(select).toBeEnabled();
  });

  it("never silently uses the browser model when a selected seated server disconnects", async () => {
    controls.internal = true;
    const labels = ["Chào", "Mua", ...Array.from({ length: 28 }, (_, i) => `word-${i}`), "Không ký hiệu"];
    controls.metadataOverrides.labels = labels;
    await open("manual");
    controls.localStatus = "ready";
    controls.metadataOverrides.model_version = "sales30-mvitv2s-seated-personal-v1-head-epoch33";
    await userEvent.click(screen.getByText("Cấu hình AI", { exact: true }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Model máy chủ" }), "seated");
    expect(screen.getByRole("combobox", { name: "Model máy chủ" })).toHaveValue("seated");
    act(() => Socket.instances[1].onclose?.());
    expect(screen.getByRole("button", { name: "Tự động beta" })).toBeDisabled();
    expect(screen.queryByText("V3 baseline đang làm model demo.")).not.toBeInTheDocument();
    expect(controls.predictLocal).not.toHaveBeenCalled();
  });

  function respond(
    socket: Socket, sequence: number, status = "ok", label = "Chào",
    modelVersion = "sales30-mvitv2s-seated-v3-epoch5",
  ) {
    act(() => socket.onmessage?.({ data: JSON.stringify({
      type: "prediction", sequence, status,
      label: status === "ok" ? label : null, confidence: status === "ok" ? 0.95 : null,
      top_k: [{ label, confidence: 0.95 }], model_version: modelVersion,
    }) } as MessageEvent<string>));
  }

  it("bật tự động trên server, gửi RGB và chỉ thêm từ khi người dùng xác nhận", async () => {
    const { socket } = await open();
    await feedGesture();
    expect(socket.send).toHaveBeenCalledOnce();
    const payload = JSON.parse(socket.send.mock.calls[0][0]);
    expect(payload.type).toBe("frames");
    expect(payload.frames).toHaveLength(16);
    expect(payload.sequence).toBe(0);
    expect(payload.session_id).toMatch(/^[a-f0-9-]{36}$/);
    expect(controls.predictLocal).not.toHaveBeenCalled();
    respond(socket, payload.sequence);
    expect(screen.getByRole("button", { name: "Thêm vào câu" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Hoàn tác từ cuối", hidden: true })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Thêm vào câu" }));
    expect(screen.getByRole("button", { name: "Hoàn tác từ cuối" })).toBeEnabled();
  });

  it("chạy model ngay khi tay vừa dừng, giữ kết quả đến khi lượt được xác nhận", async () => {
    const { socket } = await open();
    await userEvent.click(screen.getByRole("radio", { name: "Thêm từ tự động" }));
    const transcript = screen.getByRole("region", { name: "Câu của bạn" });
    // Hands rest from 1800 ms; ~150 ms later the clip is already with the server.
    await feedGesture(0, 0, 42);
    expect(socket.send).toHaveBeenCalledOnce();
    respond(socket, 0, "ok", "Mua");
    expect(within(transcript).queryByText("1 từ")).not.toBeInTheDocument();
    // The rest completes: the held result is added without another request.
    await feedGesture(0, 42, 56);
    expect(socket.send).toHaveBeenCalledOnce();
    expect(transcript.querySelector(".transcript-words")).toHaveTextContent("Mua");
  });

  it("bỏ kết quả tạm khi tay cử động lại và gửi lại đoạn ký đầy đủ", async () => {
    const { socket } = await open();
    await userEvent.click(screen.getByRole("radio", { name: "Thêm từ tự động" }));
    const transcript = screen.getByRole("region", { name: "Câu của bạn" });
    await feedGesture(0, 0, 42);
    expect(socket.send).toHaveBeenCalledOnce();
    // Moving again within the same sign retracts the provisional request.
    await feedGesture(2100 - 16 * 50, 16, 36);
    respond(socket, 0, "ok", "Mua");
    expect(within(transcript).queryByText("1 từ")).not.toBeInTheDocument();
    await feedGesture(2100 - 16 * 50, 36, 56);
    expect(socket.send).toHaveBeenCalledTimes(2);
    const second = JSON.parse(socket.send.mock.calls[1][0]);
    respond(socket, second.sequence, "ok", "Chào");
    expect(transcript.querySelector(".transcript-words")).toHaveTextContent("Chào");
    expect(transcript.querySelector(".transcript-words")).not.toHaveTextContent("Mua");
  });

  it("thu hai lượt chờ khi AI bận, dừng khi đầy và gửi FIFO khi có reply", async () => {
    const { socket } = await open();
    await feedGesture();
    await feedGesture(5000);
    await feedGesture(10000);
    const encodedWhileQueued = encoder.encode.mock.calls.length;
    expect(socket.send).toHaveBeenCalledOnce();
    expect(screen.getByText("Hàng đợi đầy · chờ AI xử lý")).toBeInTheDocument();
    await feedGesture(15000);
    expect(encoder.encode).toHaveBeenCalledTimes(encodedWhileQueued);

    respond(socket, 0);
    expect(socket.send).toHaveBeenCalledTimes(2);
    expect(JSON.parse(socket.send.mock.calls[1][0]).sequence).toBe(1);
    expect(screen.queryByText("Hàng đợi đầy · chờ AI xử lý")).not.toBeInTheDocument();
    // A duplicate reply must not free sequence 1's slot.
    respond(socket, 0);
    expect(socket.send).toHaveBeenCalledTimes(2);
    respond(socket, 1, "uncertain");
    expect(socket.send).toHaveBeenCalledTimes(3);
    expect(JSON.parse(socket.send.mock.calls[2][0]).sequence).toBe(2);
    respond(socket, 2);
    expect(screen.getByRole("button", { name: "Thêm vào câu" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Hoàn tác từ cuối", hidden: true })).toBeDisabled();
    await feedGesture(20000);
    expect(socket.send).toHaveBeenCalledTimes(4);
  });

  it("hủy các lượt chờ và không nhận kết quả sau tắt camera", async () => {
    const { socket, rerender } = await open();
    await feedGesture();
    await feedGesture(5000);
    expect(encoder.encode).toHaveBeenCalled();
    expect(socket.send).toHaveBeenCalledOnce();
    const payload = JSON.parse(socket.send.mock.calls[0][0]);
    fireEvent.click(screen.getByRole("button", { name: "Tắt camera" }));
    rerender(<App />);
    respond(socket, payload.sequence);
    expect(document.querySelector(".add-button")).toBeDisabled();
    await feedGesture(9000);
    expect(socket.send).toHaveBeenCalledOnce();
  });

  it("chuyển thủ công hủy clip chờ nhưng đợi request cũ trước khi gửi lượt mới", async () => {
    const { socket } = await open();
    await feedGesture();
    await feedGesture(5000);
    await userEvent.click(screen.getByRole("button", { name: "Thủ công" }));
    const manualCapture = screen.getByRole("button", {
      name: "Giữ để ký, cũng có thể giữ phím Space",
    });
    expect(manualCapture).toBeDisabled();
    respond(socket, 0);
    expect(manualCapture).toBeEnabled();
    expect(socket.send).toHaveBeenCalledOnce();
    expect(document.querySelector(".add-button")).toBeDisabled();
  });

  it("mất socket hủy RGB chờ, fallback local không gửi chồng request cũ", async () => {
    const { socket } = await open();
    await feedGesture();
    await feedGesture(5000);
    controls.localStatus = "ready";
    controls.predictLocal.mockImplementation(async (_frames, sequence) => ({
      type: "prediction", sequence, status: "uncertain", label: null,
      confidence: null, top_k: [], model_version: "local-v3",
    }));
    act(() => socket.onclose?.());
    await feedGesture(10000);
    // A closed transport cannot return its old reply; local must be usable.
    expect(controls.predictLocal).toHaveBeenCalledOnce();
    expect(socket.send).toHaveBeenCalledOnce();
    expect(document.querySelector(".add-button")).toBeDisabled();
  });

  it("lượt camera thiếu ảnh không hủy inference của ký hiệu trước", async () => {
    const { socket } = await open();
    await feedGesture();
    vi.mocked(createImageBitmap).mockRejectedValue(new Error("Camera snapshot failed"));
    await feedGesture(5000);
    expect(socket.send).toHaveBeenCalledOnce();
    expect(screen.getByText("Không thu được đủ ảnh camera cho ký hiệu. Hãy thử lại.")).toBeInTheDocument();
    respond(socket, 0);
    expect(screen.getByRole("button", { name: "Thêm vào câu" })).toBeEnabled();
  });

  it("encode hoàn tất sau đổi chế độ không được thêm vào hàng đợi", async () => {
    let resolve!: (frame: string) => void;
    const pending = new Promise<string>((done) => { resolve = done; });
    const { socket } = await open();
    await feedGesture();
    encoder.encode.mockImplementation((frame) => {
      frame.bitmap.close();
      return pending;
    });
    await feedGesture(5000);
    expect(screen.getByText("Đang xử lý ảnh ký hiệu…")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Thủ công" }));
    await act(async () => resolve("data:image/webp;base64,AAAA"));
    respond(socket, 0);
    expect(socket.send).toHaveBeenCalledOnce();
    expect(document.querySelector(".add-button")).toBeDisabled();
  });

  it("thủ công → tự động → thủ công vẫn đợi local request cũ, không gửi clip đã hủy", async () => {
    let resolve!: (prediction: unknown) => void;
    const pending = new Promise((done) => { resolve = done; });
    controls.localStatus = "ready";
    controls.predictLocal.mockReturnValue(pending);
    const { socket } = await open();
    act(() => socket.onclose?.());
    await userEvent.click(screen.getByRole("button", { name: "Thủ công" }));

    vi.useFakeTimers();
    try {
      const clock = vi.spyOn(performance, "now").mockReturnValue(100);
      fireEvent.keyDown(window, { code: "Space", key: " " });
      await act(async () => vi.advanceTimersByTimeAsync(900));
      clock.mockReturnValue(1000);
      fireEvent.keyUp(window, { code: "Space", key: " " });
      await act(async () => { await Promise.resolve(); });
      expect(controls.predictLocal).toHaveBeenCalledOnce();

      fireEvent.click(screen.getByRole("button", { name: "Tự động beta" }));
      await feedGesture(5000);
      expect(screen.getByText("Chờ: 1/2")).toBeInTheDocument();
      expect(controls.predictLocal).toHaveBeenCalledOnce();
      fireEvent.click(screen.getByRole("button", { name: "Thủ công" }));
      const manual = screen.getByRole("button", {
        name: "Giữ để ký, cũng có thể giữ phím Space",
      });
      expect(manual).toBeDisabled();
      await act(async () => resolve({
        type: "prediction", sequence: 0, status: "ok", label: "Chào", confidence: 0.95,
        top_k: [{ label: "Chào", confidence: 0.95 }], model_version: "local-v3",
      }));
      expect(manual).toBeEnabled();
      expect(controls.predictLocal).toHaveBeenCalledOnce();
      expect(socket.send).not.toHaveBeenCalled();
      expect(document.querySelector(".add-button")).toBeDisabled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("hủy request khi trở về thủ công, không tự chấp nhận uncertain", async () => {
    const { socket } = await open();
    await feedGesture();
    const first = JSON.parse(socket.send.mock.calls[0][0]);
    respond(socket, first.sequence, "uncertain");
    expect(document.querySelector(".add-button")).toBeDisabled();
    await feedGesture(5000);
    expect(socket.send).toHaveBeenCalledTimes(2);
    const second = JSON.parse(socket.send.mock.calls[1][0]);
    await userEvent.click(screen.getByRole("button", { name: "Thủ công" }));
    respond(socket, second.sequence);
    expect(document.querySelector(".add-button")).toBeDisabled();
  });

  it("tự thêm từng reply FIFO, kể cả khi request tiếp theo bắt đầu trong cùng tick", async () => {
    const { socket } = await open();
    await userEvent.click(screen.getByRole("radio", { name: "Thêm từ tự động" }));
    expect(screen.getByRole("button", { name: "Tự động beta" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("button", { name: "Thêm vào câu" })).not.toBeInTheDocument();
    await feedGesture();
    await feedGesture(5000);
    await feedGesture(10000);
    act(() => {
      respond(socket, 0);
      respond(socket, 1, "ok", "Mua");
      respond(socket, 2);
    });
    const transcript = screen.getByRole("region", { name: "Câu của bạn" });
    expect(transcript.querySelector(".transcript-words")).toHaveTextContent("Chào Mua Chào");
    expect(within(transcript).getByText("3 từ")).toBeInTheDocument();
    expect(socket.send).toHaveBeenCalledTimes(3);
    // Each queued clip is sent after the previous reply, with the sentence so far as context.
    expect(socket.send.mock.calls.map(([body]) => JSON.parse(body).context_words)).toEqual([
      [], ["Chào"], ["Chào", "Mua"],
    ]);
    respond(socket, 2);
    expect(within(transcript).getByText("3 từ")).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes("/sentence/compose"))).toBe(false);
  });

  it("thêm tự động vẫn hoạt động với Giữ để ký và không tự đổi cách thu", async () => {
    const { socket } = await open("manual");
    await userEvent.click(screen.getByRole("radio", { name: "Thêm từ tự động" }));
    expect(screen.getByRole("button", { name: "Thủ công" })).toHaveAttribute("aria-pressed", "true");
    await feedManualGesture();
    expect(socket.send).toHaveBeenCalledOnce();
    respond(socket, 0);
    expect(screen.getByRole("button", { name: "Hoàn tác từ cuối" })).toBeEnabled();
    expect(screen.getByRole("region", { name: "Câu của bạn" }).querySelector(".transcript-words")).toHaveTextContent(/^Chào$/);
  });

  it("bật tự động không thêm kết quả cũ hoặc các lượt đã thu trước đó", async () => {
    const { socket } = await open();
    await feedGesture();
    await feedGesture(5000);
    respond(socket, 0);
    await userEvent.click(screen.getByRole("radio", { name: "Thêm từ tự động" }));
    expect(screen.getByRole("button", { name: "Hoàn tác từ cuối", hidden: true })).toBeDisabled();
    respond(socket, 1);
    expect(screen.getByRole("button", { name: "Hoàn tác từ cuối", hidden: true })).toBeDisabled();
    await feedGesture(10000);
    respond(socket, 2);
    expect(screen.getByRole("button", { name: "Hoàn tác từ cuối" })).toBeEnabled();
  });

  it("bật tự động giữa lúc encode không thêm clip đã bắt đầu trước đó", async () => {
    let resolve!: (frame: string) => void;
    const pending = new Promise<string>((done) => { resolve = done; });
    const { socket } = await open();
    encoder.encode.mockImplementation((frame) => {
      frame.bitmap.close();
      return pending;
    });
    await feedGesture();
    encoder.encode.mockImplementation(encodeNow);
    await userEvent.click(screen.getByRole("radio", { name: "Thêm từ tự động" }));
    await act(async () => resolve("data:image/webp;base64,AAAA"));
    expect(socket.send).toHaveBeenCalledOnce();
    respond(socket, 0);
    expect(screen.getByRole("button", { name: "Hoàn tác từ cuối", hidden: true })).toBeDisabled();
    await feedGesture(5000);
    respond(socket, 1);
    expect(screen.getByRole("button", { name: "Hoàn tác từ cuối" })).toBeEnabled();
  });

  it("tắt rồi bật lại không nhận request cũ, lượt mới vẫn tự thêm", async () => {
    const { socket } = await open();
    await userEvent.click(screen.getByRole("radio", { name: "Thêm từ tự động" }));
    await feedGesture();
    await userEvent.click(screen.getByRole("radio", { name: "Thêm từ thủ công" }));
    await userEvent.click(screen.getByRole("radio", { name: "Thêm từ tự động" }));
    respond(socket, 0);
    expect(screen.getByRole("button", { name: "Hoàn tác từ cuối", hidden: true })).toBeDisabled();
    await feedGesture(5000);
    respond(socket, 1);
    expect(screen.getByRole("button", { name: "Hoàn tác từ cuối" })).toBeEnabled();
  });

  it("trở về thêm thủ công vẫn cần click để nhận kết quả đang xử lý", async () => {
    const { socket } = await open();
    await userEvent.click(screen.getByRole("radio", { name: "Thêm từ tự động" }));
    await feedGesture();
    await userEvent.click(screen.getByRole("radio", { name: "Thêm từ thủ công" }));
    respond(socket, 0);
    expect(screen.getByRole("button", { name: "Hoàn tác từ cuối", hidden: true })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Thêm vào câu" }));
    expect(screen.getByRole("button", { name: "Hoàn tác từ cuối" })).toBeEnabled();
  });

  it.each(["uncertain", "no_hands", "bad_framing", "busy", "error"])(
    "không tự thêm phản hồi %s", async (status) => {
      const { socket } = await open();
      await userEvent.click(screen.getByRole("radio", { name: "Thêm từ tự động" }));
      await feedGesture();
      respond(socket, 0, status);
      expect(screen.getByRole("button", { name: "Hoàn tác từ cuối", hidden: true })).toBeDisabled();
    },
  );

  it.each([{ mock: true }, { candidate_labels_unverified: true }])(
    "không tự thêm khi metadata không hợp lệ: %j", async (overrides) => {
      controls.metadataOverrides = overrides;
      const { socket } = await open();
      await userEvent.click(screen.getByRole("radio", { name: "Thêm từ tự động" }));
      await feedGesture();
      respond(socket, 0);
      expect(screen.getByRole("button", { name: "Hoàn tác từ cuối", hidden: true })).toBeDisabled();
      expect(screen.getByText("Tự động thêm đang tạm dừng.")).toBeInTheDocument();
    },
  );

  it.each([
    ["Không ký hiệu", "sales30-mvitv2s-seated-v3-epoch5"],
    ["Nhãn ngoài vocabulary", "sales30-mvitv2s-seated-v3-epoch5"],
    ["Chào", "old-model-version"],
  ])("không tự thêm nhãn/phiên bản không hợp lệ: %s / %s", async (label, version) => {
    const { socket } = await open();
    await userEvent.click(screen.getByRole("radio", { name: "Thêm từ tự động" }));
    await feedGesture();
    respond(socket, 0, "ok", label, version);
    expect(screen.getByRole("button", { name: "Hoàn tác từ cuối", hidden: true })).toBeDisabled();
  });

  it("giữ cooldown, cho phép ký lại từ ở lượt mới và không hồi sinh từ sau hoàn tác/xóa", async () => {
    const clock = vi.spyOn(Date, "now").mockReturnValue(1000);
    const { socket } = await open();
    await userEvent.click(screen.getByRole("radio", { name: "Thêm từ tự động" }));
    await feedGesture();
    respond(socket, 0);
    await feedGesture(5000);
    respond(socket, 1);
    const transcript = screen.getByRole("region", { name: "Câu của bạn" });
    expect(within(transcript).getByText("1 từ")).toBeInTheDocument();
    clock.mockReturnValue(2101);
    await feedGesture(10000);
    respond(socket, 2);
    expect(transcript.querySelector(".transcript-words")).toHaveTextContent("Chào Chào");
    await userEvent.click(screen.getByRole("button", { name: "Hoàn tác từ cuối" }));
    respond(socket, 2);
    expect(within(transcript).getByText("1 từ")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Xóa toàn bộ câu" }));
    respond(socket, 0);
    expect(within(transcript).getByText("Chưa có từ")).toBeInTheDocument();
  });

  it("không tự thêm phản hồi đến sau khi tắt camera", async () => {
    const { socket, rerender } = await open();
    await userEvent.click(screen.getByRole("radio", { name: "Thêm từ tự động" }));
    await feedGesture();
    fireEvent.click(screen.getByRole("button", { name: "Tắt camera" }));
    rerender(<App />);
    respond(socket, 0);
    expect(screen.getByRole("button", { name: "Hoàn tác từ cuối", hidden: true })).toBeDisabled();
  });

  it("không tự thêm phản hồi khi đổi cách thu làm hủy lượt đang xử lý", async () => {
    const { socket } = await open();
    await userEvent.click(screen.getByRole("radio", { name: "Thêm từ tự động" }));
    await feedGesture();
    await userEvent.click(screen.getByRole("button", { name: "Thủ công" }));
    respond(socket, 0);
    expect(screen.getByRole("button", { name: "Hoàn tác từ cuối", hidden: true })).toBeDisabled();
  });

  it("tự thêm với model local thật sau khi socket mất kết nối", async () => {
    controls.localStatus = "ready";
    controls.predictLocal.mockImplementation(async (_frames, sequence) => ({
      type: "prediction", sequence, status: "ok", label: "Chào", confidence: 0.95,
      top_k: [{ label: "Chào", confidence: 0.95 }], model_version: "local-v3",
    }));
    const { socket } = await open();
    act(() => socket.onclose?.());
    await userEvent.click(screen.getByRole("radio", { name: "Thêm từ tự động" }));
    await feedGesture();
    expect(controls.predictLocal).toHaveBeenCalledOnce();
    expect(socket.send).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Hoàn tác từ cuối" })).toBeEnabled();
  });

  it("thêm đủ các phản hồi local nối tiếp mà không gửi inference chồng nhau", async () => {
    const replies = new Map<number, (prediction: unknown) => void>();
    controls.localStatus = "ready";
    controls.predictLocal.mockImplementation((_frames, sequence) =>
      new Promise((resolve) => replies.set(sequence, resolve)),
    );
    const { socket } = await open();
    act(() => socket.onclose?.());
    await userEvent.click(screen.getByRole("radio", { name: "Thêm từ tự động" }));
    await feedGesture();
    await feedGesture(5000);
    await feedGesture(10000);
    expect(controls.predictLocal).toHaveBeenCalledOnce();
    for (const [sequence, label] of [[0, "Chào"], [1, "Mua"], [2, "Chào"]] as const) {
      expect(replies.has(sequence)).toBe(true);
      await act(async () => replies.get(sequence)?.({
        type: "prediction", sequence, status: "ok", label, confidence: 0.95,
        top_k: [{ label, confidence: 0.95 }], model_version: "local-v3",
      }));
      expect(controls.predictLocal).toHaveBeenCalledTimes(Math.min(sequence + 2, 3));
    }
    const transcript = screen.getByRole("region", { name: "Câu của bạn" });
    expect(transcript.querySelector(".transcript-words")).toHaveTextContent("Chào Mua Chào");
    expect(socket.send).not.toHaveBeenCalled();
  });

  it("không thêm từ khi thu mẫu AI dù đã chọn thêm tự động trong luồng nhận dạng", async () => {
    controls.metadataOverrides = { collection_enabled: true };
    const { socket } = await open("manual");
    await userEvent.click(screen.getByRole("radio", { name: "Thêm từ tự động" }));
    await userEvent.click(screen.getByText("Công cụ", { exact: true }));
    await userEvent.click(screen.getByRole("button", { name: "Thu dữ liệu AI" }));
    expect(screen.queryByRole("radio", { name: "Thêm từ tự động" })).not.toBeInTheDocument();
    await feedManualGesture();
    respond(socket, 0);
    await userEvent.click(screen.getByRole("button", { name: "Nhận dạng" }));
    expect(screen.getByRole("button", { name: "Hoàn tác từ cuối", hidden: true })).toBeDisabled();
  });
});
