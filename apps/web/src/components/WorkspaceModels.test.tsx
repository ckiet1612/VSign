import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { WorkspaceModelsResponse } from "../../../../contracts/v1/models";
import { runtimeSnapshot } from "../test/runtimeFixture";
import { InternalModelRegistry as WorkspaceModels } from "./WorkspaceModels";

const sha = "a".repeat(64);
function snapshot(): WorkspaceModelsResponse {
  return { api_version: "1", workspace_id: "local", permissions: { register: true, validate: true, approve: true, deploy: true },
    target: { target_id: "production", runtime_url: "http://localhost:8002", backend: "coreml", active_model_id: "base", previous_model_id: "candidate",
      observed_model_id: "base", revision: 2, pending_job_id: null, worker_online: true },
    models: ["base", "candidate"].map(id => ({ id, model_version: `${id}-v1`, backend: "coreml", artifact_sha256: sha, labels_sha256: sha,
      labels_count: 30, source_run_id: "source-run", created_at: "2026-10-15T03:00:00Z", origin: id === "base" ? "baseline" : "candidate",
      status: id === "base" ? "active" : "approved", validation: id === "base" ? null : { id: "validation", passed: true,
        baseline_model_id: "base", report_sha256: sha, created_at: "2026-10-15T03:10:00Z",
        checks: [{ name: "macro_f1", passed: true, detail: "candidate=0.93; baseline=0.94" }] },
      approved_validation_id: id === "base" ? null : "validation", approved_by: id === "base" ? null : "owner",
      approved_at: id === "base" ? null : "2026-10-15T03:11:00Z" })), deployments: [] };
}
const props = { platformUrl: "http://localhost:8000", workspaceId: "local", user: { id: "owner", email: "owner@example.com", display_name: "Owner", role: "owner" as const },
  onLogin: vi.fn(async () => undefined), runtime: runtimeSnapshot, workspaceName: "VSign" };
const response = (body: unknown) => new Response(JSON.stringify(body));
afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); vi.useRealTimers(); });

describe("WorkspaceModels", () => {
  it("does not show a login form while the workspace identity is loading", () => {
    render(<WorkspaceModels {...props} user={null} sessionLoading />);
    expect(screen.queryByLabelText("Mật khẩu")).not.toBeInTheDocument();
    expect(screen.getByText(/Đang tải workspace/)).toBeInTheDocument();
  });

  it("shows an access error instead of login when local admin is unavailable", () => {
    render(<WorkspaceModels {...props} user={null} authMode="local_admin" />);
    expect(screen.queryByLabelText("Mật khẩu")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("shows observed runtime and embedded login anonymously, without requesting the registry", async () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    render(<WorkspaceModels {...props} user={null} modelSelector={<select aria-label="Endpoint"><option>8003</option></select>} />);
    expect(screen.getByText(runtimeSnapshot.health.model_version)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Dev\/Test/ })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Email hoặc tên đăng nhập"), "owner@example.com");
    await userEvent.type(screen.getByLabelText("Mật khẩu"), "password");
    await userEvent.click(screen.getByRole("button", { name: "Đăng nhập" }));
    expect(props.onLogin).toHaveBeenCalledWith("owner@example.com", "password");
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("renders registry, active/previous pointers and actual gate details separately from Dev/Test", async () => {
    vi.stubGlobal("fetch", async () => response(snapshot()));
    render(<WorkspaceModels {...props} />);
    const registry = await screen.findByRole("table", { name: "Sổ mô hình" });
    expect(within(registry).getByText("candidate-v1")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Production" })).getByText("Revision 2")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Chi tiết candidate-v1" }));
    expect(screen.getByText("candidate=0.93; baseline=0.94")).toBeInTheDocument();
    expect(screen.getByText("macro_f1")).toBeInTheDocument();
  });

  it.each(["approve", "deploy", "rollback"] as const)("requires explicit in-app confirmation for %s", async action => {
    const fetcher = vi.fn().mockImplementation(async () => response(snapshot()));
    vi.stubGlobal("fetch", fetcher);
    render(<WorkspaceModels {...props} />);
    await screen.findByRole("table", { name: "Sổ mô hình" });
    if (action === "approve") await userEvent.click(screen.getByRole("button", { name: "Chi tiết candidate-v1" }));
    const labels = { approve: "Phê duyệt", deploy: "Triển khai candidate-v1", rollback: "Hoàn tác" };
    await userEvent.click(screen.getByRole("button", { name: labels[action] }));
    const dialog = screen.getByRole("dialog");
    expect(fetcher).toHaveBeenCalledTimes(1);
    await userEvent.click(within(dialog).getByRole("button", { name: "Hủy" }));
    expect(fetcher).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: labels[action] }));
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Xác nhận" }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    expect(fetcher.mock.calls[1][1].method).toBe("POST");
  });

  it("cancels with the dialog cancel event and returns focus to its trigger", async () => {
    const fetcher = vi.fn().mockImplementation(async () => response(snapshot()));
    vi.stubGlobal("fetch", fetcher);
    render(<WorkspaceModels {...props} />);
    const trigger = await screen.findByRole("button", { name: "Triển khai candidate-v1" });
    await userEvent.click(trigger);
    expect(within(screen.getByRole("dialog")).getByRole("button", { name: "Hủy" })).toHaveFocus();
    fireEvent(screen.getByRole("dialog"), new Event("cancel", { bubbles: false, cancelable: true }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("invalidates an open confirmation when polling observes a changed active revision", async () => {
    vi.useFakeTimers();
    const changed = snapshot();
    changed.target!.revision = 3;
    changed.target!.active_model_id = "candidate";
    const fetcher = vi.fn().mockResolvedValueOnce(response(snapshot())).mockResolvedValueOnce(response(changed));
    vi.stubGlobal("fetch", fetcher);
    render(<WorkspaceModels {...props} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    fireEvent.click(screen.getByRole("button", { name: "Triển khai candidate-v1" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Triển khai candidate-v1" })).toBeDisabled();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("keeps confirmation focus stable and temporarily disables confirm during polling", async () => {
    let resolve!: (response:Response)=>void;
    const fetcher=vi.fn().mockResolvedValueOnce(response(snapshot())).mockImplementationOnce(()=>new Promise<Response>(done=>{resolve=done;}));
    vi.stubGlobal('fetch',fetcher);
    render(<WorkspaceModels {...props}/>);
    await userEvent.click(await screen.findByRole('button',{name:'Triển khai candidate-v1'}));
    const dialog=screen.getByRole('dialog');
    fireEvent.click(screen.getByRole('button',{name:'Làm mới mô hình'}));
    expect(screen.getByRole('dialog')).toBe(dialog);
    expect(within(dialog).getByRole('button',{name:'Xác nhận'})).toBeDisabled();
    await act(async()=>{resolve(response(snapshot()));});
    expect(screen.getByRole('dialog')).toBe(dialog);
    expect(within(dialog).getByRole('button',{name:'Xác nhận'})).toBeEnabled();
  });

  it("clears an unsent confirmation across logout and a return to the same account", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => response(snapshot())));
    const { rerender } = render(<WorkspaceModels {...props} />);
    await userEvent.click(await screen.findByRole("button", { name: "Triển khai candidate-v1" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    rerender(<WorkspaceModels {...props} user={null} />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    rerender(<WorkspaceModels {...props} />);
    await screen.findByRole("table", { name: "Sổ mô hình" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows no registered models or configured target without claiming the selected runtime is production", async () => {
    const empty = snapshot();
    empty.models = [];
    empty.target = null;
    vi.stubGlobal("fetch", async () => response(empty));
    render(<WorkspaceModels {...props} />);
    expect(await screen.findByText("Chưa có mô hình đăng ký.")).toBeInTheDocument();
    expect(screen.getByText("Chưa cấu hình production target.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hoàn tác" })).not.toBeInTheDocument();
    expect(screen.getByText(runtimeSnapshot.health.model_version)).toBeInTheDocument();
  });

  it("registers server-local paths and imports a validation report", async () => {
    const fetcher = vi.fn().mockImplementation(async () => response(snapshot()));
    vi.stubGlobal("fetch", fetcher);
    render(<WorkspaceModels {...props} />);
    await screen.findByRole("table", { name: "Sổ mô hình" });
    for (const [name, value] of [["Manifest", "/allowed/manifest.json"], ["Artifact", "/allowed/model.mlpackage"], ["Bộ nhãn", "/allowed/labels.json"]]) {
      await userEvent.type(screen.getByRole("textbox", { name }), value);
    }
    await userEvent.click(screen.getByRole("button", { name: "Đăng ký ứng viên" }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({ manifest_path: "/allowed/manifest.json", artifact_path: "/allowed/model.mlpackage", labels_path: "/allowed/labels.json" });
    await userEvent.click(screen.getByRole("button", { name: "Chi tiết candidate-v1" }));
    await userEvent.type(screen.getByLabelText("Báo cáo đánh giá"), "/reports/heldout.json");
    await userEvent.click(screen.getByRole("button", { name: "Nhập báo cáo" }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(3));
    expect(JSON.parse(fetcher.mock.calls[2][1].body)).toEqual({ report_path: "/reports/heldout.json" });
  });

  it.each(["permission", "offline", "pending", "baseline", "backend"])("disables deployment for %s", async reason => {
    const body = snapshot();
    if (reason === "permission") body.permissions = { register: false, validate: false, approve: false, deploy: false };
    if (reason === "offline") body.target!.worker_online = false;
    if (reason === "pending") body.target!.pending_job_id = "pending";
    if (reason === "baseline") body.models[1].validation!.baseline_model_id = "outdated";
    if (reason === "backend") body.models[1].backend = "onnx";
    vi.stubGlobal("fetch", async () => response(body));
    render(<WorkspaceModels {...props} />);
    expect(await screen.findByRole("button", { name: "Triển khai candidate-v1" })).toBeDisabled();
  });

  it.each(["queued", "loading", "succeeded", "failed"] as const)("renders %s job state and hides arbitrary raw errors and paths", async status => {
    const body = snapshot();
    body.deployments = [{ id: "job-1", operation: "deploy", from_model_id: "base", to_model_id: "candidate", expected_revision: 2,
      status, requested_by: "owner", created_at: "2026-10-15T03:00:00Z", finished_at: status === "failed" || status === "succeeded" ? "2026-10-15T03:01:00Z" : null,
      error: status === "failed" ? "Traceback /Users/private/secrets/model.mlpackage token=SECRET" : null }];
    body.models[1].validation!.checks.push({ name: "artifact", passed: false, detail: "/Users/private/secrets/model.mlpackage" });
    vi.stubGlobal("fetch", async () => response({ ...body, artifact_path: "/private/extra", debug: { token: "SECRET" } }));
    render(<WorkspaceModels {...props} />);
    const jobs = await screen.findByRole("region", { name: "Lịch sử triển khai" });
    expect(within(jobs).getByText({ queued: "Đang chờ", loading: "Đang nạp", succeeded: "Thành công", failed: "Thất bại" }[status])).toBeInTheDocument();
    if (status === "failed") expect(within(jobs).getByText(/Không thể hoàn tất/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Chi tiết candidate-v1" }));
    expect(document.body.textContent).not.toContain("/Users/private");
    expect(document.body.textContent).not.toContain("SECRET");
    expect(document.body.textContent).not.toContain("/private/extra");
  });

  it.each([401, 403])("shows login or denied after HTTP %s and removes the registry", async status => {
    const fetcher = vi.fn().mockResolvedValueOnce(response(snapshot())).mockResolvedValueOnce(new Response(null, { status }));
    vi.stubGlobal("fetch", fetcher);
    render(<WorkspaceModels {...props} />);
    await screen.findByRole("table", { name: "Sổ mô hình" });
    await userEvent.click(screen.getByRole("button", { name: "Làm mới mô hình" }));
    if (status === 401) await screen.findByRole("heading", { name: "Đăng nhập VSign" });
    else await screen.findByText(/không có quyền/i);
    expect(screen.queryByRole("table", { name: "Sổ mô hình" })).not.toBeInTheDocument();
  });

  it("recovers after a 401 when the same account signs in again", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(new Response(null, { status: 401 })).mockResolvedValueOnce(response(snapshot()));
    vi.stubGlobal("fetch", fetcher);
    render(<WorkspaceModels {...props} />);
    await screen.findByRole("heading", { name: "Đăng nhập VSign" });
    await userEvent.type(screen.getByLabelText("Email hoặc tên đăng nhập"), "owner@example.com");
    await userEvent.type(screen.getByLabelText("Mật khẩu"), "password");
    await userEvent.click(screen.getByRole("button", { name: "Đăng nhập" }));
    expect(await screen.findByRole("table", { name: "Sổ mô hình" })).toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("invalidates an open confirmation on account change and ignores a late mutation", async () => {
    let resolve!: (value: Response) => void;
    const late = new Promise<Response>(done => { resolve = done; });
    const fetcher = vi.fn().mockResolvedValueOnce(response(snapshot())).mockReturnValueOnce(late).mockResolvedValueOnce(response(snapshot()));
    vi.stubGlobal("fetch", fetcher);
    const { rerender } = render(<WorkspaceModels {...props} />);
    await screen.findByRole("table", { name: "Sổ mô hình" });
    await userEvent.click(screen.getByRole("button", { name: "Hoàn tác" }));
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Xác nhận" }));
    rerender(<WorkspaceModels {...props} user={null} />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await act(async () => { resolve(response(snapshot())); });
    expect(screen.queryByRole("table", { name: "Sổ mô hình" })).not.toBeInTheDocument();
    rerender(<WorkspaceModels {...props} />);
    await screen.findByRole("table", { name: "Sổ mô hình" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("marks stale reads, disables mutations and retries without claiming empty success", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(response(snapshot())).mockResolvedValueOnce(response({ broken: true })).mockResolvedValueOnce(response(snapshot())));
    render(<WorkspaceModels {...props} />);
    await screen.findByRole("table", { name: "Sổ mô hình" });
    await userEvent.click(screen.getByRole("button", { name: "Làm mới mô hình" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/cũ/);
    expect(screen.getByRole("button", { name: "Hoàn tác" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Thử lại" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Hoàn tác" })).toBeEnabled());
  });
});
