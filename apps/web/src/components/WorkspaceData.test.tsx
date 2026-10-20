import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useWorkspaceData } from "../hooks/useWorkspaceData";
import { WorkspaceData } from "./WorkspaceData";

const id = "123e4567-e89b-12d3-a456-426614174001";
const user = { id: "admin", display_name: "Admin", email: "admin@example.com", role: "admin" as const };
const base = { api_version: "1", workspace_id: "local", collection_enabled: true, default_labels: ["Cho", "Không ký hiệu"],
  permissions: { manage: true, collect: true }, labels: [], datasets: [], sessions: [], snapshots: [] };

function Harness({ workspaceId = "local", signedIn = true }: { workspaceId?: string; signedIn?: boolean }) {
  const reader = useWorkspaceData({ platformUrl: "http://platform", workspaceId, user: signedIn ? user : null, enabled: true });
  return <WorkspaceData reader={reader} tab="datasets" onTabChange={() => undefined} datasetId="" onDatasetChange={() => undefined}
    userId={user.id} locked={false} />;
}
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("enterprise workspace data", () => {
  it("reads empty state from platform without importing or creating data automatically", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(base))));
    render(<Harness />);
    expect(await screen.findByText("Chưa có bộ dữ liệu.")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Phiên thu" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Danh mục ký hiệu" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Artifact")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Mật khẩu")).not.toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.every(([, options]) => !options?.method || options.method === "GET")).toBe(true);
  });

  it("never exposes mutations to read-only roles", async () => {
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ ...base, permissions: { manage: false, collect: false } })));
    render(<Harness />);
    await screen.findByText("Chưa có bộ dữ liệu.");
    expect(screen.queryByRole("button", { name: "Tạo bộ dữ liệu" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Chốt|Hạn mức/ })).not.toBeInTheDocument();
  });

  it("sealed versions have no snapshot or quota mutation controls", async () => {
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ ...base,
      labels: [{ id, name: "Sales", parent_id: null, created_at: "2026-10-15T00:00:00Z", entries: [{ id, name: "Cho", kind: "sign" }] }],
      datasets: [{ id, name: "Đã chốt", label_version_id: id, quota_per_label: 100, status: "sealed", sample_count: 1,
        counts: { Cho: { right: 1, left: 0 } }, created_at: "2026-10-15T00:00:00Z" }],
      snapshots: [{ id, dataset_version_id: id, label_version_id: id, sample_count: 1, sha256: "a".repeat(64), created_at: "2026-10-15T00:00:00Z" }],
    })));
    render(<Harness />);
    expect(await screen.findByRole("heading", { name: "Đã chốt" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Chốt phiên bản" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Hạn mức Đã chốt")).not.toBeInTheDocument();
    expect(screen.getByText("Bản dữ liệu bất biến")).toBeInTheDocument();
  });

  it("rejects cross-workspace responses and clears data on logout", async () => {
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify(base)));
    const view = render(<Harness workspaceId="other" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Phản hồi dữ liệu không hợp lệ");
    view.rerender(<Harness signedIn={false} />);
    expect(screen.queryByRole("button", { name: "Tạo bộ dữ liệu" })).not.toBeInTheDocument();
    expect(screen.queryByText("Chưa có bộ dữ liệu.")).not.toBeInTheDocument();
  });

  it("preserves a failed mutation request ID for explicit retry", async () => {
    const labelVersion = { id, name: "Sales", parent_id: null, created_at: "2026-10-15T00:00:00Z", entries: [{ id, name: "Cho", kind: "sign" }] };
    const overview = { ...base, labels: [labelVersion] };
    let failures = 1;
    vi.stubGlobal("fetch", vi.fn(async (_url, options) => {
      if (options?.method === "POST" && failures-- > 0) throw new TypeError("lost ACK");
      return new Response(JSON.stringify(overview));
    }));
    render(<Harness />);
    await screen.findByText("Chưa có bộ dữ liệu.");
    fireEvent.change(screen.getByLabelText("Tên bộ dữ liệu"), { target: { value: "Thu mới" } });
    fireEvent.click(screen.getByRole("button", { name: "Tạo bộ dữ liệu" }));
    await screen.findByRole("button", { name: "Thử lại thao tác" });
    fireEvent.click(screen.getByRole("button", { name: "Thử lại thao tác" }));
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(2));
    const bodies = vi.mocked(fetch).mock.calls.filter(([, options]) => options?.method === "POST").map(([, options]) => options?.body);
    expect(bodies[0]).toBe(bodies[1]);
  });
  it("does not mutate after the last confirmed read has expired", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ...base,
      labels: [{ id, name: "Sales", parent_id: null, created_at: "2026-10-15T00:00:00Z", entries: [{ id, name: "Cho", kind: "sign" }] }],
    }))));
    render(<Harness />);
    await screen.findByText("Chưa có bộ dữ liệu.");
    fireEvent.change(screen.getByLabelText("Tên bộ dữ liệu"), { target: { value: "New" } });
    const now = Date.now(); vi.spyOn(Date, "now").mockReturnValue(now + 20000);
    fireEvent.click(screen.getByRole("button", { name: "Tạo bộ dữ liệu" }));
    await screen.findByRole("alert");
    expect(vi.mocked(fetch).mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(0);
  });
  it("ignores an old read during sample upload and resumes with a fresh read", async () => {
    let resolveRead: (value: Response) => void = () => undefined;
    const fetcher = vi.fn(async () => new Response(JSON.stringify(base)));
    vi.stubGlobal("fetch", fetcher);
    const { result } = renderHook(() => useWorkspaceData({ platformUrl: "http://platform", workspaceId: "local", user, enabled: true }));
    await waitFor(() => expect(result.current.ready).toBe(true));
    fetcher.mockImplementationOnce(() => new Promise<Response>(resolve => { resolveRead = resolve; }));
    let oldRead: Promise<unknown>;
    act(() => { oldRead = result.current.refresh(); });
    act(() => result.current.holdReads(true));
    await act(async () => { resolveRead(new Response(JSON.stringify({ ...base, default_labels: ["Old"] }))); await oldRead; });
    expect(result.current.snapshot?.default_labels).toEqual(base.default_labels);
    await act(async () => { await result.current.refresh(); });
    expect(fetcher).toHaveBeenCalledTimes(2);
    await act(async () => { result.current.holdReads(false); await result.current.refresh(); });
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(result.current.ready).toBe(true);
  });
});
