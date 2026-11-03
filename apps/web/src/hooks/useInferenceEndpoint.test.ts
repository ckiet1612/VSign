import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { InferenceMetadata } from "@contracts";
import { useInferenceEndpoint, type InferenceEndpointOptions } from "./useInferenceEndpoint";
import { gpuRuntimeMatches, withInferenceToken } from "../lib/inferenceEndpoint";
import { runtimeMetadata } from "../test/runtimeFixture";

const gpu = { httpUrl: "https://gpu.example", wsUrl: "wss://gpu.example/ws/inference" };
const aws = { httpUrl: "https://aws.example", wsUrl: "wss://aws.example/ws/inference" };
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

  it.each(["frame_count", "frame_width", "frame_height"] as const)("rejects mismatched %s", field => {
    expect(gpuRuntimeMatches({ ...runtimeMetadata, [field]: runtimeMetadata[field] + 1 }, runtimeMetadata)).toBe(false);
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

  it("keeps a connected GPU socket through a transient metadata probe failure", async () => {
    let fail = false;
    const { fetcher: base } = runtime(runtimeMetadata);
    const fetcher: typeof fetch = (url, init) => fail && String(url).endsWith("/metadata")
      ? Promise.resolve(new Response(null, { status: 503 })) : base(url, init);
    const { result } = renderHook(() => useInferenceEndpoint(options(fetcher)));
    await flush();
    expect(result.current.kind).toBe("gpu");
    fail = true;
    await act(async () => { await vi.advanceTimersByTimeAsync(19_000); });
    expect(result.current.kind).toBe("gpu");
  });

  it("fails over when a renewed token socket hangs even though the previous token socket is connected", async () => {
    let generation = 0;
    const fetcher = (async (url: string) => url.endsWith("/metadata")
      ? new Response(JSON.stringify(runtimeMetadata))
      : new Response(JSON.stringify({ token: `token-${++generation}`, expires_at: Date.now() / 1000 + 600 }))) as typeof fetch;
    const { result, rerender } = renderHook((props: Partial<InferenceEndpointOptions>) =>
      useInferenceEndpoint(options(fetcher, props)), { initialProps: {} });
    await flush();
    const previousUrl = result.current.wsUrl;
    rerender({ activeWsUrl: previousUrl });
    await act(async () => { await vi.advanceTimersByTimeAsync(300_000); });
    expect(result.current.wsUrl).toBe(`${gpu.wsUrl}?token=token-2`);
    await act(async () => { await vi.advanceTimersByTimeAsync(9_000); });
    expect(result.current.kind).toBe("mac");
  });

  it("refreshes compatibility metadata without renewing a still-valid token", async () => {
    let model = runtimeMetadata;
    let tokenRequests = 0;
    const fetcher = (async (url: string) => {
      if (url.endsWith("/metadata")) return new Response(JSON.stringify(model));
      tokenRequests += 1;
      return new Response(JSON.stringify({ token: "signed", expires_at: Date.now() / 1000 + 600 }));
    }) as typeof fetch;
    const { result, rerender } = renderHook((props: Partial<InferenceEndpointOptions>) =>
      useInferenceEndpoint(options(fetcher, props)), { initialProps: {} });
    await flush();
    model = { ...runtimeMetadata, model_version: "updated-model" };
    rerender({ macMetadata: model, activeWsUrl: result.current.wsUrl });
    await act(async () => { await vi.advanceTimersByTimeAsync(18_000); });
    expect(result.current.kind).toBe("gpu");
    expect(result.current.wsUrl).toBe(`${gpu.wsUrl}?token=signed`);
    expect(tokenRequests).toBe(1);
  });
});

describe("GPU provider priority", () => {
  function providers({ modalReady = true, awsReady = true, slowModal = false } = {}) {
    const state = { modalReady, awsReady };
    const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/api/v1/inference/token")) {
        return new Response(JSON.stringify({ token: "signed", expires_at: Date.now() / 1000 + 600 }));
      }
      if (url === `${gpu.httpUrl}/metadata` && slowModal) {
        return new Promise<Response>((_, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
        });
      }
      const ready = url === `${gpu.httpUrl}/metadata` ? state.modalReady : state.awsReady;
      return ready ? new Response(JSON.stringify(runtimeMetadata)) : new Response(null, { status: 503 });
    }) as unknown as typeof fetch;
    return { state, fetcher };
  }

  it("prefers Modal when both GPUs are ready", async () => {
    const { fetcher } = providers();
    const { result } = renderHook(() => useInferenceEndpoint(options(fetcher, { aws })));
    await flush();
    expect(result.current.provider).toBe("modal");
    expect(result.current.wsUrl).toBe(`${gpu.wsUrl}?token=signed`);
  });

  it("uses AWS when Modal is unavailable", async () => {
    const { fetcher } = providers({ modalReady: false });
    const { result } = renderHook(() => useInferenceEndpoint(options(fetcher, { aws })));
    await flush();
    expect(result.current.provider).toBe("aws");
    expect(result.current.wsUrl).toBe(`${aws.wsUrl}?token=signed`);
  });

  it("does not wait for a cold Modal request before using AWS", async () => {
    const { fetcher } = providers({ slowModal: true });
    const { result } = renderHook(() => useInferenceEndpoint(options(fetcher, { aws })));
    await flush();
    expect(result.current.provider).toBe("aws");
  });

  it("supports AWS without a configured Modal endpoint", async () => {
    const { fetcher } = providers();
    const { result } = renderHook(() => useInferenceEndpoint(options(fetcher, { gpu: null, aws })));
    await flush();
    expect(result.current.provider).toBe("aws");
  });

  it("returns to Modal once it recovers, but waits for a pending sign", async () => {
    const { fetcher, state } = providers({ modalReady: false });
    let busy = false;
    const { result } = renderHook(() => useInferenceEndpoint(options(fetcher, { aws, isBusy: () => busy })));
    await flush();
    expect(result.current.provider).toBe("aws");
    state.modalReady = true;
    busy = true;
    await act(async () => { await vi.advanceTimersByTimeAsync(16_000); });
    expect(result.current.provider).toBe("aws");
    busy = false;
    await act(async () => { await vi.advanceTimersByTimeAsync(3_000); });
    expect(result.current.provider).toBe("modal");
  });

  it("falls back to AWS if the selected Modal socket never opens while Mac stays parked", async () => {
    const { fetcher } = providers();
    const { result } = renderHook(() => useInferenceEndpoint(options(fetcher, {
      aws, activeWsUrl: macWsUrl, socketStatus: "connected",
    })));
    await flush();
    expect(result.current.provider).toBe("modal");
    await act(async () => { await vi.advanceTimersByTimeAsync(9_000); });
    expect(result.current.provider).toBe("aws");
  });

  it("falls back from a disconnected Modal socket to AWS", async () => {
    const { fetcher } = providers();
    const { result, rerender } = renderHook((props: Partial<InferenceEndpointOptions>) =>
      useInferenceEndpoint(options(fetcher, { aws, ...props })), { initialProps: {} });
    await flush();
    rerender({ socketStatus: "disconnected" });
    await act(async () => { await vi.advanceTimersByTimeAsync(9_000); });
    expect(result.current.provider).toBe("aws");
  });

  it("keeps Mac when neither GPU is ready", async () => {
    const { fetcher } = providers({ modalReady: false, awsReady: false });
    const { result } = renderHook(() => useInferenceEndpoint(options(fetcher, { aws })));
    await flush();
    expect(result.current.kind).toBe("mac");
    expect(result.current.provider).toBeNull();
  });

  it("rejects an AWS endpoint serving a different model", async () => {
    const { fetcher: base } = providers({ modalReady: false });
    const fetcher: typeof fetch = (url, init) => String(url) === `${aws.httpUrl}/metadata`
      ? Promise.resolve(new Response(JSON.stringify({ ...runtimeMetadata, model_version: "other" })))
      : base(url, init);
    const { result } = renderHook(() => useInferenceEndpoint(options(fetcher, { aws })));
    await flush();
    expect(result.current.kind).toBe("mac");
  });

  it("does not keep an AWS selection after the endpoint is removed", async () => {
    const { fetcher } = providers({ modalReady: false });
    const { result, rerender } = renderHook((props: Partial<InferenceEndpointOptions>) =>
      useInferenceEndpoint(options(fetcher, props)), { initialProps: { aws } as Partial<InferenceEndpointOptions> });
    await flush();
    expect(result.current.provider).toBe("aws");
    rerender({ aws: undefined });
    await flush();
    expect(result.current.kind).toBe("mac");
  });
});
