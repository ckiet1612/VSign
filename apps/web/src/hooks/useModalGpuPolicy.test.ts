import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useModalGpuPolicy } from "./useModalGpuPolicy";

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

const response = (enabled: boolean) => Response.json({ enabled });

it("publishes a confirmed change to other signed-in tabs on their next poll", async () => {
  vi.useFakeTimers();
  let enabled = true;
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init: RequestInit) => {
    if (init.method === "POST") enabled = JSON.parse(String(init.body)).enabled;
    return response(enabled);
  }));
  const admin = renderHook(() => useModalGpuPolicy("https://api.example", "admin"));
  const viewer = renderHook(() => useModalGpuPolicy("https://api.example", "viewer"));
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  expect(admin.result.current.enabled).toBe(true);
  await act(async () => { await admin.result.current.setEnabled(false); });
  expect(admin.result.current.enabled).toBe(false);
  await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
  expect(viewer.result.current.enabled).toBe(false);
});

it("keeps the previous state and reports a failed write", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init: RequestInit) =>
    init.method === "POST" ? new Response(null, { status: 503 }) : response(false)));
  const { result } = renderHook(() => useModalGpuPolicy("https://api.example", "admin"));
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  await act(async () => { await result.current.setEnabled(true); });
  expect(result.current.enabled).toBe(false);
  expect(result.current.error).toBeTruthy();
});
