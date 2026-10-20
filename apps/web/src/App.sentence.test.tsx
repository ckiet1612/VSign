import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

vi.mock("./hooks/useWorkspacePlatform", async () => {
  const { localWorkspacePlatform } = await import("./test/workspacePlatformFixture");
  return { useWorkspacePlatform: localWorkspacePlatform };
});
import type { HandTrackingFrame } from "./components/HandTrackingOverlay";

const controls = vi.hoisted(() => ({
  tracking: null as ((frame: HandTrackingFrame) => void) | null,
  capture: null as null | { onCaptureStart?: () => void; onSequence: (...args: unknown[]) => void },
  busy: false,
}));
vi.mock("./hooks/useCamera", () => ({ useCamera: () => ({ status: "ready", message: "", enable: vi.fn(), disable: vi.fn() }) }));
vi.mock("./hooks/useLandmarkInference", () => ({ useLandmarkInference: () => ({ status: "unavailable", labels: [], predict: vi.fn() }) }));
vi.mock("./hooks/useAutomaticSignCapture", () => ({ useAutomaticSignCapture: (options: typeof controls.capture) => {
  controls.capture = options;
  return { phase: "waiting", ingest: vi.fn(), isBusy: () => controls.busy };
} }));
vi.mock("./components/HandTrackingOverlay", () => ({ HandTrackingOverlay: ({ onTrackingFrame }: { onTrackingFrame: typeof controls.tracking }) => {
  controls.tracking = onTrackingFrame;
  return null;
} }));

class Socket {
  static instance: Socket;
  readyState = 1;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onclose = null;
  onerror = null;
  send = vi.fn();
  close = vi.fn();
  constructor() { Socket.instance = this; Promise.resolve().then(() => this.onopen?.()); }
}
const labels = ["Tôi", "Muốn", "Mua", "Tủ lạnh", "Rẻ"];
describe("hands-free sentence integration", () => {
  beforeEach(() => {
    controls.busy = false;
    vi.stubGlobal("WebSocket", Socket);
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => ({ ok: true, json: async () =>
      url.endsWith("/sentence/compose") ? { sentence: JSON.parse(String(init?.body)).words.join(" ") + ".", provider: "local", model: null } : {
        backend: "coreml", model_version: "test-model", protocol_version: "1.0", labels,
        frame_count: 16, frame_width: 224, frame_height: 224,
        candidate_labels_unverified: false, mock: false, collection_enabled: false,
        sentence_ai_enabled: false,
      },
    })));
    vi.useFakeTimers();
    vi.spyOn(performance, "now").mockImplementation(() => Date.now());
  });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  async function open() {
    render(<App />);
    await act(async () => { await Promise.resolve(); });
    fireEvent.click(screen.getByText("Cách thêm từ", { exact: true }));
    fireEvent.click(screen.getByRole("button", { name: "Tự động beta" }));
    fireEvent.click(screen.getByRole("radio", { name: "Thêm từ tự động" }));
  }
  function tracking() {
    controls.tracking?.({ features: null, baselineFeatures: null, crop: null, handCount: 0, updatedAt: performance.now() });
  }
  function capture() {
    act(() => {
      tracking();
      controls.capture?.onCaptureStart?.();
      controls.capture?.onSequence([], [], new Array(16).fill("data:image/jpeg;base64,AAAA"));
    });
  }
  function reply(sequence: number, label: string, status = "ok") {
    act(() => Socket.instance.onmessage?.({ data: JSON.stringify({
      type: "prediction", sequence, status, label: status === "ok" ? label : null,
      confidence: status === "ok" ? .95 : null, top_k: [{ label, confidence: .95 }], model_version: "test-model",
    }) } as MessageEvent<string>));
  }
  async function waitQuiet() {
    for (let i = 0; i < 10; i++) {
      act(tracking);
      await act(async () => vi.advanceTimersByTimeAsync(200));
    }
  }
  function compositions() {
    return vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith("/sentence/compose"));
  }

  it("does not compose before the queued Rẻ arrives, then displays the whole draft without a click", async () => {
    await open();
    for (let i = 0; i < 4; i++) { capture(); reply(i, labels[i]); }
    capture();
    await waitQuiet();
    expect(compositions()).toHaveLength(0);
    reply(4, "Rẻ");
    await waitQuiet();
    expect(compositions()).toHaveLength(1);
    expect(JSON.parse(String(compositions()[0][1]?.body)).words).toEqual(labels);
    expect(screen.getByText("Tôi Muốn Mua Tủ lạnh Rẻ.")).toBeInTheDocument();
    expect(screen.getByText("Dự thảo · chưa xác nhận")).toBeInTheDocument();
  });

  it("shows a best-effort draft after an uncertain sign and retains the warning", async () => {
    await open();
    for (let i = 0; i < 4; i++) { capture(); reply(i, labels[i]); }
    capture(); reply(4, "Rẻ", "uncertain");
    await waitQuiet();
    expect(compositions()).toHaveLength(1);
    expect(JSON.parse(String(compositions()[0][1]?.body)).words).toEqual(labels.slice(0, 4));
    const transcript = screen.getByRole("region", { name: "Câu của bạn" });
    expect(within(transcript).getByText("Có đoạn chưa nhận dạng · cần kiểm tra")).toBeInTheDocument();
    expect(within(transcript).getByText("Tôi Muốn Mua Tủ lạnh.")).toBeInTheDocument();
  });

  it("passes backend grammar warnings to the automatic draft without erasing a capture gap", async () => {
    const previousFetch = fetch;
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => url.endsWith("/sentence/compose")
      ? { ok: true, json: async () => ({ sentence: "Tôi muốn mua tủ lạnh.", provider: "local", model: null,
        warnings: ["Cấu trúc chưa rõ"] }) }
      : previousFetch(url, init)));
    await open();
    for (let i = 0; i < 4; i++) { capture(); reply(i, labels[i]); }
    capture(); reply(4, "Rẻ", "uncertain");
    await waitQuiet();
    expect(screen.getByText(/Có đoạn chưa nhận dạng.*Cấu trúc chưa rõ/)).toBeInTheDocument();
    expect(screen.getByText("Tôi muốn mua tủ lạnh.")).toBeInTheDocument();
    const writeText = vi.fn(async () => {});
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Sao chép câu" })));
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining("Có đoạn chưa nhận dạng · cần kiểm tra · Cấu trúc chưa rõ"));
  });

  it("clear starts a clean customer transcript and ignores the old pending reply", async () => {
    await open();
    capture(); reply(0, "Mua");
    capture();
    fireEvent.click(screen.getByRole("button", { name: "Xóa toàn bộ câu" }));
    reply(1, "Rẻ");
    await waitQuiet();
    const transcript = screen.getByRole("region", { name: "Câu của bạn" });
    expect(within(transcript).getByText("Chưa có từ")).toBeInTheDocument();
    expect(compositions()).toHaveLength(0);
  });

  it("queue saturation shows a best-effort draft and retains a persistent warning", async () => {
    await open();
    capture(); reply(0, "Mua");
    capture(); capture(); capture();
    for (let i = 1; i < 4; i++) reply(i, labels[i]);
    await waitQuiet();
    expect(compositions()).toHaveLength(1);
    expect(JSON.parse(String(compositions()[0][1]?.body)).words.length).toBeGreaterThan(0);
    expect(screen.getByText("Hàng đợi đầy · có thể thiếu đoạn ký")).toBeInTheDocument();
  });

  it("staff can clear a session even when the first gesture was uncertain", async () => {
    await open();
    capture(); reply(0, "Rẻ", "uncertain");
    const clear = screen.getByRole("button", { name: "Xóa toàn bộ câu" });
    expect(clear).toBeEnabled();
    fireEvent.click(clear);
    expect(screen.queryByText("Có đoạn chưa nhận dạng · cần kiểm tra")).not.toBeInTheDocument();
    capture(); reply(1, "Mua");
    await waitQuiet();
    expect(compositions()).toHaveLength(1);
  });

  it("recognizes three separate sentences without further web actions, including one after uncertainty", async () => {
    await open();
    capture(); reply(0, "Mua");
    await waitQuiet();
    expect(screen.getByText("Mua.")).toBeInTheDocument();
    await waitQuiet(); await waitQuiet();
    capture(); reply(1, "Rẻ", "uncertain");
    await waitQuiet(); await waitQuiet(); await waitQuiet();
    capture(); reply(2, "Tủ lạnh");
    await waitQuiet();
    expect(compositions()).toHaveLength(2);
    expect(screen.getByText("Mua.")).toBeInTheDocument();
    expect(screen.getByText("Tủ lạnh.")).toBeInTheDocument();
    expect(screen.getByText("Có đoạn chưa nhận dạng · cần kiểm tra")).toBeInTheDocument();
  });

  it("assigns queued results to separate sentences even when neither has been composed", async () => {
    await open();
    capture();
    await waitQuiet(); await waitQuiet(); await waitQuiet();
    capture();
    reply(0, "Mua"); reply(1, "Tủ lạnh");
    await waitQuiet();
    expect(compositions().map(call => JSON.parse(String(call[1]?.body)).words))
      .toEqual([["Mua"], ["Tủ lạnh"]]);
    expect(screen.getByText("Mua.")).toBeInTheDocument();
    expect(screen.getByText("Tủ lạnh.")).toBeInTheDocument();
  });

  it("keeps a repeated word signed in another sentence when both predictions arrive together", async () => {
    await open();
    capture();
    await waitQuiet(); await waitQuiet(); await waitQuiet();
    capture();
    reply(0, "Mua"); reply(1, "Mua");
    await waitQuiet();
    expect(compositions().map(call => JSON.parse(String(call[1]?.body)).words))
      .toEqual([["Mua"], ["Mua"]]);
    expect(screen.getAllByText("Mua.")).toHaveLength(2);
    expect(screen.queryByText("Có đoạn chưa nhận dạng · cần kiểm tra")).not.toBeInTheDocument();
  });
});
