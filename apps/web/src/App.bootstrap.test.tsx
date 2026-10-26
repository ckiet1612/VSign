import { act, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";

const capabilities = { overview: true, recognize: true, data: true, evaluation: true,
  monitoring: true, models: true, activity: true, reports: true, integrations: true, team: true, settings: true };

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
  document.documentElement.removeAttribute("data-workspace-boot");
});

it.each([
  ["/", "", true, false],
  ["/landing", "", true, false],
  ["/workspace", "", false, false],
  ["/workspace", "?login=staff", true, false],
  ["/workspace/models", "", true, true],
  ["/workspace", "", true, true],
  ["/display", "", true, false],
])("restores the boot frame only for a confirmed workspace: %s %s %s", (pathname, search, ready, expected) => {
  const html = readFileSync("index.html", "utf8");
  const parsed = new DOMParser().parseFromString(html, "text/html");
  const script = parsed.querySelector("script:not([src])")!.textContent!;
  runInNewContext(script, {
    document: parsed, location: { pathname, search }, URLSearchParams,
    sessionStorage: { getItem: () => ready ? "ready" : null },
    localStorage: { getItem: () => JSON.stringify({ collapsed: true }) },
  });
  expect(parsed.documentElement.hasAttribute("data-workspace-boot")).toBe(expected);
  if (expected) expect(parsed.documentElement.style.getPropertyValue("--boot-sidebar")).toBe("68px");
});

it("keeps the cached frame while revalidating a workspace and removes it if login is required", async () => {
  document.documentElement.setAttribute("data-workspace-boot", "");
  sessionStorage.setItem("vsign.workspace-boot", "ready");
  let respond!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(resolve => { respond = resolve; })));
  const { container } = render(<App />);
  expect(container.querySelector(".boot-frame")).not.toBeNull();
  await act(async () => respond(Response.json({ detail: "Login required" }, { status: 401 })));
  await screen.findByRole("heading", { name: "Đăng nhập VSign" });
  expect(container.querySelector(".boot-frame")).toBeNull();
  expect(sessionStorage.getItem("vsign.workspace-boot")).toBeNull();
  expect(document.documentElement.hasAttribute("data-workspace-boot")).toBe(false);
});

it("shows a neutral loading state until the session is known", async () => {
  let respond!: (response: Response) => void;
  const response = new Promise<Response>(resolve => { respond = resolve; });
  vi.stubGlobal("fetch", vi.fn(() => response));
  const { container } = render(<App />);
  expect(screen.getByRole("main", { name: "Đang tải workspace" })).toBeInTheDocument();
  expect(container.querySelector(".boot-frame, .app-shell")).toBeNull();
  await act(async () => respond(Response.json({ detail: "Login required" }, { status: 401 })));
  await screen.findByRole("heading", { name: "Đăng nhập VSign" });
  expect(container.querySelector(".boot-frame, .app-shell")).toBeNull();
});

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
  await userEvent.type(screen.getByLabelText("Email hoặc tên đăng nhập"), "vsignadmin");
  await userEvent.type(screen.getByLabelText("Mật khẩu"), "temporary-pass");
  await userEvent.click(screen.getByRole("button", { name: "Đăng nhập" }));
  await screen.findByRole("navigation", { name: "Workspace" });
  expect(sessionStorage.getItem("vsign.workspace-boot")).toBe("ready");
  history.replaceState(null, "", "/workspace/recognize");
  await userEvent.click(screen.getByRole("button", { name: /Đăng xuất/ }));
  await screen.findByRole("heading", { name: "Đăng nhập VSign" });
  expect(window.location.pathname).toBe("/workspace");
  expect(screen.queryByRole("navigation", { name: "Workspace" })).not.toBeInTheDocument();
  expect(sessionStorage.getItem("vsign.workspace-boot")).toBeNull();
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
