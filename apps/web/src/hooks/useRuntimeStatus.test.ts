import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useRuntimeStatus } from "./useRuntimeStatus";
import { runtimeHealth, runtimeMetadata } from "../test/runtimeFixture";

const endpoint = "http://localhost:8003";
const reply = (body: unknown) => new Response(JSON.stringify(body));
const respond = (url: string) => reply(url.endsWith("/health") ? runtimeHealth : runtimeMetadata);

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("useRuntimeStatus", () => {
  it("reads health and validated metadata from the selected inference endpoint", async () => {
    const fetcher = vi.fn(async (url: string) => respond(url));
    vi.stubGlobal("fetch", fetcher);
    const { result } = renderHook(() => useRuntimeStatus(`${endpoint}/`, true));
    await waitFor(() => expect(result.current.metadata).toEqual(runtimeMetadata));
    expect(result.current.health).toEqual(runtimeHealth);
    expect(result.current.healthError).toBe("");
    expect(result.current.healthLatencyMs).toBeGreaterThanOrEqual(0);
    expect(result.current.checkedAt).not.toBeNull();
    expect(fetcher).toHaveBeenCalledWith(`${endpoint}/health`, expect.objectContaining({ cache: "no-store" }));
    expect(fetcher).toHaveBeenCalledWith(`${endpoint}/metadata`, expect.anything());
  });

  it("retains stale metadata on failure and recovers on manual refresh", async () => {
    let offline = false;
    vi.stubGlobal("fetch", async (url: string) => {
      if (offline) throw new TypeError("Failed to fetch");
      return respond(url);
    });
    const { result } = renderHook(() => useRuntimeStatus(endpoint, true));
    await waitFor(() => expect(result.current.metadata).toEqual(runtimeMetadata));
    const lastHealthyAt = result.current.lastHealthyAt;
    offline = true;
    await act(async () => { await result.current.refresh(); });
    expect(result.current.healthError).not.toBe("");
    expect(result.current.healthLatencyMs).toBeNull();
    expect(result.current.metadata).toEqual(runtimeMetadata);
    expect(result.current.lastHealthyAt).toBe(lastHealthyAt);
    offline = false;
    await act(async () => { await result.current.refresh(); });
    expect(result.current.healthError).toBe("");
    expect(result.current.metadataError).toBe("");
  });

  it("can report healthy HTTP with unavailable metadata without inventing model labels", async () => {
    vi.stubGlobal("fetch", async (url: string) => url.endsWith("/health")
      ? reply(runtimeHealth) : new Response(null, { status: 503 }));
    const { result } = renderHook(() => useRuntimeStatus(endpoint, true));
    await waitFor(() => expect(result.current.checking).toBe(false));
    expect(result.current.health).toEqual(runtimeHealth);
    expect(result.current.metadata).toBeNull();
    expect(result.current.metadataError).toContain("503");
  });

  it.each([
    { ...runtimeMetadata, labels: [123] },
    { ...runtimeMetadata, mock: "false" },
    { ...runtimeMetadata, model_version: "" },
    { ...runtimeMetadata, confidence_threshold: 2 },
  ])("rejects malformed metadata %#", async metadata => {
    vi.stubGlobal("fetch", async (url: string) => reply(url.endsWith("/health") ? runtimeHealth : metadata));
    const { result } = renderHook(() => useRuntimeStatus(endpoint, true));
    await waitFor(() => expect(result.current.metadataError).not.toBe(""));
    expect(result.current.metadata).toBeNull();
  });

  it("rejects mismatched health and metadata identities", async () => {
    vi.stubGlobal("fetch", async (url: string) => reply(url.endsWith("/health")
      ? runtimeHealth : { ...runtimeMetadata, model_version: "different-model" }));
    const { result } = renderHook(() => useRuntimeStatus(endpoint, true));
    await waitFor(() => expect(result.current.metadataError).toContain("không khớp"));
    expect(result.current.metadata).toBeNull();
  });

  it("clears old endpoint data immediately and ignores replies after switching endpoint", async () => {
    const pending: Array<(response: Response) => void> = [];
    vi.stubGlobal("fetch", (url: string) => url.startsWith(endpoint)
      ? new Promise<Response>(resolve => pending.push(resolve)) : Promise.resolve(respond(url)));
    const { result, rerender } = renderHook(({ url }) => useRuntimeStatus(url, true), { initialProps: { url: endpoint } });
    rerender({ url: "http://localhost:8002" });
    expect(result.current.health).toBeNull();
    expect(result.current.metadata).toBeNull();
    await waitFor(() => expect(result.current.metadata).toEqual(runtimeMetadata));
    await act(async () => { pending.forEach(resolve => resolve(reply({ ...runtimeMetadata, model_version: "old" }))); });
    expect(result.current.endpoint).toBe("http://localhost:8002");
    expect(result.current.metadata?.model_version).toBe("sales30-runtime-v1");
  });

  it("polls every ten seconds, pauses in hidden tabs, and stops when disabled", async () => {
    vi.useFakeTimers();
    let hidden = false;
    vi.spyOn(document, "visibilityState", "get").mockImplementation(() => hidden ? "hidden" : "visible");
    const fetcher = vi.fn(async (url: string) => respond(url));
    vi.stubGlobal("fetch", fetcher);
    const { result, rerender } = renderHook(({ enabled }) => useRuntimeStatus(endpoint, enabled), { initialProps: { enabled: true } });
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    const firstCheckedAt = result.current.checkedAt;
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(result.current.checkedAt).toBeGreaterThan(firstCheckedAt!);
    expect(fetcher).toHaveBeenCalledTimes(4);
    hidden = true;
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(fetcher).toHaveBeenCalledTimes(4);
    hidden = false;
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    expect(fetcher).toHaveBeenCalledTimes(6);
    rerender({ enabled: false });
    await act(async () => { await vi.advanceTimersByTimeAsync(20000); });
    expect(fetcher).toHaveBeenCalledTimes(6);
    vi.restoreAllMocks();
  });

  it("times out hung requests, prevents overlaps, and aborts on unmount", async () => {
    vi.useFakeTimers();
    const signals: AbortSignal[] = [];
    const fetcher = vi.fn((_url: string, init: RequestInit) => new Promise<Response>((_resolve, reject) => {
      const signal = init.signal!;
      signals.push(signal);
      signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    }));
    vi.stubGlobal("fetch", fetcher);
    const { result, unmount } = renderHook(() => useRuntimeStatus(endpoint, true));
    await act(async () => { await result.current.refresh(); });
    expect(fetcher).toHaveBeenCalledTimes(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(result.current.healthError).toContain("Hết thời gian");
    expect(result.current.checking).toBe(false);
    expect(signals.every(signal => signal.aborted)).toBe(true);
    act(() => { void result.current.refresh(); });
    unmount();
    expect(signals.every(signal => signal.aborted)).toBe(true);
  });

  it("does not fetch while disabled and works under StrictMode", async () => {
    const fetcher = vi.fn(async (url: string) => respond(url));
    vi.stubGlobal("fetch", fetcher);
    const { result, rerender } = renderHook(({ enabled }) => useRuntimeStatus(endpoint, enabled), {
      initialProps: { enabled: false }, wrapper: ({ children }) => createElement(StrictMode, null, children),
    });
    expect(fetcher).not.toHaveBeenCalled();
    rerender({ enabled: true });
    await waitFor(() => expect(result.current.metadata).toEqual(runtimeMetadata));
  });
});
