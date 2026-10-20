import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useSystemDashboard } from "./useSystemDashboard";
import { dashboardFixture } from "../test/dashboardFixture";

const system = { id: "system", email: "s@example.com", display_name: "System", role: "system_admin" as const };
afterEach(() => vi.unstubAllGlobals());

it("ignores a late range response after the filter changes", async () => {
  let resolveOld!: (response: Response) => void;
  vi.stubGlobal("fetch", (url: string) => url.endsWith("days=7") ? new Promise<Response>(resolve => { resolveOld = resolve; })
    : Promise.resolve(new Response(JSON.stringify(dashboardFixture(90)))));
  const { result, rerender } = renderHook(({ days }: { days: 7 | 90 }) => useSystemDashboard("http://platform", "local", system, days), { initialProps: { days: 7 } });
  rerender({ days: 90 });
  await waitFor(() => expect(result.current.data?.days).toBe(90));
  await act(async () => resolveOld(new Response(JSON.stringify(dashboardFixture(7)))));
  expect(result.current.data?.days).toBe(90);
});

it("clears visible statistics immediately when identity or workspace changes", async () => {
  vi.stubGlobal("fetch", () => Promise.resolve(new Response(JSON.stringify(dashboardFixture(30)))));
  const { result, rerender } = renderHook(({ role, workspace }: { role: "system_admin" | "admin"; workspace: string }) =>
    useSystemDashboard("http://platform", workspace, { ...system, role }, 30), { initialProps: { role: "system_admin", workspace: "local" } });
  await waitFor(() => expect(result.current.data?.totals.samples).toBe(128));
  rerender({ role: "admin", workspace: "local" });
  expect(result.current.data).toBeNull();
  rerender({ role: "system_admin", workspace: "other" });
  expect(result.current.data).toBeNull();
  await waitFor(() => expect(result.current.error).toContain("Phản hồi thống kê không hợp lệ"));
});

it("preserves last confirmed statistics with a stale error, but clears them on permission denial", async () => {
  const fetcher = vi.fn(async () => new Response(JSON.stringify(dashboardFixture(30))));
  vi.stubGlobal("fetch", fetcher);
  const { result } = renderHook(() => useSystemDashboard("http://platform", "local", system, 30));
  await waitFor(() => expect(result.current.data).not.toBeNull());
  fetcher.mockImplementation(async () => new Response("{}", { status: 503 }));
  act(() => result.current.refresh());
  await waitFor(() => expect(result.current.error).toContain("Không thể tải thống kê"));
  expect(result.current.data?.totals.samples).toBe(128);
  fetcher.mockImplementation(async () => new Response("{}", { status: 403 }));
  act(() => result.current.refresh());
  await waitFor(() => expect(result.current.error).toContain("Không có quyền"));
  expect(result.current.data).toBeNull();
});

it.each(["negative", "missing-day", "wrong-sum"])("rejects malformed aggregates: %s", async mode => {
  const fixture = dashboardFixture(30);
  if (mode === "negative") fixture.totals.samples = -1;
  if (mode === "missing-day") fixture.daily_samples[0].date = fixture.daily_samples[1].date;
  if (mode === "wrong-sum") fixture.period.samples++;
  vi.stubGlobal("fetch", async () => new Response(JSON.stringify(fixture)));
  const { result } = renderHook(() => useSystemDashboard("http://platform", "local", system, 30));
  await waitFor(() => expect(result.current.error).toContain("Phản hồi thống kê không hợp lệ"));
  expect(result.current.data).toBeNull();
});
