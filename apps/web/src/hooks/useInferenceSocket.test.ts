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
  send() {}
}

afterEach(() => { vi.unstubAllGlobals(); Socket.all = []; });

it("ignores predictions and open/error events from the previous model socket", () => {
  vi.stubGlobal("WebSocket", Socket);
  const received: number[] = [];
  const { result, rerender } = renderHook(({ url }) => useInferenceSocket(url, p => received.push(p.sequence)),
    { initialProps: { url: "ws://localhost:8000/ws/inference" } });
  const old = Socket.all[0];
  act(() => old.onopen?.());
  expect(result.current.status).toBe("connected");
  rerender({ url: "ws://localhost:8003/ws/inference" });
  const prediction = { type: "prediction", sequence: 1, status: "ok", label: "Tôi", confidence: .9,
    top_k: [{ label: "Tôi", confidence: .9 }], model_version: "old", latency_ms: 1 };
  act(() => { old.onmessage?.(new MessageEvent("message", { data: JSON.stringify(prediction) })); old.onopen?.(); old.onerror?.(); });
  expect(received).toEqual([]);
  expect(result.current.status).toBe("connecting");
  act(() => { Socket.all[1].onopen?.(); Socket.all[1].onmessage?.(new MessageEvent("message", { data: JSON.stringify(prediction) })); });
  expect(received).toEqual([1]);
});
