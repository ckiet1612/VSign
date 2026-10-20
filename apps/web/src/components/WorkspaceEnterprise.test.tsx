import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WorkspaceModels } from "./WorkspaceModels";
import { WorkspaceRuntime } from "./WorkspaceRuntime";
import { AppSidebar } from "./AppSidebar";
import { runtimeSnapshot } from "../test/runtimeFixture";

const user = { id: "admin", email: "admin@example.com", display_name: "Admin", role: "admin" as const };
const model = (id: string) => ({ id, model_version: `${id}-v1`, backend: "coreml", artifact_sha256: "a".repeat(64),
  labels_sha256: "b".repeat(64), labels_count: 30, source_run_id: "private-run", created_at: "2026-10-15T03:00:00Z",
  origin: "candidate", status: id === "active" ? "active" : "candidate", validation: null,
  approved_validation_id: null, approved_by: null, approved_at: null });
const snapshot = { api_version: "1", workspace_id: "local", permissions: { register: true, validate: true, approve: true, deploy: true },
  target: { target_id: "production", runtime_url: "http://private-runtime:8002", backend: "coreml", active_model_id: "active",
    previous_model_id: null, observed_model_id: "active", revision: 2, pending_job_id: null, worker_online: true },
  models: [model("active"), model("private-candidate")], deployments: [] };
afterEach(() => vi.unstubAllGlobals());

describe("Enterprise workspace", () => {
  it("is read-only even when an old server advertises technical permissions", async () => {
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify(snapshot)));
    render(<WorkspaceModels platformUrl="http://localhost:8000" workspaceId="local" user={user}
      onLogin={async () => undefined} runtime={runtimeSnapshot} />);
    expect((await screen.findAllByText("active-v1")).length).toBeGreaterThan(0);
    expect(screen.queryByText("private-candidate-v1")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Manifest")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Artifact")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Triển khai|Hoàn tác|Phê duyệt|Đăng ký/ })).not.toBeInTheDocument();
    expect(screen.queryByText("http://private-runtime:8002")).not.toBeInTheDocument();
    expect(screen.queryByText("private-run")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Lịch sử cập nhật" })).toBeInTheDocument();
  });

  it("shows business service status without infrastructure details", () => {
    render(<WorkspaceRuntime runtime={runtimeSnapshot} monitoring />);
    expect(screen.getByText("Dịch vụ đang hoạt động")).toBeInTheDocument();
    expect(screen.getAllByText("Chưa có dữ liệu")).toHaveLength(2);
    expect(screen.queryByText("Protocol 1.0")).not.toBeInTheDocument();
    expect(screen.queryByText("coreml")).not.toBeInTheDocument();
    expect(screen.queryByText(/\/health|\/metadata/)).not.toBeInTheDocument();
  });

  it("identifies the admin as a business administrator", () => {
    render(<AppSidebar activeView="models" onNavigate={vi.fn()} user={user} />);
    expect(screen.getByText("Quản trị doanh nghiệp")).toBeInTheDocument();
    expect(within(screen.getByRole("complementary")).queryByText("Development")).not.toBeInTheDocument();
  });

  it("does not substitute a selected test runtime for an unconfigured workspace model", async () => {
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ ...snapshot, target: null })));
    render(<WorkspaceModels platformUrl="http://localhost:8000" workspaceId="local" user={user}
      onLogin={async () => undefined} runtime={runtimeSnapshot} />);
    expect(await screen.findByText("Chưa có phiên bản được xác nhận cho workspace này.")).toBeInTheDocument();
    expect(screen.queryByText(runtimeSnapshot.health.model_version)).not.toBeInTheDocument();
    expect(screen.queryByText("active-v1")).not.toBeInTheDocument();
  });

  it.each([false, true])("never confirms an offline or mismatched service as online (worker=%s)", async worker_online => {
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ ...snapshot,
      target: { ...snapshot.target, worker_online, observed_model_id: worker_online ? "other-model" : "active" },
    })));
    render(<WorkspaceModels platformUrl="http://localhost:8000" workspaceId="local" user={user}
      onLogin={async () => undefined} runtime={runtimeSnapshot} />);
    expect(await screen.findByText("Chưa xác nhận hoạt động")).toBeInTheDocument();
    expect(screen.queryByText("Đang hoạt động")).not.toBeInTheDocument();
  });

  it("shows update outcomes without technical errors or rollback commands", async () => {
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ ...snapshot, deployments: [{
      id: "job", operation: "rollback", from_model_id: "private-candidate", to_model_id: "active", expected_revision: 1,
      status: "failed", requested_by: "internal-engineer", created_at: "2026-10-15T03:00:00Z", finished_at: "2026-10-15T03:01:00Z",
      error: "Failed /private/model.onnx token=secret",
    }] })));
    render(<WorkspaceModels platformUrl="http://localhost:8000" workspaceId="local" user={user}
      onLogin={async () => undefined} runtime={runtimeSnapshot} />);
    expect(await screen.findByText("Khôi phục phiên bản")).toBeInTheDocument();
    expect(screen.getByText("Thất bại")).toBeInTheDocument();
    expect(screen.queryByText(/private\/model|internal-engineer|token=secret/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Hoàn tác|Khôi phục/ })).not.toBeInTheDocument();
  });

  it("marks cached model information stale after a refresh failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(snapshot)))
      .mockRejectedValueOnce(new TypeError("private-network")));
    render(<WorkspaceModels platformUrl="http://localhost:8000" workspaceId="local" user={user}
      onLogin={async () => undefined} runtime={runtimeSnapshot} />);
    await screen.findByText("active-v1");
    await userEvent.click(screen.getByRole("button", { name: "Làm mới mô hình" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("dữ liệu lần đọc trước");
    expect(screen.getByText("Dữ liệu lần đọc trước")).toBeInTheDocument();
    expect(screen.queryByText("Đang hoạt động")).not.toBeInTheDocument();
  });

  it("hides login while loading and clears private model details on logout", async () => {
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify(snapshot)));
    const props = { platformUrl: "http://localhost:8000", workspaceId: "local", onLogin: async () => undefined, runtime: runtimeSnapshot };
    const { rerender } = render(<WorkspaceModels {...props} user={null} sessionLoading />);
    expect(screen.queryByLabelText("Mật khẩu")).not.toBeInTheDocument();
    rerender(<WorkspaceModels {...props} user={user} />);
    await screen.findByText("active-v1");
    rerender(<WorkspaceModels {...props} user={null} authMode="local_admin" />);
    expect(screen.queryByText("active-v1")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Mật khẩu")).not.toBeInTheDocument();
  });
});
