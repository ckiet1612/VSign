import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useInferenceSocket } from "./useInferenceSocket";

class Socket {
  static all: Socket[] = [];
  readyState = 1;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(public url: string) { Socket.all.push(this); }
  close() { this.readyState = 3; }
  send: (data: string) => void = () => undefined;
}

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); Socket.all = []; });

it("keeps a pending AWS reply and sends on AWS until the Modal handover is safe", () => {
  vi.useFakeTimers();
  vi.stubGlobal("WebSocket", Socket);
  let busy = false;
  const received: number[] = [];
  const sent: string[] = [];
  const { result, rerender, unmount } = renderHook(({ url }) =>
    useInferenceSocket(url, p => { received.push(p.sequence); busy = p.sequence !== 2; }, "current", () => busy),
  { initialProps: { url: "wss://aws.example/ws/inference" } });
  const aws = Socket.all[0];
  aws.send = () => { sent.push("aws"); };
  act(() => aws.onopen?.());
  rerender({ url: "wss://modal.example/ws/inference" });
  const modal = Socket.all[1];
  modal.readyState = 0;
  modal.send = () => { sent.push("modal"); };
  busy = true;
  act(() => result.current.sendFrames({ sequence: 1 } as never));
  act(() => { modal.readyState = 1; modal.onopen?.(); });
  expect(aws.readyState).toBe(1);
  expect(result.current.activeUrl).toBe(aws.url);
  act(() => modal.onmessage?.(new MessageEvent("message", {
    data: JSON.stringify({ type: "runtime_info", gpu_name: "Modal GPU" }),
  })));
  expect(result.current.gpuName).toBeNull();
  act(() => result.current.sendFrames({ sequence: 2 } as never));
  expect(sent).toEqual(["aws", "aws"]);
  const prediction = { type: "prediction", sequence: 1, status: "ok", label: "Tôi", confidence: .9,
    top_k: [{ label: "Tôi", confidence: .9 }], model_version: "v", latency_ms: 1 };
  act(() => aws.onmessage?.(new MessageEvent("message", { data: JSON.stringify(prediction) })));
  expect(received).toEqual([1]);
  act(() => vi.advanceTimersByTime(100));
  expect(aws.readyState).toBe(1);
  act(() => aws.onmessage?.(new MessageEvent("message", {
    data: JSON.stringify({ ...prediction, sequence: 2 }),
  })));
  expect(received).toEqual([1, 2]);
  act(() => vi.advanceTimersByTime(100));
  expect(aws.readyState).toBe(3);
  expect(result.current.activeUrl).toBe(modal.url);
  expect(result.current.gpuName).toBe("Modal GPU");
  act(() => result.current.sendFrames({ sequence: 3 } as never));
  expect(sent).toEqual(["aws", "aws", "modal"]);
  unmount();
  expect(vi.getTimerCount()).toBe(0);
});

it("reports the connected GPU and clears its name on a new connection", () => {
  vi.stubGlobal("WebSocket", Socket);
  const onPrediction = vi.fn();
  const { result, rerender } = renderHook(({ url }) => useInferenceSocket(url, onPrediction, "current"),
    { initialProps: { url: "wss://gpu.example/ws/inference" } });
  const socket = Socket.all[0];
  act(() => socket.onopen?.());
  act(() => socket.onmessage?.(new MessageEvent("message", {
    data: JSON.stringify({ type: "runtime_info", gpu_name: "NVIDIA A10G" }),
  })));
  expect(result.current.gpuName).toBe("NVIDIA A10G");
  expect(onPrediction).not.toHaveBeenCalled();
  rerender({ url: "wss://mac.example/ws/inference" });
  expect(result.current.gpuName).toBe("NVIDIA A10G");
  act(() => Socket.all[1].onopen?.());
  expect(result.current.gpuName).toBeNull();
});

it("ignores predictions and open/error events from the previous model socket", () => {
  vi.stubGlobal("WebSocket", Socket);
  const received: number[] = [];
  const { result, rerender } = renderHook(({ url }) => useInferenceSocket(url, p => received.push(p.sequence)),
    { initialProps: { url: "ws://localhost:8000/ws/inference" } });
  const old = Socket.all[0];
  act(() => old.onopen?.());
  expect(result.current.status).toBe("connected");
  expect(result.current.activeUrl).toBe(old.url);
  rerender({ url: "ws://localhost:8003/ws/inference" });
  const prediction = { type: "prediction", sequence: 1, status: "ok", label: "Tôi", confidence: .9,
    top_k: [{ label: "Tôi", confidence: .9 }], model_version: "old", latency_ms: 1 };
  act(() => { old.onmessage?.(new MessageEvent("message", { data: JSON.stringify(prediction) })); old.onopen?.(); old.onerror?.(); });
  expect(received).toEqual([]);
  expect(result.current.status).toBe("connecting");
  expect(result.current.activeUrl).toBeNull();
  act(() => { Socket.all[1].onopen?.(); Socket.all[1].onmessage?.(new MessageEvent("message", { data: JSON.stringify(prediction) })); });
  expect(received).toEqual([1]);
});

it("hands the same model over to a new runtime without dropping the connection", () => {
  vi.stubGlobal("WebSocket", Socket);
  const received: number[] = [];
  const sent: string[] = [];
  const { result, rerender } = renderHook(({ url }) => useInferenceSocket(url, p => received.push(p.sequence), "current"),
    { initialProps: { url: "wss://api.example/ws/inference" } });
  const mac = Socket.all[0];
  mac.send = (data: string) => { sent.push(`mac:${data}`); };
  act(() => mac.onopen?.());
  rerender({ url: "wss://gpu.example/ws/inference?token=t" });
  expect(result.current.status).toBe("connected");
  const gpu = Socket.all[1];
  gpu.readyState = 0;
  expect(result.current.activeUrl).toBe(mac.url);
  gpu.send = (data: string) => { sent.push(`gpu:${data}`); };
  act(() => result.current.sendFrames({ sequence: 1 } as never));
  const prediction = { type: "prediction", sequence: 1, status: "ok", label: "Tôi", confidence: .9,
    top_k: [{ label: "Tôi", confidence: .9 }], model_version: "v", latency_ms: 1 };
  act(() => mac.onmessage?.(new MessageEvent("message", { data: JSON.stringify(prediction) })));
  expect(received).toEqual([1]);
  expect(mac.readyState).toBe(1);
  act(() => { gpu.readyState = 1; gpu.onopen?.(); });
  expect(mac.readyState).toBe(3);
  expect(result.current.status).toBe("connected");
  expect(result.current.activeUrl).toBe(gpu.url);
  act(() => result.current.sendFrames({ sequence: 2 } as never));
  expect(sent.map(item => item.split(":")[0])).toEqual(["mac", "gpu"]);
});

it("reports a lost connection when the new runtime fails during a handover", () => {
  vi.stubGlobal("WebSocket", Socket);
  const { result, rerender } = renderHook(({ url }) => useInferenceSocket(url, () => undefined, "current"),
    { initialProps: { url: "wss://gpu.example/ws/inference?token=t" } });
  const gpu = Socket.all[0];
  act(() => gpu.onopen?.());
  rerender({ url: "wss://api.example/ws/inference" });
  act(() => { Socket.all[1].onerror?.(); });
  expect(result.current.status).toBe("connected");
  act(() => { Socket.all[1].onclose?.(); });
  expect(gpu.readyState).toBe(3);
  expect(result.current.status).toBe("disconnected");
  expect(result.current.activeUrl).toBeNull();
});

it("retains a busy parked socket when the replacement fails and retries without losing its reply", () => {
  vi.useFakeTimers();
  vi.stubGlobal("WebSocket", Socket);
  let busy = false;
  const received: number[] = [];
  const { result, rerender, unmount } = renderHook(({ url }) =>
    useInferenceSocket(url, p => { received.push(p.sequence); busy = false; }, "current", () => busy),
  { initialProps: { url: "wss://aws.example/ws/inference" } });
  const aws = Socket.all[0];
  act(() => aws.onopen?.());
  rerender({ url: "wss://modal.example/ws/inference" });
  busy = true;
  act(() => result.current.sendFrames({ sequence: 1 } as never));
  const failed = Socket.all[1];
  act(() => { failed.onopen?.(); failed.readyState = 3; failed.onclose?.(); });
  expect(result.current.activeUrl).toBe(aws.url);
  expect(aws.readyState).toBe(1);
  act(() => vi.advanceTimersByTime(2_000));
  const retry = Socket.all[2];
  act(() => retry.onopen?.());
  expect(result.current.activeUrl).toBe(aws.url);
  const prediction = { type: "prediction", sequence: 1, status: "error", label: null, confidence: 0,
    top_k: [], model_version: "v", latency_ms: 1 };
  act(() => aws.onmessage?.(new MessageEvent("message", { data: JSON.stringify(prediction) })));
  act(() => vi.advanceTimersByTime(100));
  expect(received).toEqual([1]);
  expect(result.current.activeUrl).toBe(retry.url);
  expect(aws.readyState).toBe(3);
  unmount();
  expect(vi.getTimerCount()).toBe(0);
});

it("cancels a delayed handover when a different candidate replaces it", () => {
  vi.useFakeTimers();
  vi.stubGlobal("WebSocket", Socket);
  let busy = false;
  const { result, rerender, unmount } = renderHook(({ url }) =>
    useInferenceSocket(url, () => undefined, "current", () => busy),
  { initialProps: { url: "wss://aws.example/ws/inference?token=old" } });
  const aws = Socket.all[0];
  act(() => aws.onopen?.());
  rerender({ url: "wss://modal.example/ws/inference" });
  busy = true;
  act(() => Socket.all[1].onopen?.());
  rerender({ url: "wss://aws.example/ws/inference?token=new" });
  expect(Socket.all[1].readyState).toBe(3);
  busy = false;
  act(() => vi.advanceTimersByTime(100));
  expect(result.current.activeUrl).toBe(aws.url);
  expect(aws.readyState).toBe(1);
  act(() => Socket.all[2].onopen?.());
  expect(result.current.activeUrl).toBe("wss://aws.example/ws/inference?token=new");
  expect(aws.readyState).toBe(3);
  unmount();
  expect(vi.getTimerCount()).toBe(0);
});
