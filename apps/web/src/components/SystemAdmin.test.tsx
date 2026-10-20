import { render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AppSidebar } from "./AppSidebar";
import { WorkspaceModels } from "./WorkspaceModels";
import { WorkspaceRuntime } from "./WorkspaceRuntime";
import { runtimeSnapshot } from "../test/runtimeFixture";
import { teamOverview } from "../test/teamFixture";
import { useWorkspaceTeam } from "../hooks/useWorkspaceTeam";
import { useWorkspaceIntegrations } from "../hooks/useWorkspaceIntegrations";
import { useWorkspaceEvaluations } from "../hooks/useWorkspaceEvaluations";

const user = { id: "system", email: "system@example.com", display_name: "Admin", role: "system_admin" as const };
const options = { platformUrl: "http://localhost:8000", workspaceId: "local", user };
afterEach(() => vi.unstubAllGlobals());

it("identifies system administration and exposes every workflow in navigation", () => {
  render(<AppSidebar activeView="models" onNavigate={vi.fn()} user={user} />);
  expect(screen.getByText("Quản trị hệ thống")).toBeInTheDocument();
  expect(screen.queryByText("Không gian doanh nghiệp")).not.toBeInTheDocument();
  for (const name of ["Mô hình & triển khai", "Tài khoản & quyền", "Cấu hình hệ thống", "Dữ liệu & thu mẫu", "Tích hợp & API"])
    expect(screen.getByRole("button", { name })).toBeEnabled();
});

it("shows only the VSign wordmark on top and the user's name and role at the bottom", () => {
  render(<AppSidebar activeView="overview" onNavigate={vi.fn()} user={user} />);
  expect(screen.getByRole("img", { name: "VSign" })).toBeInTheDocument();
  expect(screen.getByText("Admin")).toBeInTheDocument();
  expect(screen.getByText("Quản trị hệ thống")).toBeInTheDocument();
  expect(screen.queryByText(/Hệ thống · /)).not.toBeInTheDocument();
});

it("mounts the real internal registry for a system account", async () => {
  vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ api_version: "1", workspace_id: "local",
    permissions: { register: true, validate: true, approve: true, deploy: true }, target: null, models: [], deployments: [] })));
  render(<WorkspaceModels {...options} onLogin={async () => undefined} runtime={runtimeSnapshot} />);
  expect(await screen.findByRole("button", { name: "Đăng ký ứng viên" })).toBeInTheDocument();
  expect(screen.getByLabelText("Manifest")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Mô hình & triển khai" })).toBeInTheDocument();
});

it("shows real runtime identity to system operators without fabricating telemetry", () => {
  render(<WorkspaceRuntime runtime={runtimeSnapshot} monitoring systemAdmin />);
  expect(screen.getByText(runtimeSnapshot.endpoint)).toBeInTheDocument();
  expect(screen.getByText("coreml")).toBeInTheDocument();
  expect(screen.getAllByText("Chưa có dữ liệu")).toHaveLength(2);
});

it("loads accounts including protected internal memberships for system administrators", async () => {
  const snapshot = { ...teamOverview(), grantable_roles: ["admin", "operator", "reviewer", "viewer"],
    members: [{ ...teamOverview().members[0], ...user }] };
  vi.stubGlobal("fetch", async () => new Response(JSON.stringify(snapshot)));
  const { result } = renderHook(() => useWorkspaceTeam({ ...options, tab: "members" }));
  await waitFor(() => expect(result.current.canMutate).toBe(true));
  expect(result.current.snapshot?.overview.members[0].role).toBe("system_admin");
});

it("allows system administrators to manage integrations", async () => {
  vi.stubGlobal("fetch", async (url: string) => new Response(JSON.stringify(url.includes("/logs")
    ? { api_version: "1", workspace_id: "local", logs: [], next_cursor: null }
    : { api_version: "1", workspace_id: "local", permissions: { manage: true }, webhook_ready: true, worker_online: true,
      available_scopes: ["models:read"], available_events: ["evaluation.completed"],
      limits: { key_per_minute: 60, workspace_per_minute: 300, webhook_per_minute: 30, webhook_workspace_per_minute: 60 },
      keys: [], webhooks: [], deliveries: [] })));
  const { result } = renderHook(() => useWorkspaceIntegrations(options));
  await waitFor(() => expect(result.current.canMutate).toBe(true));
});

it("allows system administrators to create and cancel evaluations", async () => {
  vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ api_version: "1", workspace_id: "local", active_model_id: null,
    permissions: { create: true, cancel: true }, workers: { onnx: false }, models: [], snapshots: [], runs: [] })));
  const { result } = renderHook(() => useWorkspaceEvaluations(options));
  await waitFor(() => expect(result.current.canMutate).toBe(true));
});
