import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AuthenticatedUser, WorkspaceAuditEvent, WorkspaceAuditPageResponse } from "@workspace-contracts";
import { WorkspaceActivity } from "./WorkspaceActivity";

const user: AuthenticatedUser = { id: "owner-1", email: "owner@example.com", display_name: "Owner", role: "owner" };
const event: WorkspaceAuditEvent = {
  event_id: "event-1", workspace_id: "local", event_type: "model.selected", actor_type: "user", actor_id: "owner-1",
  occurred_at: "2026-10-15T02:00:00Z", resource_type: "model", resource_id: "model-2", outcome: "success",
  metadata: { source: "browser_report", previous_model_id: "model-1", new_model_id: "model-2", client_id: "client-1", session_id: "session-1" },
};
function page(events = [event], cursor: string | null = null): WorkspaceAuditPageResponse {
  return { api_version: "1", workspace_id: "local", events, next_cursor: cursor, has_more: cursor !== null, source: "store" };
}
const response = (body: unknown) => new Response(JSON.stringify(body));
const props = { platformUrl: "http://localhost:8000", user, canRead: true, onLogin: async () => undefined };
afterEach(() => vi.unstubAllGlobals());

describe("WorkspaceActivity", () => {
  it.each([
    ['requested','Yêu cầu đánh giá'],['started','Bắt đầu đánh giá'],['completed','Hoàn tất đánh giá'],
    ['failed','Đánh giá thất bại'],['cancelled','Hủy lượt đánh giá'],
  ])('names evaluation lifecycle event %s', async (state,title) => {
    vi.stubGlobal('fetch',async () => response(page([{...event,event_type:`evaluation.${state}`,actor_type:'service',actor_id:null,
      resource_type:'evaluation_run',metadata:{source:'server',dataset_version:'dataset-1',snapshot_id:'snapshot-1'}}])));
    render(<WorkspaceActivity {...props} />);
    expect(await screen.findByText(title)).toBeInTheDocument();
  });
  it("does not show a login form while the workspace identity is loading", () => {
    render(<WorkspaceActivity {...props} user={null} sessionLoading />);
    expect(screen.queryByLabelText("Mật khẩu")).not.toBeInTheDocument();
    expect(screen.getByText(/Đang tải workspace/)).toBeInTheDocument();
  });

  it("shows an access error instead of login when local admin is unavailable", () => {
    render(<WorkspaceActivity {...props} user={null} authMode="local_admin" />);
    expect(screen.queryByLabelText("Mật khẩu")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("embeds the real login gate without a nested main and never fetches anonymously", async () => {
    const fetcher = vi.fn();
    const onLogin = vi.fn(async () => undefined);
    vi.stubGlobal("fetch", fetcher);
    const { container } = render(<main><WorkspaceActivity {...props} user={null} onLogin={onLogin} workspaceName="VSign local" /></main>);
    expect(screen.getByRole("heading", { name: "Hoạt động", level: 1 })).toHaveAttribute("id", "workspace-page-title");
    expect(container.querySelector(".workspace-page")).not.toBeNull();
    expect(container.querySelectorAll("main")).toHaveLength(1);
    await userEvent.type(screen.getByLabelText("Email"), "owner@example.com");
    await userEvent.type(screen.getByLabelText("Mật khẩu"), "password");
    await userEvent.click(screen.getByRole("button", { name: "Đăng nhập" }));
    expect(onLogin).toHaveBeenCalledWith("owner@example.com", "password");
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("does not fetch or render private rows for a user without permission", () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    render(<WorkspaceActivity {...props} canRead={false} />);
    expect(screen.getByText(/không có quyền/i)).toBeInTheDocument();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("shows source, actor, resource and model/client/session details with the raw event code", async () => {
    vi.stubGlobal("fetch", async () => response(page()));
    render(<WorkspaceActivity {...props} />);
    expect(await screen.findByText("model.selected")).toBeInTheDocument();
    expect(screen.getByText("Trình duyệt báo cáo")).toBeInTheDocument();
    await userEvent.click(screen.getByText("Chi tiết"));
    for (const value of ["owner-1", "model-1", "model-2", "client-1", "session-1", "event-1"]) {
      expect(screen.getAllByText(value).length).toBeGreaterThan(0);
    }
    expect(within(screen.getByRole("article")).getByText("Thành công")).toBeInTheDocument();
    expect(screen.queryByText(/máy chủ xác nhận/i)).not.toBeInTheDocument();
  });

  it("labels server records separately, preserves unknown event types and system actors", async () => {
    vi.stubGlobal("fetch", async () => response(page([{ ...event, event_type: "custom.future_event", actor_id: null, actor_type: "system", outcome: "failure", metadata: {} }])));
    render(<WorkspaceActivity {...props} />);
    expect(await screen.findByText("custom.future_event")).toBeInTheDocument();
    expect(screen.getByText("Máy chủ ghi nhận")).toBeInTheDocument();
    expect(within(screen.getByRole("article")).getByText("Thất bại")).toBeInTheDocument();
    await userEvent.click(screen.getByText("Chi tiết"));
    expect(screen.getByText("Hệ thống")).toBeInTheDocument();
  });

  it("renders only whitelisted metadata as text and hides sensitive fields at every depth", async () => {
    const metadata = {
      source: "browser_report", reason: "<img src=x onerror=alert(1)>",
      token: "hidden-token", password: "hidden-password", secret: "hidden-secret", cookie: "hidden-cookie",
      authorization: "hidden-auth", account_key: "hidden-account", address_key: "hidden-address",
      client: { client_id: "safe-client", token: "nested-token", session: { session_id: "safe-session", password: "nested-password" } },
      changes: { previous: { model_id: "before-model", Authorization: "nested-auth" }, new: { model_id: "after-model", address_key: "nested-address" } },
      unknown_field: "hidden-unknown",
      constructor: "hidden-constructor", toString: "hidden-tostring",
    };
    vi.stubGlobal("fetch", async () => response(page([{ ...event, metadata }])));
    const { container } = render(<WorkspaceActivity {...props} />);
    await screen.findByText("model.selected");
    await userEvent.click(screen.getByText("Chi tiết"));
    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    for (const text of ["safe-client", "safe-session", "before-model", "after-model"]) expect(screen.getByText(text)).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/hidden-|nested-/);
  });

  it("filters by group/outcome and converts local date bounds to ISO, with no old-filter rows", async () => {
    const fetcher = vi.fn<typeof fetch>(async () => response(page()));
    vi.stubGlobal("fetch", fetcher);
    render(<WorkspaceActivity {...props} />);
    await screen.findByText("model.selected");
    await userEvent.selectOptions(screen.getByLabelText("Loại hoạt động"), "auth");
    await userEvent.selectOptions(screen.getByLabelText("Kết quả"), "failure");
    fireEvent.change(screen.getByLabelText("Từ thời điểm"), { target: { value: "2026-10-14T09:30" } });
    fireEvent.change(screen.getByLabelText("Đến thời điểm"), { target: { value: "2026-10-15T17:30" } });
    await waitFor(() => {
      const query = new URL(String(fetcher.mock.calls.at(-1)![0])).searchParams;
      expect(query.get("group")).toBe("auth");
      expect(query.get("outcome")).toBe("failure");
      expect(query.get("from_at")).toBe(new Date("2026-10-14T09:30").toISOString());
      expect(query.get("to_at")).toBe(new Date("2026-10-15T17:30").toISOString());
    });
  });

  it("rejects an inverted time range without fetching or retaining unrelated rows", async () => {
    const fetcher = vi.fn(async () => response(page()));
    vi.stubGlobal("fetch", fetcher);
    render(<WorkspaceActivity {...props} />);
    await screen.findByText("model.selected");
    fireEvent.change(screen.getByLabelText("Từ thời điểm"), { target: { value: "2026-10-15T17:30" } });
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    fireEvent.change(screen.getByLabelText("Đến thời điểm"), { target: { value: "2026-10-14T09:30" } });
    expect(await screen.findByRole("alert")).toHaveTextContent(/trước|sau/);
    expect(screen.queryByText("model.selected")).not.toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("shows explicit no-source states without fabricating deployment/evaluation/integration rows", async () => {
    vi.stubGlobal("fetch", async () => response(page([])));
    render(<WorkspaceActivity {...props} />);
    const sources = await screen.findByRole("region", { name: "Nguồn nhật ký" });
    for (const name of ["Triển khai", "Đánh giá", "Tích hợp"]) expect(within(sources).getByText(name)).toBeInTheDocument();
    expect(within(sources).getAllByText("Chưa có nguồn nhật ký")).toHaveLength(1);
    expect(within(sources).getByText("Máy chủ ghi nhận yêu cầu, hủy và kết quả đánh giá")).toBeInTheDocument();
    expect(within(sources).getByText("Máy chủ ghi nhận yêu cầu và kết quả deploy/rollback")).toBeInTheDocument();
    expect(await screen.findByText("Không có hoạt động phù hợp.")).toBeInTheDocument();
    expect(screen.queryAllByRole("article")).toHaveLength(0);
  });

  it("loads more explicitly and refreshes with an accessible icon control", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(response(page([event], "next")))
      .mockResolvedValueOnce(response(page([{ ...event, event_id: "event-2", event_type: "auth.logout" }])))
      .mockResolvedValueOnce(response(page([])));
    vi.stubGlobal("fetch", fetcher);
    render(<WorkspaceActivity {...props} />);
    await userEvent.click(await screen.findByRole("button", { name: "Tải thêm" }));
    expect(await screen.findByText("auth.logout")).toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(2);
    const refresh = screen.getByRole("button", { name: "Làm mới hoạt động" });
    expect(refresh).toHaveAttribute("title", "Làm mới hoạt động");
    expect(refresh.querySelector("svg")).not.toBeNull();
    await userEvent.click(refresh);
    expect(await screen.findByText("Không có hoạt động phù hợp.")).toBeInTheDocument();
    expect(screen.queryByText("model.selected")).not.toBeInTheDocument();
  });

  it("keeps rows visibly stale on failure and retries the failed pagination operation", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(response(page([event], "next")))
      .mockResolvedValueOnce(new Response(null, { status: 500 }))
      .mockResolvedValueOnce(response(page([{ ...event, event_id: "event-2", event_type: "auth.logout" }])));
    vi.stubGlobal("fetch", fetcher);
    render(<WorkspaceActivity {...props} />);
    await userEvent.click(await screen.findByRole("button", { name: "Tải thêm" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/dữ liệu cũ/i);
    expect(screen.getByText("model.selected")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Thử lại" }));
    expect(await screen.findByText("auth.logout")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(new URL(fetcher.mock.calls[2][0]).searchParams.get("cursor")).toBe("next");
  });

  it.each([401, 403])("hides private details after HTTP %s", async status => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(response(page()))
      .mockResolvedValueOnce(new Response(null, { status })));
    render(<WorkspaceActivity {...props} />);
    await screen.findByText("model.selected");
    await userEvent.click(screen.getByRole("button", { name: "Làm mới hoạt động" }));
    await waitFor(() => expect(screen.queryByText("model.selected")).not.toBeInTheDocument());
    if (status === 401) expect(screen.getByLabelText("Mật khẩu")).toBeInTheDocument();
    else expect(screen.getByText(/không có quyền/i)).toBeInTheDocument();
  });

  it("removes all private details immediately on logout", async () => {
    vi.stubGlobal("fetch", async () => response(page()));
    const { rerender } = render(<WorkspaceActivity {...props} />);
    await screen.findByText("model.selected");
    await act(async () => { rerender(<WorkspaceActivity {...props} user={null} />); });
    expect(screen.queryByText("model.selected")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Mật khẩu")).toBeInTheDocument();
  });

  it("retries the expired reader after successful login with the same user ID", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(new Response(null, { status: 401 })).mockResolvedValueOnce(response(page()));
    const onLogin = vi.fn(async () => undefined);
    vi.stubGlobal("fetch", fetcher);
    render(<WorkspaceActivity {...props} onLogin={onLogin} />);
    await screen.findByLabelText("Mật khẩu");
    await userEvent.type(screen.getByLabelText("Email"), "owner@example.com");
    await userEvent.type(screen.getByLabelText("Mật khẩu"), "password");
    await userEvent.click(screen.getByRole("button", { name: "Đăng nhập" }));
    expect(await screen.findByText("model.selected")).toBeInTheDocument();
    expect(screen.queryByLabelText("Mật khẩu")).not.toBeInTheDocument();
    expect(onLogin).toHaveBeenCalledWith("owner@example.com", "password");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("displays the agreed recorder fields including previous/current model and saved sample counts", async () => {
    vi.stubGlobal("fetch", async () => response(page([{ ...event, event_type: "model.switched", metadata: {
      source: "browser_report", model_version: "current-v2", previous_model_version: "old-v1",
      model_option: "seated", previous_model_option: "current", capture_session_id: "capture-1",
      saved_samples: 12, sample_id: "sample-7", reason: "manual-stop",
    } }])));
    render(<WorkspaceActivity {...props} />);
    await screen.findByText("model.switched");
    expect(screen.getByRole("heading", { name: "Đổi mô hình" })).toBeInTheDocument();
    await userEvent.click(screen.getByText("Chi tiết"));
    for (const text of ["current-v2", "old-v1", "seated", "current", "capture-1", "12", "sample-7", "manual-stop"]) {
      expect(screen.getByText(text)).toBeInTheDocument();
    }
  });

  it("shows permission, method and path for server permission denials without exposing private metadata", async () => {
    vi.stubGlobal("fetch", async () => response(page([{ ...event, event_type: "permission.denied", outcome: "failure", metadata: {
      permission: "activity:read", method: "GET", path: "/api/v1/workspace/audit/events", token: "hidden-token",
    } }])));
    render(<WorkspaceActivity {...props} />);
    await screen.findByText("permission.denied");
    await userEvent.click(screen.getByText("Chi tiết"));
    for (const text of ["activity:read", "GET", "/api/v1/workspace/audit/events"]) expect(screen.queryByText(text)).not.toBeInTheDocument();
    expect(screen.getByText("Máy chủ ghi nhận")).toBeInTheDocument();
    expect(screen.queryByText("hidden-token")).not.toBeInTheDocument();
  });

  it.each([["auth.login", "Đăng nhập"], ["auth.logout", "Đăng xuất"], ["auth.login_failed", "Đăng nhập thất bại"]])("labels actual server event %s", async (event_type, title) => {
    vi.stubGlobal("fetch", async () => response(page([{ ...event, event_type, metadata: {} }])));
    render(<WorkspaceActivity {...props} />);
    await screen.findByText(event_type);
    expect(screen.getByRole("heading", { name: title, level: 3 })).toBeInTheDocument();
  });

  it("retries an initial server error without showing an empty successful result", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(new Response(null, { status: 500 })).mockResolvedValueOnce(response(page())));
    render(<WorkspaceActivity {...props} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/không thể tải nhật ký/i);
    expect(screen.queryByText("Không có hoạt động phù hợp.")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Thử lại" }));
    expect(await screen.findByText("model.selected")).toBeInTheDocument();
  });
});
