import { act, render, screen } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { RuntimeBoundary, useRuntimeConfig, windowsConfig } from "./runtimeConfig";

vi.mock("./config", () => ({ config: {
  platformHost: "mac", publicDemo: false,
  platformHttpUrl: "https://mac.example", inferenceHttpUrl: "https://mac.example",
  inferenceWsUrl: "wss://mac.example/ws/inference",
  windowsRuntime: { httpUrl: "https://windows.example", wsUrl: "wss://windows.example/ws/inference" },
  gpuRuntime: null, awsRuntime: null,
  serverModels: [{ id: "current", label: "Current", httpUrl: "https://mac.example", wsUrl: "wss://mac.example/ws/inference" }],
} }));

let mounts = 0;
function Consumer() {
  const runtime = useRuntimeConfig();
  useEffect(() => { mounts += 1; }, []);
  return <span>{runtime.platformHost}:{runtime.platformHttpUrl}</span>;
}
const unauthorized = () => new Response(JSON.stringify({ detail: "Authentication required" }), {
  status: 401, headers: { "Content-Type": "application/json" },
});
beforeEach(() => { vi.useFakeTimers(); mounts = 0; });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
async function advance(ms = 0) { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); }

it("keeps the Mac when logged out and does not contact Windows", async () => {
  const fetcher = vi.fn<(url: string) => Promise<Response>>(async () => unauthorized());
  vi.stubGlobal("fetch", fetcher);
  render(<RuntimeBoundary><Consumer /></RuntimeBoundary>);
  await advance(15000);
  expect(screen.getByText("mac:https://mac.example")).toBeInTheDocument();
  expect(fetcher.mock.calls.every(call => String(call[0]).startsWith("https://mac.example"))).toBe(true);
});

it("requires two Mac failures, remounts all consumers, and stays on Windows after Mac recovers", async () => {
  let macRecovered = false;
  const fetcher = vi.fn(async (url: string) => url.startsWith("https://windows") || macRecovered
    ? unauthorized() : new Response(null, { status: 503 }));
  vi.stubGlobal("fetch", fetcher);
  render(<RuntimeBoundary><Consumer /></RuntimeBoundary>);
  await advance();
  expect(mounts).toBe(1);
  expect(screen.queryByText("windows:https://windows.example")).not.toBeInTheDocument();
  await advance(5000);
  expect(screen.getByText("windows:https://windows.example")).toBeInTheDocument();
  expect(mounts).toBe(2);
  macRecovered = true;
  await advance(30000);
  expect(mounts).toBe(2);
  expect(fetcher).toHaveBeenCalledTimes(3);
});

it("does not change databases when neither server is reachable", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("offline"); }));
  render(<RuntimeBoundary><Consumer /></RuntimeBoundary>);
  await advance(20000);
  expect(screen.getByText("mac:https://mac.example")).toBeInTheDocument();
  expect(mounts).toBe(1);
});

it("does not switch on a single transient Mac failure", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(new Response(null, { status: 502 }))
    .mockImplementation(async () => unauthorized());
  vi.stubGlobal("fetch", fetcher);
  render(<RuntimeBoundary><Consumer /></RuntimeBoundary>);
  await advance(20000);
  expect(mounts).toBe(1);
});

it("changes platform, metadata and websocket URLs together", () => {
  const runtime = windowsConfig();
  expect(runtime.platformHttpUrl).toBe("https://windows.example");
  expect(runtime.inferenceHttpUrl).toBe(runtime.platformHttpUrl);
  expect(runtime.serverModels[0].httpUrl).toBe(runtime.platformHttpUrl);
  expect(runtime.serverModels[0].wsUrl).toBe(runtime.inferenceWsUrl);
});
