import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { BASELINE_HAND_PRESENCE_OFFSET } from "./lib/landmarkFeaturesV3";

const controls = vi.hoisted(() => ({ capture: null as null | { onFrames: (value: unknown) => void },
  start: vi.fn(), finishSave: null as null | (() => void), failStart: false, failSave: false, deferSave: false,
  startStatus: 503, requireConsent: false, emptyData: false, role: "admin" as "admin" | "viewer", calls: [] as string[] }));
vi.mock("./hooks/useWorkspacePlatform", () => ({ useWorkspacePlatform: () => ({ loading: false, available: true, authMode: "local_admin",
  context: { workspace_id: "local", name: "Doanh nghiệp", environment: "development" },
  user: { id: "admin", display_name: "Admin", email: "admin@example.com", role: controls.role },
  capabilities: { overview: true, recognize: true, data: true, models: true, monitoring: true, activity: true, team: true },
  login: vi.fn(), reload: vi.fn(), loadMembers: vi.fn(), members: [],
}) }));
vi.mock("./hooks/useCamera", () => ({ useCamera: () => ({ status: "ready", message: "Sẵn sàng", enable: vi.fn(), disable: vi.fn() }) }));
vi.mock("./hooks/useLandmarkInference", () => ({ useLandmarkInference: () => ({ status: "unavailable", labels: [], predict: vi.fn(), error: "test", modelVersion: "local" }) }));
vi.mock("./hooks/useInferenceSocket", () => ({ useInferenceSocket: () => ({ status: "disconnected", sendFrames: vi.fn() }) }));
vi.mock("./components/HandTrackingOverlay", () => ({ HandTrackingOverlay: () => null }));
vi.mock("./hooks/useSignCapture", () => ({ useSignCapture: (options: typeof controls.capture) => {
  controls.capture = options; return { status: "idle", start: controls.start, stop: vi.fn(), cancel: vi.fn() };
} }));

const datasetId = "123e4567-e89b-12d3-a456-426614174001", labelId = "123e4567-e89b-12d3-a456-426614174002";
const snapshot = () => ({ api_version: "1", workspace_id: "local", collection_enabled: true, default_labels: ["Cho"],
  collection_policy: { enabled: true, process_enabled: true, require_consent: false, default_quota_per_label: 100, revision: 0 },
  permissions: { manage: true, collect: true }, labels: [{ id: labelId, name: "Sales", parent_id: null,
    entries: [{ id: labelId, name: "Cho", kind: "sign" }], created_at: "2026-10-16T00:00:00Z" }],
  datasets: [{ id: datasetId, name: "Bộ dữ liệu mới", label_version_id: labelId, status: "draft", quota_per_label: 2,
    sample_count: 0, counts: { Cho: { right: 0, left: 0 } }, created_at: "2026-10-16T00:00:00Z" }],
  sessions: [] as Array<{ id: string; dataset_version_id: string; created_by: string; state: string; sample_count: number; created_at: string; updated_at: string }>, snapshots: [],
});

describe("workspace dataset collection", () => {
  beforeEach(() => {
    history.replaceState(null, "", "/?view=data");
    controls.calls = []; controls.finishSave = null; controls.failStart = false; controls.failSave = false; controls.deferSave = false; controls.start.mockClear();
    controls.role = "admin"; controls.startStatus = 503; controls.requireConsent = false; controls.emptyData = false;
    const data = snapshot();
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/api/v1/workspace/data")) return new Response(JSON.stringify({ ...data,
        default_labels: ["Cho", "Mua"], ...(controls.emptyData ? { labels: [], datasets: [] } : {}),
        collection_policy: { ...data.collection_policy, require_consent: controls.requireConsent },
        permissions: { manage: controls.role === "admin", collect: controls.role === "admin" } }));
      if (url.includes("/api/v1/workspace/data/") && init?.method === "POST") {
        const payload = JSON.parse(String(init.body));
        if (url.endsWith("/sessions")) {
          controls.calls.push("start");
          if (controls.failStart) return new Response("{}", { status: controls.startStatus });
          data.sessions.push({ id: payload.request_id, dataset_version_id: datasetId, state: "running", created_by: "admin",
            sample_count: 0, created_at: "2026-10-16T00:00:00Z", updated_at: "2026-10-16T00:00:00Z" });
        } else if (url.endsWith("/samples")) {
          controls.calls.push("save");
          if (controls.failSave) { controls.failSave = false; return new Response("{}", { status: 503 }); }
          if (data.sessions[0].state !== "running") return new Response("{}", { status: 409 });
          if (controls.deferSave) await new Promise<void>(resolve => { controls.finishSave = resolve; });
          data.datasets[0].counts.Cho.right++; data.datasets[0].sample_count++; data.sessions[0].sample_count++;
          controls.calls.push("saved");
          return new Response(JSON.stringify({ sample_id: payload.sample_key, expected_label: "Cho", hand: "right",
            label_hand_count: data.datasets[0].sample_count, label_count: data.datasets[0].sample_count }));
        } else if (url.endsWith("/state")) {
          if (!data.sessions.length) return new Response("{}", { status: 404 });
          controls.calls.push(payload.state); data.sessions[0].state = payload.state;
        }
        return new Response(JSON.stringify(data));
      }
      return new Response(JSON.stringify({ backend: "pytorch", model_version: "sales30-v3", frame_count: 16, labels: ["Cho"],
        collection_labels: ["Cho"], collection_enabled: true, mock: false, candidate_labels_unverified: false }));
    }));
  });
  afterEach(() => { vi.unstubAllGlobals(); history.replaceState(null, "", "/"); });
  async function begin() {
    const view = render(<App />);
    const select = await screen.findByLabelText("Bộ dữ liệu đang thu");
    await waitFor(() => expect(select).toBeEnabled());
    fireEvent.change(select, { target: { value: datasetId } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Bắt đầu thu" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Bắt đầu thu" }));
    return view;
  }
  async function emit() {
    const frame = new Array(128).fill(0); frame[BASELINE_HAND_PRESENCE_OFFSET] = 1;
    await act(async () => controls.capture?.onFrames({ frames: new Array(16).fill("data:image/webp;base64,AAAA"),
      sourceFrames: new Array(28).fill("data:image/webp;base64,AAAA"), durationMs: 2100,
      landmarkFrames: [], baselineLandmarkFrames: new Array(16).fill(frame) }));
  }
  it("lets an empty workspace preview default words without starting or saving a collection", async () => {
    controls.emptyData = true;
    render(<App />);
    await screen.findByText("Chưa có bộ dữ liệu.");
    const words = screen.getByRole("combobox", { name: "Từ cần thực hiện" });
    expect(Array.from((words as HTMLSelectElement).options).map(option => option.value)).toEqual(["Cho", "Mua"]);
    fireEvent.change(words, { target: { value: "Mua" } });
    expect(words).toHaveValue("Mua");
    expect(screen.getByLabelText("Video mẫu cho từ Mua")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Bắt đầu thu" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Tạo danh mục ký hiệu" }));
    expect(screen.getByRole("tab", { name: "Danh mục ký hiệu" })).toHaveAttribute("aria-selected", "true");
    expect(vi.mocked(fetch).mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  });
  it("restricts preview words to the selected dataset catalog before capture", async () => {
    render(<App />);
    const dataset = await screen.findByLabelText("Bộ dữ liệu đang thu");
    await waitFor(() => expect(dataset).toBeEnabled());
    fireEvent.change(screen.getByRole("combobox", { name: "Từ cần thực hiện" }), { target: { value: "Mua" } });
    expect(screen.getByRole("combobox", { name: "Từ cần thực hiện" })).toHaveValue("Mua");
    fireEvent.change(dataset, { target: { value: datasetId } });
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Từ cần thực hiện" })).toHaveValue("Cho"));
    expect(screen.queryByRole("option", { name: /Mua/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Bắt đầu thu" })).toBeEnabled();
  });
  it("requires an explicit consent checkbox and sends it only after acceptance", async () => {
    controls.requireConsent = true;
    render(<App />);
    const select = await screen.findByLabelText("Bộ dữ liệu đang thu");
    await waitFor(() => expect(select).toBeEnabled());
    fireEvent.change(select, { target: { value: datasetId } });
    const consent = await screen.findByRole("checkbox", { name: "Tôi đồng ý lưu video và dữ liệu mẫu cho workspace này." });
    expect(consent).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Bắt đầu thu" })).toBeDisabled();
    fireEvent.click(consent);
    await waitFor(() => expect(screen.getByRole("button", { name: "Bắt đầu thu" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Bắt đầu thu" }));
    await waitFor(() => expect(controls.calls).toContain("start"));
    const write = vi.mocked(fetch).mock.calls.find(([url]) => String(url).endsWith("/api/v1/workspace/data/sessions"))!;
    expect(JSON.parse(String(write[1]?.body)).consent).toBe(true);
  });
  it("requires a server session and saves full source frames to platform, never inference collection", async () => {
    await begin();
    await waitFor(() => expect(screen.getByRole("button", { name: "Tạm dừng" })).toBeEnabled());
    await emit();
    await waitFor(() => expect(controls.calls).toContain("saved"));
    const posts = vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === "POST");
    const save = posts.find(([url]) => String(url).endsWith("/samples"))!;
    expect(String(save[0])).toContain("/api/v1/workspace/data/sessions/");
    expect(JSON.parse(String(save[1]?.body)).frames).toHaveLength(28);
    expect(posts.some(([url]) => String(url).includes("/collection/samples") || String(url).includes("/audit/client-events"))).toBe(false);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "1");
  });
  it("waits for an in-flight sample ACK before closing the persisted session", async () => {
    controls.deferSave = true;
    await begin(); await waitFor(() => expect(screen.getByRole("button", { name: "Tạm dừng" })).toBeEnabled());
    await emit(); await waitFor(() => expect(controls.finishSave).not.toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Dừng phiên" }));
    expect(controls.calls).toEqual(["start", "save"]);
    await act(async () => controls.finishSave!());
    await waitFor(() => expect(controls.calls).toEqual(["start", "save", "saved", "stopped"]));
  });
  it("never starts capture when backend session creation fails", async () => {
    controls.failStart = true;
    await begin();
    await screen.findByRole("button", { name: "Thử lại thao tác" });
    expect(controls.start).not.toHaveBeenCalled();
    await emit();
    expect(controls.calls).toEqual(["start"]);
  });
  it("explicitly retries a failed sample without restarting automatic collection", async () => {
    controls.failSave = true;
    await begin(); await waitFor(() => expect(screen.getByRole("button", { name: "Tạm dừng" })).toBeEnabled());
    await emit(); await waitFor(() => expect(controls.calls).toContain("paused"));
    fireEvent.click(screen.getByRole("button", { name: "Thử lưu lại" }));
    await waitFor(() => expect(controls.calls).toContain("saved"));
    await waitFor(() => expect(controls.calls.at(-1)).toBe("paused"));
    expect(screen.getByRole("button", { name: "Tiếp tục" })).toBeInTheDocument();
    const uploads = vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith("/samples"));
    expect(uploads).toHaveLength(2);
    expect(uploads[0][1]?.body).toBe(uploads[1][1]?.body);
  });
  it("discards pending capture and late upload ACK when the same user's role changes", async () => {
    controls.deferSave = true;
    const view = await begin();
    await waitFor(() => expect(screen.getByRole("button", { name: "Tạm dừng" })).toBeEnabled());
    await emit(); await waitFor(() => expect(controls.finishSave).not.toBeNull());
    controls.role = "viewer";
    view.rerender(<App />);
    await waitFor(() => expect(screen.getByLabelText("Bộ dữ liệu đang thu")).toBeDisabled());
    await act(async () => controls.finishSave!());
    expect(screen.getByLabelText("Bộ dữ liệu đang thu")).toHaveValue("");
    expect(screen.queryByText(/Đã lưu 1\/2/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Thử lưu lại" })).not.toBeInTheDocument();
    expect(controls.calls).toEqual(["start", "save", "saved"]);
  });
  it("allows a new session after a definite start rejection and refresh", async () => {
    controls.failStart = true; controls.startStatus = 409;
    await begin();
    await screen.findByRole("alert");
    controls.failStart = false;
    fireEvent.click(screen.getByRole("button", { name: "Làm mới dữ liệu" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Bắt đầu thu" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Bắt đầu thu" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Tạm dừng" })).toBeEnabled());
    expect(controls.calls).toEqual(["start", "start"]);
  });
  it("keeps the original session creation ID when its outcome is unknown", async () => {
    controls.failStart = true;
    await begin();
    await screen.findByRole("button", { name: "Thử lại thao tác" });
    fireEvent.click(screen.getByRole("button", { name: "Làm mới dữ liệu" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Thử lại thao tác" })).toBeEnabled());
    controls.failStart = false;
    fireEvent.click(screen.getByRole("button", { name: "Thử lại thao tác" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Tạm dừng" })).toBeEnabled());
    const starts = vi.mocked(fetch).mock.calls.filter(([url, init]) => String(url).endsWith("/sessions") && init?.method === "POST");
    expect(starts).toHaveLength(2);
    expect(starts[0][1]?.body).toBe(starts[1][1]?.body);
  });
});
