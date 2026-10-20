import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useManualTests } from "./useManualTests";

const runtime = { enabled: true, backend: "coreml", model_version: "fixture-v1", runtime_key: "runtime-a",
  labels: ["Mua", "Tôi", "Không ký hiệu"], confidence_threshold: .7, margin_threshold: .15,
  mock: false, candidate_labels_unverified: false };
const emptySummary = { groups: [], recorded: 0, independent_evaluation: false };
const captured = { frames: Array(16).fill("data:image/webp;base64,AA=="), sourceFrames: Array(20).fill("source"),
  durationMs: 1500, landmarkFrames: [], baselineLandmarkFrames: [] };
const context = { expected_label: "Mua", signer_id: "tester-1", hand: "right" as const,
  distance: "standard" as const, lighting: "normal" as const, negative_action: null };

afterEach(() => vi.unstubAllGlobals());

it("does not publish an old backend summary after switching model endpoints", async () => {
  let finishOld!: (value: Response) => void;
  vi.stubGlobal("fetch", async (url: string) => {
    const old = url.startsWith("http://old");
    if (url.endsWith("/config")) return new Response(JSON.stringify({ ...runtime, model_version: old ? "old" : "new" }));
    if (url.endsWith("/summary") && old) return new Promise<Response>(resolve => { finishOld = resolve; });
    if (url.endsWith("/summary")) return new Response(JSON.stringify({ ...emptySummary, recorded: 2 }));
    return new Response(JSON.stringify({ trials: [] }));
  });
  const { result, rerender } = renderHook(({ base }) => useManualTests(base, "session-1"), { initialProps: { base: "http://old" } });
  await waitFor(() => expect(result.current.runtime?.model_version).toBe("old"));
  rerender({ base: "http://new" });
  await waitFor(() => expect(result.current.summary.recorded).toBe(2));
  await act(async () => { finishOld(new Response(JSON.stringify({ ...emptySummary, recorded: 99 }))); });
  expect(result.current.summary.recorded).toBe(2);
  expect(result.current.runtime?.model_version).toBe("new");
});

it("rejects a stale response even after switching A to B and back to A", async () => {
  let finishOld!: (value: Response) => void;
  let summaries = 0;
  vi.stubGlobal("fetch", async (url: string) => {
    const old = url.startsWith("http://old");
    if (url.endsWith("/config")) return new Response(JSON.stringify({ ...runtime, model_version: old ? "old" : "new" }));
    if (url.endsWith("/summary") && old && ++summaries === 1) return new Promise<Response>(resolve => { finishOld = resolve; });
    if (url.endsWith("/summary")) return new Response(JSON.stringify({ ...emptySummary, recorded: old ? 3 : 2 }));
    return new Response(JSON.stringify({ trials: [] }));
  });
  const { result, rerender } = renderHook(({ base }) => useManualTests(base, "session-1"), { initialProps: { base: "http://old" } });
  await waitFor(() => expect(result.current.runtime?.model_version).toBe("old"));
  rerender({ base: "http://new" });
  await waitFor(() => expect(result.current.summary.recorded).toBe(2));
  rerender({ base: "http://old" });
  await waitFor(() => expect(result.current.summary.recorded).toBe(3));
  await act(async () => { finishOld(new Response(JSON.stringify({ ...emptySummary, recorded: 99 }))); });
  expect(result.current.summary.recorded).toBe(3);
});

function server(options: { failSave?: boolean; failReview?: boolean } = {}) {
  const requests: Record<string, unknown>[] = [];
  let saved: Record<string, unknown> | null = null;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/config")) return new Response(JSON.stringify(runtime));
    if (url.includes("/summary")) return new Response(JSON.stringify(emptySummary));
    if (url.endsWith("/review")) {
      return new Response(JSON.stringify({ saved: true }), { status: options.failReview ? 500 : 200 });
    }
    if (init?.method === "POST") {
      const request = JSON.parse(init.body as string);
      requests.push(request);
      if (options.failSave && requests.length === 1) throw new TypeError("network unavailable");
      saved = { ...request, outcome: "correct", model_version: "fixture-v1", prediction: { status: "ok", label: "Mua", confidence: .95 },
        review: { valid: true, notes: "", reviewer: null }, review_history: [], video_available: true };
      return new Response(JSON.stringify(saved));
    }
    return new Response(JSON.stringify({ trials: saved ? [saved] : [] }));
  }));
  return requests;
}

it("retains the same capture identity and expected label when a lost response is retried", async () => {
  const requests = server({ failSave: true });
  const { result } = renderHook(() => useManualTests("http://backend", "session-1"));
  await waitFor(() => expect(result.current.runtime?.model_version).toBe("fixture-v1"));
  await act(() => result.current.saveCapture(context, captured, 1000));
  expect(result.current.pending?.expected_label).toBe("Mua");
  expect(result.current.notice).toContain("chưa được xác nhận");
  await act(() => result.current.retry());
  expect(result.current.pending).toBeNull();
  expect(result.current.trials[0].expected_label).toBe("Mua");
  expect(requests[0].trial_id).toBe(requests[1].trial_id);
  expect(requests[0].captured_at).toBe(requests[1].captured_at);
});

it("keeps a saved trial visible when reloading statistics fails", async () => {
  server();
  const { result } = renderHook(() => useManualTests("http://backend", "session-1"));
  await waitFor(() => expect(result.current.runtime).not.toBeNull());
  const original = fetch;
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) =>
    url.includes("/summary") ? new Response("{}", { status: 500 }) : original(url, init));
  await act(() => result.current.saveCapture(context, captured, 1000));
  expect(result.current.pending).toBeNull();
  expect(result.current.lastTrial?.outcome).toBe("correct");
  expect(result.current.notice).toContain("đã lưu");
});

it("records encoding failures as technical events without claiming prediction frames", async () => {
  const requests = server();
  const { result } = renderHook(() => useManualTests("http://backend", "session-1"));
  await waitFor(() => expect(result.current.runtime).not.toBeNull());
  await act(() => result.current.saveFailure(context, "Không thu được frame", 1000));
  expect(requests[0].frames).toEqual([]);
  expect(requests[0].technical_error).toBe("Không thu được frame");
});

it("records an incomplete camera capture as a technical failure rather than a permanently pending invalid request", async () => {
  const requests = server();
  const { result } = renderHook(() => useManualTests("http://backend", "session-1"));
  await waitFor(() => expect(result.current.runtime).not.toBeNull());
  await act(() => result.current.saveCapture(context, { ...captured, sourceFrames: ["source"] }, 1000));
  expect(requests[0].frames).toEqual([]);
  expect(requests[0].source_frames).toEqual([]);
  expect(requests[0].technical_error).toBeTruthy();
});

it("does not pretend a review was saved when the server rejects it", async () => {
  server({ failReview: true });
  const { result } = renderHook(() => useManualTests("http://backend", "session-1"));
  await waitFor(() => expect(result.current.runtime).not.toBeNull());
  await act(() => result.current.saveCapture(context, captured, 1000));
  let accepted = true;
  await act(async () => { accepted = await result.current.review("trial-1", false, "Clip không đủ", "staff"); });
  expect(accepted).toBe(false);
  expect(result.current.notice).toContain("Chưa lưu được kiểm định");
});

it("reports a reload failure instead of silently keeping stale statistics", async () => {
  server();
  const { result } = renderHook(() => useManualTests("http://backend", "session-1"));
  await waitFor(() => expect(result.current.runtime).not.toBeNull());
  vi.stubGlobal("fetch", async () => new Response("{}", { status: 503 }));
  await act(() => result.current.reload());
  expect(result.current.notice).toContain("Chưa tải lại được kết quả");
});

it("confirms a saved review even if the following statistics read fails", async () => {
  server();
  const { result } = renderHook(() => useManualTests("http://backend", "session-1"));
  await waitFor(() => expect(result.current.runtime).not.toBeNull());
  const original = fetch;
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) =>
    url.includes("/summary") ? new Response("{}", { status: 500 }) : original(url, init));
  let saved = false;
  await act(async () => { saved = await result.current.review("trial-1", true, "Đủ cử chỉ", "staff"); });
  expect(saved).toBe(true);
  expect(result.current.notice).toContain("Đã lưu kiểm định");
});

it("reloads config after an initially unavailable backend comes online", async () => {
  server();
  const original = fetch;
  let unavailable = true;
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    if (url.endsWith("/config") && unavailable) throw new TypeError("offline");
    return original(url, init);
  });
  const { result } = renderHook(() => useManualTests("http://backend", "session-1"));
  await waitFor(() => expect(result.current.notice).toContain("Chưa kết nối"));
  unavailable = false;
  await act(() => result.current.reload());
  expect(result.current.runtime?.runtime_key).toBe("runtime-a");
});

it("recovers a rejected stale-runtime capture explicitly without relabeling its provenance", async () => {
  server();
  const { result } = renderHook(() => useManualTests("http://backend", "session-1"));
  await waitFor(() => expect(result.current.runtime).not.toBeNull());
  const original = fetch;
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    if (url.endsWith("/config")) return new Response(JSON.stringify({ ...runtime, runtime_key: "runtime-b" }));
    if (init?.method === "POST" && JSON.parse(init.body as string).runtime_key === "runtime-a") {
      return new Response(JSON.stringify({ detail: "Runtime changed; refresh before starting a new test" }), { status: 409 });
    }
    return original(url, init);
  });
  await act(() => result.current.saveCapture(context, captured, 1000));
  const old = result.current.pending;
  expect(result.current.rejected).toBe(true);
  await act(() => result.current.reload());
  expect(result.current.runtime?.runtime_key).toBe("runtime-b");
  expect(result.current.pending).toEqual(old);
  act(() => result.current.discardRejected());
  expect(result.current.pending).toBeNull();
  await act(() => result.current.saveCapture(context, captured, 2000));
  expect(result.current.lastTrial?.runtime_key).toBe("runtime-b");
  expect(result.current.lastTrial?.trial_id).not.toBe(old?.trial_id);
});
