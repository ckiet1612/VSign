import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type { AuthenticatedUser } from "@workspace-contracts";
let auditUser: AuthenticatedUser | null = null;

vi.mock("./hooks/useWorkspacePlatform", async () => {
  const { localWorkspacePlatform } = await import("./test/workspacePlatformFixture");
  return { useWorkspacePlatform: () => ({ ...localWorkspacePlatform(), user: auditUser }) };
});
import { BASELINE_HAND_PRESENCE_OFFSET } from "./lib/landmarkFeaturesV3";

const controls = vi.hoisted(() => ({
  cameraStatus: "ready" as "ready" | "idle",
  captureOptions: null as null | {
    onFrames: (value: unknown) => void; onCaptureCancel: () => void; onError: (message: string) => void;
  },
  cancel: vi.fn(),
  start: vi.fn(),
  counts: { right: 0, left: 0 },
  saveError: false,
  summaryError: false,
  deferredSave: null as null | (() => Promise<unknown>),
}));
vi.mock("./hooks/useCamera", () => ({ useCamera: () => ({
  status: controls.cameraStatus, message: "Sẵn sàng", enable: vi.fn(), disable: vi.fn(),
}) }));
vi.mock("./hooks/useLandmarkInference", () => ({ useLandmarkInference: () => ({
  status: "unavailable", labels: [], predict: vi.fn(), error: "test", modelVersion: "local",
}) }));
vi.mock("./hooks/useInferenceSocket", () => ({ useInferenceSocket: () => ({
  status: "disconnected", sendFrames: vi.fn(() => { throw new Error("No inference expected"); }),
}) }));
vi.mock("./components/HandTrackingOverlay", () => ({ HandTrackingOverlay: () => null }));
vi.mock("./hooks/useSignCapture", () => ({ useSignCapture: (options: typeof controls.captureOptions) => {
  controls.captureOptions = options;
  return { status: "idle", start: controls.start, stop: vi.fn(), cancel: controls.cancel };
} }));

async function emitSample(withHands = true) {
  const baseline = new Array(128).fill(0);
  if (withHands) baseline[BASELINE_HAND_PRESENCE_OFFSET] = 1;
  await act(async () => controls.captureOptions?.onFrames({
    frames: new Array(16).fill("data:image/webp;base64,AAAA"),
    sourceFrames: new Array(28).fill("data:image/webp;base64,AAAA"),
    durationMs: 2100,
    landmarkFrames: [], baselineLandmarkFrames: new Array(16).fill(baseline),
  }));
}

describe("personal 100 collection", () => {
  beforeEach(() => {
    controls.cameraStatus = "ready";
    auditUser = null;
    controls.counts = { right: 0, left: 0 };
    controls.saveError = false;
    controls.summaryError = false;
    controls.deferredSave = null;
    controls.cancel.mockReset(); controls.start.mockReset();
    vi.stubGlobal("fetch", vi.fn(async (url: string, options?: RequestInit) => {
      if (url.endsWith("/audit/client-events")) {
        const payload = JSON.parse(String(options?.body));
        return new Response(JSON.stringify({ status: "recorded", event_id: payload.event_id }), { status: 201 });
      }
      if (url.includes("/collection/summary")) return {
        ok: !controls.summaryError,
        json: async () => ({ batch: "personal-100", target_per_label: 100, counts: { "Chào": controls.counts } }),
      };
      if (url.endsWith("/collection/samples")) {
        if (controls.deferredSave) return controls.deferredSave();
        if (controls.saveError) return { ok: false, json: async () => ({ detail: "Lỗi lưu thử nghiệm" }) };
        const payload = JSON.parse(options!.body as string);
        controls.counts = { ...controls.counts, [payload.hand]: controls.counts[payload.hand as "right" | "left"] + 1 };
        return { ok: true, json: async () => ({
          status: "saved", sample_id: payload.sample_key, expected_label: payload.expected_label,
          hand: payload.hand, label_hand_count: controls.counts[payload.hand as "right" | "left"],
          label_count: controls.counts.right + controls.counts.left,
          relative_video_path: "batches/personal-100/chao/right/sample.mp4",
        }) };
      }
      return { ok: true, json: async () => ({
        backend: "pytorch", model_version: "sales30-v3", frame_count: 16, labels: ["Chào"],
        collection_labels: ["Chào"], collection_enabled: true, collection_target_per_hand: 50,
        mock: false, candidate_labels_unverified: false,
      }) };
    }));
  });
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  async function open() {
    const view = render(<App />);
    fireEvent.click(screen.getByText("Công cụ", { exact: true }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Thu dữ liệu AI" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Thu dữ liệu AI" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Bắt đầu thu" })).toBeEnabled());
    return view;
  }
  const posts = () => vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith("/collection/samples"));
  const reports = () => vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith("/audit/client-events"))
    .map(([, init]) => JSON.parse(String(init?.body)));
  const signIn = () => { auditUser = { id: "owner", email: "owner@example.com", display_name: "Owner", role: "owner" }; };

  it("pauses once on camera shutdown and requires an explicit resume", async () => {
    signIn(); const view = await open();
    fireEvent.click(screen.getByRole("button", { name: "Bắt đầu thu" }));
    controls.cameraStatus = "idle"; view.rerender(<App />);
    await waitFor(() => expect(reports()).toHaveLength(2));
    expect(reports()[1]).toMatchObject({ event_type: "collection.paused", reason: "camera_off" });
    controls.cameraStatus = "ready"; view.rerender(<App />);
    expect(screen.getByRole("button", { name: "Tiếp tục" })).toBeEnabled();
    expect(reports()).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Tiếp tục" }));
    await waitFor(() => expect(reports()).toHaveLength(3));
    expect(reports()[2].event_type).toBe("collection.resumed");
  });

  it("ends the old collection context across logout and starts a fresh audited session after login", async () => {
    signIn(); const view = await open();
    fireEvent.click(screen.getByRole("button", { name: "Bắt đầu thu" }));
    await waitFor(() => expect(reports()).toHaveLength(1));
    auditUser = null; view.rerender(<App />);
    signIn(); view.rerender(<App />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Bắt đầu thu" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Bắt đầu thu" }));
    await emitSample();
    await waitFor(() => expect(reports()).toHaveLength(3));
    expect(reports()[1].event_type).toBe("collection.started");
    expect(reports()[1].resource_id).not.toBe(reports()[0].resource_id);
    expect(reports()[2]).toMatchObject({ event_type: "collection.sample_saved", resource_id: reports()[1].resource_id });
  });

  it("ignores an old account's ACK when the same account logs in again", async () => {
    signIn(); let finish!: (response: unknown) => void;
    controls.deferredSave = () => new Promise(resolve => { finish = resolve; });
    const view = await open(); fireEvent.click(screen.getByRole("button", { name: "Bắt đầu thu" }));
    await emitSample();
    const payload = JSON.parse(posts()[0][1]!.body as string);
    auditUser = null; view.rerender(<App />); signIn(); view.rerender(<App />);
    await act(async () => finish({ ok: true, json: async () => ({ status: "saved", sample_id: payload.sample_key,
      expected_label: "Chào", hand: "right", label_hand_count: 100, label_count: 100 }) }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Bắt đầu thu" })).toBeEnabled());
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
    expect(reports().filter(item => item.event_type === "collection.sample_saved")).toHaveLength(0);
  });

  it("audits transitions and confirmed saves under separate logical sessions", async () => {
    signIn(); await open();
    fireEvent.click(screen.getByRole("button", { name: "Bắt đầu thu" }));
    await emitSample();
    await waitFor(() => expect(reports()).toHaveLength(2));
    fireEvent.click(screen.getByRole("button", { name: "Tạm dừng" }));
    fireEvent.click(screen.getByRole("button", { name: "Tiếp tục" }));
    fireEvent.click(screen.getByRole("button", { name: "Dừng phiên" }));
    fireEvent.click(screen.getByRole("button", { name: "Bắt đầu thu" }));
    await waitFor(() => expect(reports()).toHaveLength(6));
    expect(reports().map(item => item.event_type)).toEqual(["collection.started", "collection.sample_saved",
      "collection.paused", "collection.resumed", "collection.stopped", "collection.started"]);
    expect(new Set(reports().slice(0, 5).map(item => item.resource_id)).size).toBe(1);
    expect(reports()[5].resource_id).not.toBe(reports()[0].resource_id);
    expect(reports()[1]).toMatchObject({ saved_samples: 1, sample_id: JSON.parse(posts()[0][1]!.body as string).sample_key });
    expect(reports()[5].saved_samples).toBe(0);
  });

  it("never reports a saved sample on upload failure", async () => {
    signIn(); controls.saveError = true; await open();
    fireEvent.click(screen.getByRole("button", { name: "Bắt đầu thu" }));
    await emitSample();
    await waitFor(() => expect(reports()).toHaveLength(2));
    expect(reports().map(item => item.event_type)).toEqual(["collection.started", "collection.paused"]);
    expect(reports()[1]).toMatchObject({ saved_samples: 0, reason: "save_error" });
    expect(posts()).toHaveLength(1);
  });

  it("attributes an ACK arriving after Stop to the stopped session", async () => {
    signIn(); let finish!: (response: unknown) => void;
    controls.deferredSave = () => new Promise(resolve => { finish = resolve; });
    await open(); fireEvent.click(screen.getByRole("button", { name: "Bắt đầu thu" }));
    await emitSample(); fireEvent.click(screen.getByRole("button", { name: "Dừng phiên" }));
    const payload = JSON.parse(posts()[0][1]!.body as string);
    await act(async () => finish({ ok: true, json: async () => ({ status: "saved", sample_id: payload.sample_key,
      expected_label: "Chào", hand: "right", label_hand_count: 1, label_count: 1 }) }));
    await waitFor(() => expect(reports()).toHaveLength(3));
    expect(reports().map(item => item.event_type)).toEqual(["collection.started", "collection.stopped", "collection.sample_saved"]);
    expect(reports()[2].resource_id).toBe(reports()[0].resource_id);
    expect(screen.getByRole("button", { name: "Bắt đầu thu" })).toBeEnabled();
  });

  it("starts without an AI model and saves full clips under a separate batch", async () => {
    await open();
    expect(screen.queryByRole("button", { name: /Giữ để quay mẫu/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Bắt đầu thu" }));
    await emitSample();
    await waitFor(() => expect(posts()).toHaveLength(1));
    const payload = JSON.parse(posts()[0][1]!.body as string);
    expect(payload.batch).toBe("personal-100");
    expect(payload.sample_key).toMatch(/^[a-f0-9-]{36}$/);
    expect(payload.expected_label).toBe("Chào");
    expect(payload.predicted_label).toBeNull();
    expect(payload.frames).toHaveLength(28);
    await waitFor(() => expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "1"));
    expect(screen.getByRole("button", { name: "Tạm dừng" })).toBeEnabled();
  });

  it("counts both hands toward 100 and stops without changing the selected word", async () => {
    controls.counts = { right: 80, left: 19 };
    await open();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "99");
    fireEvent.click(screen.getByRole("button", { name: "Bắt đầu thu" }));
    await emitSample();
    await waitFor(() => expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100"));
    expect(screen.getByRole("button", { name: "Đã đủ mẫu" })).toBeDisabled();
    expect(screen.getByLabelText("Từ cần thực hiện")).toHaveValue("Chào");
  });

  it("does not count invalid takes and supports pause, resume and stop", async () => {
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Bắt đầu thu" }));
    await emitSample(false);
    expect(posts()).toHaveLength(0);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
    controls.cancel.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Tạm dừng" }));
    expect(controls.cancel).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "Tiếp tục" }));
    expect(screen.getByRole("button", { name: "Tạm dừng" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Dừng phiên" }));
    expect(screen.getByRole("button", { name: "Bắt đầu thu" })).toBeEnabled();
  });

  it("stops on save failure without counting or automatically retrying", async () => {
    controls.saveError = true;
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Bắt đầu thu" }));
    await emitSample();
    await waitFor(() => expect(screen.getByText(/Lỗi lưu thử nghiệm/)).toBeInTheDocument());
    expect(posts()).toHaveLength(1);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
    expect(screen.getByRole("button", { name: "Thử lưu lại" })).toBeEnabled();
    const firstKey = JSON.parse(posts()[0][1]!.body as string).sample_key;
    controls.saveError = false;
    fireEvent.click(screen.getByRole("button", { name: "Thử lưu lại" }));
    await waitFor(() => expect(posts()).toHaveLength(2));
    expect(JSON.parse(posts()[1][1]!.body as string).sample_key).toBe(firstKey);
  });

  it("does not start when batch progress cannot be loaded", async () => {
    controls.summaryError = true;
    render(<App />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Thu dữ liệu AI" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Thu dữ liệu AI" }));
    await waitFor(() => expect(screen.getByText(/Chưa đọc được tiến độ/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Bắt đầu thu" })).toBeDisabled();
  });

  it("counts only after save confirmation and stopping does not restart after an in-flight save", async () => {
    let resolve!: (response: unknown) => void;
    const saving = new Promise((done) => { resolve = done; });
    controls.deferredSave = () => saving;
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Bắt đầu thu" }));
    await emitSample();
    expect(posts()).toHaveLength(1);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
    fireEvent.click(screen.getByRole("button", { name: "Dừng phiên" }));
    const payload = JSON.parse(posts()[0][1]!.body as string);
    await act(async () => resolve({ ok: true, json: async () => ({
      status: "saved", sample_id: payload.sample_key, expected_label: "Chào", hand: "right",
      label_hand_count: 1, label_count: 1, relative_video_path: "batches/personal-100/chao/right/a.mp4",
    }) }));
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "1");
    expect(screen.getByRole("button", { name: "Bắt đầu thu" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Tạm dừng" })).not.toBeInTheDocument();
    expect(posts()).toHaveLength(1);
  });

  it("pauses on a capture error instead of automatically trying again", async () => {
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Bắt đầu thu" }));
    act(() => controls.captureOptions?.onError("Camera encode failed"));
    expect(screen.getByRole("button", { name: "Tiếp tục" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Tạm dừng" })).not.toBeInTheDocument();
    expect(posts()).toHaveLength(0);
  });

  it("uses the authoritative total when another window saved with the other hand", async () => {
    controls.counts = { right: 80, left: 18 };
    let resolve!: (response: unknown) => void;
    controls.deferredSave = () => new Promise((done) => { resolve = done; });
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Bắt đầu thu" }));
    await emitSample();
    const payload = JSON.parse(posts()[0][1]!.body as string);
    await act(async () => resolve({ ok: true, json: async () => ({
      status: "saved", sample_id: payload.sample_key, expected_label: "Chào", hand: "right",
      label_hand_count: 81, label_count: 100, relative_video_path: "batches/personal-100/chao/right/a.mp4",
    }) }));
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
    expect(screen.getByRole("button", { name: "Đã đủ mẫu" })).toBeDisabled();
  });

  it("an upload failing after Stop keeps the session stopped", async () => {
    let resolve!: (response: unknown) => void;
    controls.deferredSave = () => new Promise((done) => { resolve = done; });
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Bắt đầu thu" }));
    await emitSample();
    fireEvent.click(screen.getByRole("button", { name: "Dừng phiên" }));
    await act(async () => resolve({ ok: false, json: async () => ({ detail: "Upload failed" }) }));
    expect(screen.queryByRole("button", { name: "Tiếp tục" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dừng phiên" })).toBeDisabled();
    expect(posts()).toHaveLength(1);
  });
});
