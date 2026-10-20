import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AuthenticatedUser, WorkspaceAuditEvent, WorkspaceAuditPageResponse } from "@workspace-contracts";
import { useWorkspaceActivity, type WorkspaceActivityOptions } from "./useWorkspaceActivity";

const user: AuthenticatedUser = { id: "owner-1", email: "owner@example.com", display_name: "Owner", role: "owner" };
const event: WorkspaceAuditEvent = {
  event_id: "event-1", workspace_id: "local", event_type: "auth.login_succeeded",
  actor_type: "user", actor_id: user.id, occurred_at: "2026-10-15T02:00:00Z",
  resource_type: "session", resource_id: "session-1", outcome: "success", metadata: {},
};
function page(events = [event], next_cursor: string | null = null): WorkspaceAuditPageResponse {
  return { api_version: "1", workspace_id: "local", events, next_cursor, has_more: next_cursor !== null, source: "store" };
}
const options: WorkspaceActivityOptions = { platformUrl: "http://localhost:8000", user, canRead: true, workspaceId: "local" };
const response = (body: unknown) => new Response(JSON.stringify(body));
function deferred() {
  let resolve!: (value: Response) => void;
  const promise = new Promise<Response>(complete => { resolve = complete; });
  return { promise, resolve };
}
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("useWorkspaceActivity", () => {
  it("never requests private audit before authentication or without permission", () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    const { result, rerender } = renderHook(props => useWorkspaceActivity(props), { initialProps: { ...options, user: null } as WorkspaceActivityOptions });
    expect(result.current.events).toEqual([]);
    expect(result.current.access).toBe("login_required");
    rerender({ ...options, canRead: false });
    expect(result.current.access).toBe("forbidden");
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("sends optional filters, ISO bounds, fixed limit and cookie credentials", async () => {
    const fetcher = vi.fn<typeof fetch>(async () => response(page()));
    vi.stubGlobal("fetch", fetcher);
    const { result } = renderHook(() => useWorkspaceActivity({ ...options, filters: {
      group: "auth", outcome: "failure", from_at: "2026-10-14T17:00:00.000Z", to_at: "2026-10-15T16:59:00.000Z",
    } }));
    await waitFor(() => expect(result.current.events).toEqual([event]));
    const url = new URL(String(fetcher.mock.calls[0][0]));
    expect(Object.fromEntries(url.searchParams)).toEqual({ limit: "50", group: "auth", outcome: "failure", from_at: "2026-10-14T17:00:00.000Z", to_at: "2026-10-15T16:59:00.000Z" });
    expect(fetcher).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ credentials: "include", signal: expect.any(AbortSignal) }));
  });

  it("appends and deduplicates keyset pages, then refresh replaces from the first page", async () => {
    const second = { ...event, event_id: "event-2" };
    const fetcher = vi.fn()
      .mockResolvedValueOnce(response(page([event], "opaque+/=")))
      .mockResolvedValueOnce(response(page([event, second])))
      .mockResolvedValueOnce(response(page([second])));
    vi.stubGlobal("fetch", fetcher);
    const { result } = renderHook(() => useWorkspaceActivity(options));
    await waitFor(() => expect(result.current.hasMore).toBe(true));
    await act(async () => { await result.current.loadMore(); });
    expect(result.current.events.map(row => row.event_id)).toEqual(["event-1", "event-2"]);
    expect(new URL(fetcher.mock.calls[1][0]).searchParams.get("cursor")).toBe("opaque+/=");
    expect(result.current.hasMore).toBe(false);
    await act(async () => { await result.current.refresh(); });
    expect(result.current.events).toEqual([second]);
    expect(new URL(fetcher.mock.calls[2][0]).searchParams.has("cursor")).toBe(false);
  });

  it.each(["filter", "account", "logout", "workspace", "platform", "permission"] as const)("clears old data immediately and ignores late replies after %s changes", async change => {
    const late = deferred();
    const fresh = deferred();
    const fetcher = vi.fn().mockResolvedValueOnce(response(page([event], "older")))
      .mockReturnValueOnce(late.promise).mockReturnValueOnce(fresh.promise);
    vi.stubGlobal("fetch", fetcher);
    const { result, rerender } = renderHook(props => useWorkspaceActivity(props), { initialProps: options });
    await waitFor(() => expect(result.current.events).toHaveLength(1));
    let loading!: Promise<void>;
    act(() => { loading = result.current.loadMore(); });
    const changed: WorkspaceActivityOptions = {
      ...options,
      ...(change === "filter" ? { filters: { group: "model" as const } } : {}),
      ...(change === "account" ? { user: { ...user, id: "other" } } : {}),
      ...(change === "logout" ? { user: null } : {}),
      ...(change === "workspace" ? { workspaceId: "other-workspace" } : {}),
      ...(change === "platform" ? { platformUrl: "http://localhost:8001" } : {}),
      ...(change === "permission" ? { canRead: false } : {}),
    };
    rerender(changed);
    // A new filter keeps the previous rows on screen (marked previewing) until its own page lands;
    // any change of identity or permission clears them at once.
    const kept = change === "filter" ? [event] : [];
    expect(result.current.events).toEqual(kept);
    expect(result.current.previewing).toBe(change === "filter");
    expect(result.current.stale).toBe(false);
    expect(fetcher.mock.calls[1][1].signal.aborted).toBe(true);
    await act(async () => { late.resolve(response(page([{ ...event, event_id: "late" }]))); await loading; });
    expect(result.current.events).toEqual(kept);
    if (change !== "logout" && change !== "permission") {
      await act(async () => { fresh.resolve(response({ ...page([{ ...event, workspace_id: changed.workspaceId!, event_id: "fresh" }]), workspace_id: changed.workspaceId })); });
      await waitFor(() => expect(result.current.events[0]?.event_id).toBe("fresh"));
    }
  });

  it.each(["loadMore", "refresh"] as const)("retains same-filter rows visibly stale on %s failure and supports retry", async operation => {
    const fetcher = vi.fn().mockResolvedValueOnce(response(page([event], "older")))
      .mockResolvedValueOnce(new Response(null, { status: 500 }))
      .mockResolvedValueOnce(response(page([{ ...event, event_id: "new" }])));
    vi.stubGlobal("fetch", fetcher);
    const { result } = renderHook(() => useWorkspaceActivity(options));
    await waitFor(() => expect(result.current.hasMore).toBe(true));
    await act(async () => { await result.current[operation](); });
    expect(result.current.events).toEqual([event]);
    expect(result.current.stale).toBe(true);
    expect(result.current.error).not.toBe("");
    expect(result.current.nextCursor).toBe("older");
    await act(async () => { await result.current[operation](); });
    expect(result.current.error).toBe("");
    expect(result.current.stale).toBe(false);
    expect(result.current.events.map(row => row.event_id)).toEqual(operation === "refresh" ? ["new"] : ["event-1", "new"]);
  });

  it.each([[401, "login_required"], [403, "forbidden"]] as const)("clears private rows on HTTP %s without changing parent auth", async (status, access) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(response(page([event], "older")))
      .mockResolvedValueOnce(new Response(null, { status })));
    const { result } = renderHook(() => useWorkspaceActivity(options));
    await waitFor(() => expect(result.current.events).toHaveLength(1));
    await act(async () => { await result.current.refresh(); });
    expect(result.current.events).toEqual([]);
    expect(result.current.access).toBe(access);
    expect(result.current.hasMore).toBe(false);
    expect(options.user).toBe(user);
  });

  const malformed = [
    null, {}, { ...page(), api_version: "2" }, { ...page(), workspace_id: "another" },
    { ...page(), source: "not_configured" }, { ...page(), has_more: "false" },
    { ...page(), next_cursor: "unexpected" }, { ...page(), has_more: true },
    { ...page(), events: [{ ...event, event_id: "" }] },
    { ...page(), events: [{ ...event, workspace_id: "another" }] },
    { ...page(), events: [{ ...event, event_type: null }] },
    { ...page(), events: [{ ...event, actor_type: "robot" }] },
    { ...page(), events: [{ ...event, actor_type: ["system"] }] },
    { ...page(), events: [{ ...event, actor_id: undefined }] },
    { ...page(), events: [{ ...event, occurred_at: "not-a-date" }] },
    { ...page(), events: [{ ...event, occurred_at: "2026-10-15" }] },
    { ...page(), events: [{ ...event, resource_type: 42 }] },
    { ...page(), events: [{ ...event, resource_id: undefined }] },
    { ...page(), events: [{ ...event, outcome: "unknown" }] },
    { ...page(), events: [{ ...event, metadata: [] }] },
    { ...page(), events: [{ ...event, metadata: null }] },
    { ...page(), events: [event, { ...event, event_id: "invalid", outcome: null }] },
  ];
  it.each(malformed.map((body, index) => [index, body] as const))("rejects the whole malformed page %s", async (_index, body) => {
    vi.stubGlobal("fetch", async () => response(body));
    const { result } = renderHook(() => useWorkspaceActivity(options));
    await waitFor(() => expect(result.current.error).not.toBe(""));
    expect(result.current.events).toEqual([]);
    expect(result.current.loading).toBe(false);
  });

  it("rejects a repeated cursor without appending any rows", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(response(page([event], "same")))
      .mockResolvedValueOnce(response(page([{ ...event, event_id: "bad-page" }], "same"))));
    const { result } = renderHook(() => useWorkspaceActivity(options));
    await waitFor(() => expect(result.current.hasMore).toBe(true));
    await act(async () => { await result.current.loadMore(); });
    expect(result.current.events).toEqual([event]);
    expect(result.current.stale).toBe(true);
  });

  it("times out at eight seconds even if fetch ignores abort, and rejects the late result", async () => {
    vi.useFakeTimers();
    const late = deferred();
    const fetcher = vi.fn().mockReturnValue(late.promise);
    vi.stubGlobal("fetch", fetcher);
    const { result } = renderHook(() => useWorkspaceActivity(options));
    await act(async () => { await vi.advanceTimersByTimeAsync(8000); });
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toMatch(/8 giây/);
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true);
    await act(async () => { late.resolve(response(page())); });
    expect(result.current.events).toEqual([]);
  });

  it("aborts on unmount and survives StrictMode effect replay", async () => {
    const fetcher = vi.fn<typeof fetch>(async () => response(page()));
    vi.stubGlobal("fetch", fetcher);
    const { result, unmount } = renderHook(() => useWorkspaceActivity(options), {
      wrapper: ({ children }) => createElement(StrictMode, null, children),
    });
    await waitFor(() => expect(result.current.events).toEqual([event]));
    const late = deferred();
    fetcher.mockReturnValueOnce(late.promise);
    let loading!: Promise<void>;
    act(() => { loading = result.current.refresh(); });
    const signal = fetcher.mock.calls.at(-1)![1]!.signal!;
    unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => { late.resolve(response(page())); await loading; });
  });

  it("supersedes a pending same-filter refresh and ignores its late 401", async () => {
    const first = deferred();
    const second = deferred();
    vi.stubGlobal("fetch", vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise));
    const { result } = renderHook(() => useWorkspaceActivity(options));
    let refreshed!: Promise<void>;
    act(() => { refreshed = result.current.refresh(); });
    await act(async () => { second.resolve(response(page())); await refreshed; });
    expect(result.current.events).toEqual([event]);
    await act(async () => { first.resolve(new Response(null, { status: 401 })); });
    expect(result.current.events).toEqual([event]);
    expect(result.current.access).toBe("ready");
  });

  it("ignores duplicate pagination clicks and never fetches without a cursor", async () => {
    const more = deferred();
    const fetcher = vi.fn().mockResolvedValueOnce(response(page([event], "next"))).mockReturnValueOnce(more.promise);
    vi.stubGlobal("fetch", fetcher);
    const { result } = renderHook(() => useWorkspaceActivity(options));
    await act(async () => { await result.current.loadMore(); });
    expect(fetcher).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(result.current.hasMore).toBe(true));
    let loading!: Promise<void>;
    act(() => { loading = result.current.loadMore(); void result.current.loadMore(); });
    expect(fetcher).toHaveBeenCalledTimes(2);
    await act(async () => { more.resolve(response(page([]))); await loading; });
    await act(async () => { await result.current.loadMore(); });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});
