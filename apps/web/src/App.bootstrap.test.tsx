import { act, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";
import userEvent from "@testing-library/user-event";

const capabilities = { overview: true, recognize: true, data: true, evaluation: true,
  monitoring: true, models: true, activity: true, integrations: true, team: true, settings: true };

afterEach(() => vi.unstubAllGlobals());

it("keeps the workspace unmounted until login and returns to login after logout", async () => {
  let authenticated = false;
  vi.stubGlobal("fetch", vi.fn(async (input: string | URL | Request) => {
    const url = String(input);
    if (url.endsWith("/auth/login")) {
      authenticated = true;
      return Response.json({ authenticated: true, user: { id: "admin", email: "vsignadmin@vsign.invalid", display_name: "Admin", role: "admin" } });
    }
    if (url.endsWith("/auth/logout")) {
      authenticated = false;
      return Response.json({ authenticated: false });
    }
    if (!authenticated) return Response.json({ detail: "Đăng nhập để tiếp tục" }, { status: 401 });
    if (url.endsWith("/workspace")) return Response.json({ api_version: "1", workspace_id: "local", name: "VSign", environment: "production", auth_required: true });
    if (url.endsWith("/capabilities")) return Response.json({ api_version: "1", workspace_id: "local", capabilities });
    if (url.endsWith("/auth/me")) return Response.json({ authenticated: true, auth_mode: "session", user: { id: "admin", email: "vsignadmin@vsign.invalid", display_name: "Admin", role: "admin" } });
    return Response.json({}, { status: 503 });
  }));
  render(<App />);
  await screen.findByRole("heading", { name: "Đăng nhập VSign" });
  expect(screen.queryByRole("navigation", { name: "Workspace" })).not.toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Tên đăng nhập"), "vsignadmin");
  await userEvent.type(screen.getByLabelText("Mật khẩu"), "temporary-pass");
  await userEvent.click(screen.getByRole("button", { name: "Đăng nhập" }));
  await screen.findByRole("navigation", { name: "Workspace" });
  await userEvent.click(screen.getByRole("button", { name: /Đăng xuất/ }));
  await screen.findByRole("heading", { name: "Đăng nhập VSign" });
  expect(screen.queryByRole("navigation", { name: "Workspace" })).not.toBeInTheDocument();
});

it.each(["system_admin", "admin"])("waits for the real %s identity before mounting workspace navigation", async role => {
  history.replaceState(null, "", "/?view=overview");
  let resolveIdentity!: (response: Response) => void;
  const identity = new Promise<Response>(resolve => { resolveIdentity = resolve; });
  const fetchMock = vi.fn(async (input: string | URL | Request) => {
    const url = String(input);
    if (url.endsWith("/auth/me")) return identity;
    if (url.endsWith("/workspace")) return new Response(JSON.stringify({ api_version: "1", workspace_id: "local",
      name: "VSign workspace", environment: "production", auth_required: false }));
    if (url.endsWith("/capabilities")) return new Response(JSON.stringify({ api_version: "1", workspace_id: "local", capabilities }));
    return new Response("{}", { status: 503 });
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<App />);
  expect(screen.getByLabelText("Đang tải workspace")).toBeInTheDocument();
  expect(screen.queryByRole("navigation", { name: "Workspace" })).not.toBeInTheDocument();
  expect(screen.queryByText("Không gian doanh nghiệp")).not.toBeInTheDocument();
  await vi.waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/auth/me"))).toBe(true));
  expect(screen.queryByRole("navigation", { name: "Workspace" })).not.toBeInTheDocument();
  await act(async () => resolveIdentity(new Response(JSON.stringify({ authenticated: true, auth_mode: "local_admin",
    user: { id: "local", email: "local@example.com", display_name: "Admin", role } }))));
  expect(await screen.findByRole("navigation", { name: "Workspace" })).toBeInTheDocument();
  expect(screen.queryByLabelText("Đang tải workspace")).not.toBeInTheDocument();
  expect(screen.getByText(role === "system_admin" ? "Quản trị hệ thống" : "Quản trị doanh nghiệp")).toBeInTheDocument();
});
