import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { InferenceMetadata } from "@contracts";
import { useInferenceEndpoint, type InferenceEndpointOptions } from "./useInferenceEndpoint";
import { gpuRuntimeMatches, withInferenceToken } from "../lib/inferenceEndpoint";
import { runtimeMetadata } from "../test/runtimeFixture";

const gpu = { httpUrl: "https://gpu.example", wsUrl: "wss://gpu.example/ws/inference" };
const macWsUrl = "wss://api.example/ws/inference";

function runtime(gpuMetadata: InferenceMetadata | null, token = "signed") {
  const calls: string[] = [];
  const fetcher = vi.fn(async (url: string) => {
    calls.push(url);
    if (url === `${gpu.httpUrl}/metadata`) {
      return gpuMetadata ? new Response(JSON.stringify(gpuMetadata)) : new Response(null, { status: 404 });
    }
    if (url.endsWith("/api/v1/inference/token")) {
      return new Response(JSON.stringify({ token, expires_at: Math.floor(Date.now() / 1000) + 600 }));
    }
    throw new TypeError("unexpected");
  }) as unknown as typeof fetch;
  return { fetcher, calls };
}

function options(fetcher: typeof fetch, overrides: Partial<InferenceEndpointOptions> = {}): InferenceEndpointOptions {
  return {
    gpu, macWsUrl, platformUrl: "https://api.example", macMetadata: runtimeMetadata, enabled: true,
    socketStatus: "connected", isBusy: () => false, fetcher, ...overrides,
  };
}

async function flush() {
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
}

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); });

describe("gpuRuntimeMatches", () => {
  it("requires the same model, framing and labels on both runtimes", () => {
    const gpuMetadata = { ...runtimeMetadata, backend: "pytorch" };
    expect(gpuRuntimeMatches(gpuMetadata, runtimeMetadata)).toBe(true);
    expect(gpuRuntimeMatches({ ...gpuMetadata, model_version: "other" }, runtimeMetadata)).toBe(false);
    expect(gpuRuntimeMatches({ ...gpuMetadata, input_framing: "trim-bodycrop-v1" }, runtimeMetadata)).toBe(false);
    expect(gpuRuntimeMatches({ ...gpuMetadata, labels: ["Chào"] }, runtimeMetadata)).toBe(false);
    expect(gpuRuntimeMatches({ ...gpuMetadata, mock: true }, runtimeMetadata)).toBe(false);
  });

  it("adds the signed token to the socket URL", () => {
    expect(withInferenceToken(gpu.wsUrl, "a.b")).toBe("wss://gpu.example/ws/inference?token=a.b");
  });
});

describe("useInferenceEndpoint", () => {
  it("uses the GPU runtime once it serves the same model", async () => {
    const { fetcher } = runtime({ ...runtimeMetadata, backend: "pytorch" });
    const { result } = renderHook(() => useInferenceEndpoint(options(fetcher)));
    expect(result.current.kind).toBe("mac");
    await flush();
    expect(result.current.kind).toBe("gpu");
    expect(result.current.wsUrl).toBe(`${gpu.wsUrl}?token=signed`);
  });

  it("stays on the Mac when the GPU runtime is stopped or serves another model", async () => {
    for (const gpuMetadata of [null, { ...runtimeMetadata, model_version: "other" }]) {
      const { fetcher } = runtime(gpuMetadata);
      const { result, unmount } = renderHook(() => useInferenceEndpoint(options(fetcher)));
      await flush();
      expect(result.current.kind).toBe("mac");
      expect(result.current.wsUrl).toBe(macWsUrl);
      unmount();
    }
  });

  it("falls back to the Mac when the GPU socket stays down, then returns after a later probe", async () => {
    const { fetcher } = runtime({ ...runtimeMetadata, backend: "pytorch" });
    const { result, rerender } = renderHook((props: Partial<InferenceEndpointOptions>) =>
      useInferenceEndpoint(options(fetcher, props)), { initialProps: {} });
    await flush();
    expect(result.current.kind).toBe("gpu");
    rerender({ socketStatus: "disconnected" });
    await act(async () => { await vi.advanceTimersByTimeAsync(9_000); });
    expect(result.current.kind).toBe("mac");
    rerender({ socketStatus: "connected" });
    result.current.noteActivity();
    await act(async () => { await vi.advanceTimersByTimeAsync(16_000); });
    expect(result.current.kind).toBe("gpu");
  });

  it("does not switch while a sign awaits its prediction", async () => {
    const { fetcher } = runtime({ ...runtimeMetadata, backend: "pytorch" });
    let busy = true;
    const { result } = renderHook(() => useInferenceEndpoint(options(fetcher, { isBusy: () => busy })));
    await flush();
    expect(result.current.kind).toBe("mac");
    busy = false;
    await act(async () => { await vi.advanceTimersByTimeAsync(16_000); });
    expect(result.current.kind).toBe("gpu");
  });

  it("releases the GPU after a long idle period and stops probing until activity resumes", async () => {
    const { fetcher, calls } = runtime({ ...runtimeMetadata, backend: "pytorch" });
    const { result } = renderHook(() => useInferenceEndpoint(options(fetcher)));
    await flush();
    expect(result.current.kind).toBe("gpu");
    await act(async () => { await vi.advanceTimersByTimeAsync(10 * 60_000 + 4_000); });
    expect(result.current.kind).toBe("mac");
    const probes = calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(calls.length).toBe(probes);
    result.current.noteActivity();
    await act(async () => { await vi.advanceTimersByTimeAsync(16_000); });
    expect(result.current.kind).toBe("gpu");
  });

  it("stays on the Mac without a configured GPU runtime", async () => {
    const { fetcher } = runtime({ ...runtimeMetadata });
    const { result } = renderHook(() => useInferenceEndpoint(options(fetcher, { gpu: null })));
    await flush();
    expect(result.current.kind).toBe("mac");
    expect(fetcher).not.toHaveBeenCalled();
  });
});
