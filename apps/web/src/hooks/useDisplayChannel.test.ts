import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { displaySocketUrl, useDisplayChannel } from "./useDisplayChannel";

class Socket {
  static OPEN = 1;
  static all: Socket[] = [];
  readyState = 0;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  constructor(public url: string) { Socket.all.push(this); }
  open() { this.readyState = 1; this.onopen?.(); }
  receive(data: unknown) { this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(data) })); }
  drop(code: number) { this.readyState = 3; this.onclose?.({ code }); }
  close() { this.readyState = 3; }
  send(data: string) { this.sent.push(data); }
}

beforeEach(() => { vi.useFakeTimers(); vi.stubGlobal("WebSocket", Socket); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); Socket.all = []; });

it("builds the socket url from the platform url", () => {
  expect(displaySocketUrl("https://api.vsign.io.vn/", "d 1", "staff", true))
    .toBe("wss://api.vsign.io.vn/ws/display/d%201?role=staff&takeover=1");
  expect(displaySocketUrl("http://localhost:8000", "d1", "device")).toBe("ws://localhost:8000/ws/display/d1?role=device");
});

it("delivers parsed messages, ignores junk and reconnects with backoff after a network drop", () => {
  const onMessage = vi.fn();
  const { result } = renderHook(() => useDisplayChannel({ url: "ws://x/ws/display/d1?role=device", onMessage }));
  expect(result.current.status).toBe("connecting");
  act(() => Socket.all[0].open());
  expect(result.current.status).toBe("open");
  act(() => { Socket.all[0].receive({ type: "pong" }); Socket.all[0].receive({ type: "nope" }); });
  expect(onMessage).toHaveBeenCalledTimes(1);
  expect(result.current.send({ type: "ping" })).toBe(true);

  act(() => Socket.all[0].drop(1006));
  expect(result.current.status).toBe("reconnecting");
  expect(result.current.send({ type: "ping" })).toBe(false);
  act(() => vi.advanceTimersByTime(999));
  expect(Socket.all).toHaveLength(1);
  act(() => vi.advanceTimersByTime(1));
  expect(Socket.all).toHaveLength(2);
  act(() => Socket.all[1].open());
  expect(result.current.status).toBe("open");
});

it("closes a socket that stays silent and stops for good on a terminal close code", () => {
  const onEnded = vi.fn();
  const { result } = renderHook(() => useDisplayChannel({ url: "ws://x", onMessage: vi.fn(), onEnded }));
  act(() => Socket.all[0].open());
  act(() => vi.advanceTimersByTime(15000));
  expect(Socket.all[0].sent).toContain(JSON.stringify({ type: "ping" }));
  expect(Socket.all[0].readyState).toBe(3);

  act(() => Socket.all[0].drop(4003));
  expect(result.current.status).toBe("closed");
  expect(onEnded).toHaveBeenCalledWith(4003);
  act(() => vi.advanceTimersByTime(10000));
  expect(Socket.all).toHaveLength(1);
});

it("stays idle without a url and closes the socket when the url goes away", () => {
  const { result, rerender } = renderHook(({ url }) => useDisplayChannel({ url, onMessage: vi.fn() }),
    { initialProps: { url: null as string | null } });
  expect(result.current.status).toBe("idle");
  expect(Socket.all).toHaveLength(0);
  rerender({ url: "ws://x" });
  act(() => Socket.all[0].open());
  rerender({ url: null });
  expect(result.current.status).toBe("idle");
  expect(Socket.all[0].readyState).toBe(3);
});
