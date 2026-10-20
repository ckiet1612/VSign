import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AuthenticatedUser } from "../../../../contracts/v1/workspace";
import type { WorkspaceModelsResponse } from "../../../../contracts/v1/models";
import { useWorkspaceModels, type WorkspaceModelsOptions } from "./useWorkspaceModels";

const user: AuthenticatedUser = { id: "owner", email: "owner@example.com", display_name: "Owner", role: "owner" };
const options: WorkspaceModelsOptions = { platformUrl: "http://localhost:8000", workspaceId: "local", user };
const sha = "a".repeat(64);
function snapshot(): WorkspaceModelsResponse {
  return {
    api_version: "1", workspace_id: "local",
    target: { target_id: "production", runtime_url: "http://localhost:8002", backend: "coreml", active_model_id: "base",
      previous_model_id: "previous", observed_model_id: "base", revision: 3, pending_job_id: null, worker_online: true },
    permissions: { register: true, validate: true, approve: true, deploy: true },
    models: ["base", "candidate", "previous"].map(id => ({ id, model_version: `${id}-v1`, backend: "coreml", artifact_sha256: sha,
      labels_sha256: sha, labels_count: 2, source_run_id: "run-1", created_at: "2026-10-15T02:00:00Z",
      origin: id === "candidate" ? "candidate" : "baseline", status: id === "candidate" ? "approved" : "baseline",
      validation: id === "candidate" ? { id: "validation-1", passed: true, baseline_model_id: "base", report_sha256: sha,
        created_at: "2026-10-15T02:01:00Z", checks: [{ name: "macro_f1", passed: true, detail: "candidate=0.93; baseline=0.94" }] } : null,
      approved_validation_id: id === "candidate" ? "validation-1" : null, approved_by: id === "candidate" ? "owner" : null,
      approved_at: id === "candidate" ? "2026-10-15T02:02:00Z" : null })), deployments: [],
  };
}
const response = (body: unknown) => new Response(JSON.stringify(body));
function deferred() {
  let resolve!: (value: Response) => void;
  const promise = new Promise<Response>(done => { resolve = done; });
  return { resolve, promise };
}
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("useWorkspaceModels", () => {
  it("does not read private data anonymously and requests the platform with cookies", async () => {
    const fetcher = vi.fn().mockImplementation(async () => response(snapshot()));
    vi.stubGlobal("fetch", fetcher);
    const { result, rerender } = renderHook(useWorkspaceModels, { initialProps: { ...options, user: null } as WorkspaceModelsOptions });
    expect(result.current.access).toBe("login_required");
    expect(fetcher).not.toHaveBeenCalled();
    rerender(options);
    await waitFor(() => expect(result.current.snapshot?.workspace_id).toBe("local"));
    expect(fetcher).toHaveBeenCalledWith("http://localhost:8000/api/v1/workspace/models", expect.objectContaining({
      method: "GET", credentials: "include", cache: "no-store", signal: expect.any(AbortSignal),
    }));
  });

  it.each([
    (s: WorkspaceModelsResponse) => ({ ...s, workspace_id: "another" }),
    (s: WorkspaceModelsResponse) => ({ ...s, api_version: "2" }),
    (s: WorkspaceModelsResponse) => ({ ...s, permissions: { ...s.permissions, deploy: "yes" } }),
    (s: WorkspaceModelsResponse) => ({ ...s, target: { ...s.target, worker_online: "yes" } }),
    (s: WorkspaceModelsResponse) => ({ ...s, target: { ...s.target, revision: -1 } }),
    (s: WorkspaceModelsResponse) => ({ ...s, target: { ...s.target, pending_job_id: {} } }),
    (s: WorkspaceModelsResponse) => ({ ...s, models: [{ ...s.models[1], labels_count: 1.5 }] }),
    (s: WorkspaceModelsResponse) => ({ ...s, models: [{ ...s.models[1], artifact_sha256: "not-a-hash" }] }),
    (s: WorkspaceModelsResponse) => ({ ...s, models: [{ ...s.models[1], approved_at: "yesterday" }] }),
    (s: WorkspaceModelsResponse) => ({ ...s, models: [{ ...s.models[1], validation: { ...s.models[1].validation, checks: [{ name: "f1", passed: "yes", detail: "bad" }] } }] }),
    (s: WorkspaceModelsResponse) => ({ ...s, deployments: [{ id: "job", status: "succeeded" }] }),
    (s: WorkspaceModelsResponse) => ({ ...s, models: [s.models[0], s.models[0]] }),
  ])("rejects malformed nested or wrong-workspace snapshots %#", async corrupt => {
    vi.stubGlobal("fetch", async () => response(corrupt(snapshot())));
    const { result } = renderHook(() => useWorkspaceModels(options));
    await waitFor(() => expect(result.current.error).toBeTruthy());
    expect(result.current.snapshot).toBeNull();
    expect(result.current.canMutate).toBe(false);
  });

  it("posts all frozen payloads, accepts refreshed snapshots and generates deployment UUIDs", async () => {
    const fetcher = vi.fn().mockImplementation(async () => response(snapshot()));
    vi.stubGlobal("fetch", fetcher);
    const { result } = renderHook(() => useWorkspaceModels(options));
    await waitFor(() => expect(result.current.canMutate).toBe(true));
    const actions = [
      { type: "register" as const, manifest_path: "/allowed/manifest.json", artifact_path: "/allowed/model", labels_path: "/allowed/labels.json" },
      { type: "validate" as const, model_id: "candidate", report_path: "/reports/report.json" },
      { type: "approve" as const, model_id: "candidate", validation_id: "validation-1" },
      { type: "deploy" as const, model_id: "candidate", expected_revision: 3 },
      { type: "rollback" as const, expected_revision: 3 },
    ];
    for (const action of actions) await act(async () => { expect(await result.current.mutate(action)).toBe(true); });
    const posts = fetcher.mock.calls.slice(1).map(([url, init]) => [url, JSON.parse(init.body)]);
    expect(posts[0]).toEqual([`${options.platformUrl}/api/v1/workspace/models`, {
      manifest_path: "/allowed/manifest.json", artifact_path: "/allowed/model", labels_path: "/allowed/labels.json",
    }]);
    expect(posts[1]).toEqual([`${options.platformUrl}/api/v1/workspace/models/candidate/validate`, { report_path: "/reports/report.json" }]);
    expect(posts[2]).toEqual([`${options.platformUrl}/api/v1/workspace/models/candidate/approve`, { validation_id: "validation-1" }]);
    for (const [index, path] of [[3, "deployments"], [4, "rollback"]] as const) {
      expect(posts[index][0]).toBe(`${options.platformUrl}/api/v1/workspace/models/${path}`);
      expect(posts[index][1].expected_revision).toBe(3);
      expect(posts[index][1].request_id).toMatch(/^[\da-f]{8}-[\da-f]{4}-4[\da-f]{3}-[89ab][\da-f]{3}-[\da-f]{12}$/i);
    }
    expect(posts[3][1].model_id).toBe("candidate");
    expect(posts[4][1]).not.toHaveProperty("model_id");
  });

  it.each(["permissions", "offline", "unconfirmed", "pending", "revision", "backend", "baseline", "no-active", "approval", "checks"])("blocks unsafe deployment: %s", async reason => {
    const body = snapshot();
    if (reason === "permissions") body.permissions.deploy = false;
    if (reason === "offline") body.target!.worker_online = false;
    if (reason === "unconfirmed") body.target!.observed_model_id = null;
    if (reason === "pending") body.target!.pending_job_id = "job-1";
    if (reason === "revision") body.target!.revision = 4;
    if (reason === "backend") body.models[1].backend = "onnx";
    if (reason === "baseline") body.models[1].validation!.baseline_model_id = "old";
    if (reason === "no-active") body.target!.active_model_id = null;
    if (reason === "approval") body.models[1].approved_validation_id = "old-validation";
    if (reason === "checks") body.models[1].validation!.checks[0].passed = false;
    const fetcher = vi.fn().mockImplementation(async () => response(body));
    vi.stubGlobal("fetch", fetcher);
    const { result } = renderHook(() => useWorkspaceModels(options));
    await waitFor(() => expect(result.current.snapshot).not.toBeNull());
    await act(async () => { expect(await result.current.mutate({ type: "deploy", model_id: "candidate", expected_revision: 3 })).toBe(false); });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("keeps last snapshot stale on read failure, blocks writes and recovers on refresh", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(response(snapshot())).mockResolvedValueOnce(new Response(null, { status: 500 }))
      .mockImplementation(async () => response(snapshot()));
    vi.stubGlobal("fetch", fetcher);
    const { result } = renderHook(() => useWorkspaceModels(options));
    await waitFor(() => expect(result.current.canMutate).toBe(true));
    await act(async () => { await result.current.refresh(); });
    expect(result.current.stale).toBe(true);
    expect(result.current.snapshot?.models).toHaveLength(3);
    await act(async () => { expect(await result.current.mutate({ type: "rollback", expected_revision: 3 })).toBe(false); });
    expect(fetcher).toHaveBeenCalledTimes(2);
    await act(async () => { await result.current.refresh(); });
    expect(result.current.canMutate).toBe(true);
  });

  it.each([401, 403])("clears private data after mutation HTTP %s without exposing server detail", async status => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(response(snapshot())).mockResolvedValueOnce(new Response(JSON.stringify({ detail: "/private/secret" }), { status })));
    const { result } = renderHook(() => useWorkspaceModels(options));
    await waitFor(() => expect(result.current.canMutate).toBe(true));
    await act(async () => { await result.current.mutate({ type: "rollback", expected_revision: 3 }); });
    expect(result.current.snapshot).toBeNull();
    expect(result.current.access).toBe(status === 401 ? "login_required" : "forbidden");
    expect(result.current.canMutate).toBe(false);
    expect(result.current.error).not.toContain("/private");
  });

  it.each(["account", "workspace", "platform", "logout"] as const)("ignores late mutation replies and saved callbacks after %s changes", async change => {
    const late = deferred();
    const fresh = deferred();
    const fetcher = vi.fn().mockResolvedValueOnce(response(snapshot())).mockReturnValueOnce(late.promise).mockReturnValueOnce(fresh.promise);
    vi.stubGlobal("fetch", fetcher);
    const { result, rerender } = renderHook(useWorkspaceModels, { initialProps: options });
    await waitFor(() => expect(result.current.canMutate).toBe(true));
    const saved = result.current.mutate;
    let mutation!: Promise<boolean>;
    act(() => { mutation = saved({ type: "rollback", expected_revision: 3 }); });
    const signal = fetcher.mock.calls[1][1].signal;
    rerender({ ...options, ...(change === "account" ? { user: { ...user, id: "other" } } : {}),
      ...(change === "workspace" ? { workspaceId: "other" } : {}), ...(change === "platform" ? { platformUrl: "http://other" } : {}),
      ...(change === "logout" ? { user: null } : {}) });
    expect(result.current.snapshot).toBeNull();
    expect(signal.aborted).toBe(true);
    await act(async () => { late.resolve(response(snapshot())); expect(await mutation).toBe(false); });
    await act(async () => { expect(await saved({ type: "rollback", expected_revision: 3 })).toBe(false); });
    expect(result.current.snapshot).toBeNull();
    expect(fetcher).toHaveBeenCalledTimes(change === "logout" ? 2 : 3);
  });

  it("protects A-logout-A from an old read and an old mutation closure", async () => {
    const late = deferred();
    const fetcher = vi.fn().mockReturnValueOnce(late.promise).mockResolvedValueOnce(response(snapshot()));
    vi.stubGlobal("fetch", fetcher);
    const { result, rerender } = renderHook(useWorkspaceModels, { initialProps: options });
    const saved = result.current.mutate;
    rerender({ ...options, user: null });
    rerender(options);
    await waitFor(() => expect(result.current.canMutate).toBe(true));
    await act(async () => { late.resolve(response({ ...snapshot(), workspace_id: "wrong" })); });
    expect(result.current.error).toBe("");
    await act(async () => { expect(await saved({ type: "rollback", expected_revision: 3 })).toBe(false); });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("ignores an in-flight mutation and its saved callback after A-logout-A", async () => {
    const late = deferred();
    const fresh = snapshot();
    fresh.target!.revision = 8;
    const fetcher = vi.fn().mockResolvedValueOnce(response(snapshot())).mockReturnValueOnce(late.promise).mockResolvedValueOnce(response(fresh));
    vi.stubGlobal("fetch", fetcher);
    const { result, rerender } = renderHook(useWorkspaceModels, { initialProps: options });
    await waitFor(() => expect(result.current.canMutate).toBe(true));
    const saved = result.current.mutate;
    let mutation!: Promise<boolean>;
    act(() => { mutation = saved({ type: "rollback", expected_revision: 3 }); });
    rerender({ ...options, user: null });
    rerender(options);
    await waitFor(() => expect(result.current.snapshot?.target?.revision).toBe(8));
    await act(async () => { late.resolve(response(snapshot())); expect(await mutation).toBe(false); });
    await act(async () => { expect(await saved({ type: "rollback", expected_revision: 8 })).toBe(false); });
    expect(result.current.snapshot?.target?.revision).toBe(8);
    expect(fetcher).toHaveBeenCalledTimes(3);
  });

  it("rejects a malformed POST snapshot, keeps the last snapshot stale and sanitizes mutation errors", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(response(snapshot())).mockResolvedValueOnce(response({ ...snapshot(), target: { revision: 4 } }));
    vi.stubGlobal("fetch", fetcher);
    const { result } = renderHook(() => useWorkspaceModels(options));
    await waitFor(() => expect(result.current.canMutate).toBe(true));
    await act(async () => { expect(await result.current.mutate({ type: "rollback", expected_revision: 3 })).toBe(false); });
    expect(result.current.stale).toBe(true);
    expect(result.current.snapshot?.target?.revision).toBe(3);
    expect(result.current.canMutate).toBe(false);
  });

  it("accepts a failed gate returned as HTTP 200 and blocks approval and deployment", async () => {
    const failed = snapshot();
    failed.models[1].status = "candidate";
    failed.models[1].validation!.passed = false;
    failed.models[1].validation!.checks[0] = { name: "held_out", passed: false, detail: "Thiếu mẫu held-out độc lập." };
    const fetcher = vi.fn().mockResolvedValueOnce(response(snapshot())).mockResolvedValueOnce(response(failed));
    vi.stubGlobal("fetch", fetcher);
    const { result } = renderHook(() => useWorkspaceModels(options));
    await waitFor(() => expect(result.current.canMutate).toBe(true));
    await act(async () => { expect(await result.current.mutate({ type: "validate", model_id: "candidate", report_path: "/reports/heldout.json" })).toBe(true); });
    expect(result.current.error).toBe("");
    expect(result.current.snapshot?.models[1].validation?.passed).toBe(false);
    await act(async () => {
      expect(await result.current.mutate({ type: "approve", model_id: "candidate", validation_id: "validation-1" })).toBe(false);
      expect(await result.current.mutate({ type: "deploy", model_id: "candidate", expected_revision: 3 })).toBe(false);
    });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("keeps a 422 validation error safe and requires a refreshed snapshot before another mutation", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(response(snapshot())).mockResolvedValueOnce(new Response(JSON.stringify({ detail: "/server/private/report.json" }), { status: 422 }));
    vi.stubGlobal("fetch", fetcher);
    const { result } = renderHook(() => useWorkspaceModels(options));
    await waitFor(() => expect(result.current.canMutate).toBe(true));
    await act(async () => { expect(await result.current.mutate({ type: "validate", model_id: "candidate", report_path: "/reports/bad.json" })).toBe(false); });
    expect(result.current.error).not.toContain("/server/private");
    expect(result.current.stale).toBe(true);
    expect(result.current.canMutate).toBe(false);
  });

  it("serializes reads and mutations and polls queued/loading/succeeded snapshots", async () => {
    vi.useFakeTimers();
    const loading = deferred();
    const states = ["queued", "loading", "succeeded"] as const;
    const bodies = states.map(status => {
      const body = snapshot();
      body.target!.pending_job_id = status === "succeeded" ? null : "job";
      body.deployments = [{ id: "job", operation: "deploy", from_model_id: "base", to_model_id: "candidate", expected_revision: 3,
        status, requested_by: "owner", created_at: "2026-10-15T03:00:00Z", finished_at: status === "succeeded" ? "2026-10-15T03:01:00Z" : null, error: null }];
      return body;
    });
    const fetcher = vi.fn().mockResolvedValueOnce(response(snapshot())).mockReturnValueOnce(loading.promise)
      .mockResolvedValueOnce(response(bodies[1])).mockResolvedValueOnce(response(bodies[2]));
    vi.stubGlobal("fetch", fetcher);
    const { result } = renderHook(() => useWorkspaceModels(options));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    let mutation!: Promise<boolean>;
    act(() => { mutation = result.current.mutate({ type: "deploy", model_id: "candidate", expected_revision: 3 }); });
    await act(async () => {
      await result.current.refresh();
      expect(await result.current.mutate({ type: "rollback", expected_revision: 3 })).toBe(false);
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(fetcher).toHaveBeenCalledTimes(2);
    await act(async () => { loading.resolve(response(bodies[0])); expect(await mutation).toBe(true); });
    expect(result.current.snapshot?.deployments[0].status).toBe("queued");
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(result.current.snapshot?.deployments[0].status).toBe("loading");
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(result.current.snapshot?.deployments[0].status).toBe("succeeded");
  });

  it("times out even when fetch ignores abort, then polls through job failure without overlapping writes", async () => {
    vi.useFakeTimers();
    const late = deferred();
    const failed = snapshot();
    failed.deployments = [{ id: "job", operation: "deploy", from_model_id: "base", to_model_id: "candidate", expected_revision: 3,
      status: "failed", requested_by: "owner", created_at: "2026-10-15T03:00:00Z", finished_at: "2026-10-15T03:01:00Z", error: "load_failed" }];
    const fetcher = vi.fn().mockReturnValueOnce(late.promise).mockResolvedValueOnce(response(failed));
    vi.stubGlobal("fetch", fetcher);
    const { result } = renderHook(() => useWorkspaceModels(options));
    await act(async () => { await vi.advanceTimersByTimeAsync(8000); });
    expect(result.current.error).toMatch(/thời gian|8 giây/i);
    expect(result.current.canMutate).toBe(false);
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(result.current.snapshot?.deployments[0].status).toBe("failed");
    await act(async () => { late.resolve(response(snapshot())); });
    expect(result.current.snapshot?.deployments[0].status).toBe("failed");
  });

  it("survives StrictMode cleanup and aborts on unmount", async () => {
    const fetcher = vi.fn().mockImplementation(async () => response(snapshot()));
    vi.stubGlobal("fetch", fetcher);
    const { result, unmount } = renderHook(() => useWorkspaceModels(options), { wrapper: ({ children }) => createElement(StrictMode, null, children) });
    await waitFor(() => expect(result.current.canMutate).toBe(true));
    const late = deferred();
    fetcher.mockImplementation(() => late.promise);
    let refreshing!: Promise<void>;
    act(() => { refreshing = result.current.refresh(); });
    const signal = fetcher.mock.calls.at(-1)![1].signal;
    expect(signal.aborted).toBe(false);
    unmount();
    expect(signal.aborted).toBe(true);
    await refreshing;
  });
});
