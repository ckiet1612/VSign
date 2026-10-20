import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { WorkspaceClientEventRequest } from "@workspace-contracts";
import { useActivityRecorder } from "./useActivityRecorder";

const event = (id: string): WorkspaceClientEventRequest => ({ event_id: id, event_type: "model.switched",
  resource_id: "session", model_version: "new", previous_model_version: "old", model_option: "seated", previous_model_option: "current" });
afterEach(() => vi.unstubAllGlobals());

it("does not submit anonymous reports", () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  const { result } = renderHook(() => useActivityRecorder("http://platform", null));
  act(() => result.current.record(event("a")));
  expect(fetcher).not.toHaveBeenCalled();
  expect(result.current.pending).toBe(0);
});

it("never accepts a retained callback from a previous login to the same account", () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  const { result, rerender } = renderHook(({ account }) => useActivityRecorder("http://platform", account), { initialProps: { account: "owner" as string | null } });
  const oldRecord = result.current.record;
  rerender({ account: null }); rerender({ account: "owner" });
  act(() => oldRecord(event("old")));
  expect(fetcher).not.toHaveBeenCalled();
});

it("serializes authenticated reports through the platform with credentials", async () => {
  const submitted: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (_url, init) => {
    const body = JSON.parse(init.body); submitted.push(body.event_id);
    expect(init.credentials).toBe("include");
    return new Response(JSON.stringify({ status: "recorded", event_id: body.event_id }), { status: 201 });
  }));
  const { result } = renderHook(() => useActivityRecorder("http://platform/", "owner"));
  act(() => { result.current.record(event("a")); result.current.record(event("b")); });
  await waitFor(() => expect(result.current.pending).toBe(0));
  expect(submitted).toEqual(["a", "b"]);
  expect(fetch).toHaveBeenCalledWith("http://platform/api/v1/workspace/audit/client-events", expect.anything());
});

it("retains a failed report and retries the same ID before later reports", async () => {
  let fail = true; const ids: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (_url, init) => {
    const body = JSON.parse(init.body); ids.push(body.event_id);
    if (fail) throw new Error("offline");
    return new Response(JSON.stringify({ status: "recorded", event_id: body.event_id }));
  }));
  const { result } = renderHook(() => useActivityRecorder("http://platform", "owner"));
  act(() => result.current.record(event("a")));
  await waitFor(() => expect(result.current.error).not.toBe(""));
  act(() => result.current.record(event("b")));
  expect(ids).toEqual(["a"]);
  fail = false;
  act(() => result.current.retry());
  await waitFor(() => expect(result.current.pending).toBe(0));
  expect(ids).toEqual(["a", "a", "b"]);
});

it("does not acknowledge a mismatched response", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ status: "recorded", event_id: "wrong" }))));
  const { result } = renderHook(() => useActivityRecorder("http://platform", "owner"));
  act(() => result.current.record(event("a")));
  await waitFor(() => expect(result.current.error).not.toBe(""));
  expect(result.current.pending).toBe(1);
});

it("keeps an explicit lost-event count after a full queue successfully drains", async () => {
  let finish!: () => void;
  let first = true;
  vi.stubGlobal("fetch", vi.fn(async (_url, init) => {
    if (first) { first = false; await new Promise<void>(resolve => { finish = resolve; }); }
    const body = JSON.parse(init.body);
    return new Response(JSON.stringify({ status: "recorded", event_id: body.event_id }));
  }));
  const { result } = renderHook(() => useActivityRecorder("http://platform", "owner"));
  act(() => { for (let i = 0; i < 201; i++) result.current.record(event(String(i))); });
  expect(result.current.pending).toBe(200);
  await act(async () => finish());
  await waitFor(() => expect(result.current.pending).toBe(0));
  expect(result.current.dropped).toBe(1);
});

it("clears pending reports and ignores late responses when the account changes", async () => {
  let finish!: (value: Response) => void;
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(resolve => { finish = resolve; })));
  const { result, rerender } = renderHook(({ account }) => useActivityRecorder("http://platform", account), { initialProps: { account: "owner" as string | null } });
  act(() => result.current.record(event("a")));
  rerender({ account: "other" });
  await act(async () => finish(new Response(JSON.stringify({ status: "recorded", event_id: "a" }))));
  expect(result.current.pending).toBe(0);
  expect(result.current.error).toBe("");
  act(() => result.current.retry());
  expect(fetch).toHaveBeenCalledTimes(1);
});
