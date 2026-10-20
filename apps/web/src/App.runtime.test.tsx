import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import App from "./App";
import { runtimeHealth, runtimeMetadata } from "./test/runtimeFixture";

vi.mock("./hooks/useWorkspacePlatform", async () => {
  const { localWorkspacePlatform } = await import("./test/workspacePlatformFixture");
  return { useWorkspacePlatform: () => ({ ...localWorkspacePlatform(),
    user: { id: "internal", email: "internal@example.com", display_name: "Internal", role: "model_admin" },
  }) };
});

class Socket {
  readyState = 0;
  onopen = null;
  onmessage = null;
  onerror = null;
  onclose = null;
  close() {}
  send() {}
}

beforeEach(() => {
  window.history.replaceState({}, "", "/");
  vi.stubGlobal("WebSocket", Socket);
  vi.stubGlobal("fetch", async (url: string) => new Response(JSON.stringify(
    url.endsWith("/health") ? runtimeHealth : runtimeMetadata,
  )));
});
afterEach(() => { window.history.replaceState({}, "", "/"); vi.unstubAllGlobals(); });

it("opens monitoring without a camera or WebSocket connection and reads real HTTP status", async () => {
  render(<App />);
  await userEvent.click(screen.getByRole("button", { name: "Giám sát" }));
  const main = screen.getByRole("main", { name: "Giám sát" });
  expect(await within(main).findByText("Dịch vụ đang hoạt động")).toBeInTheDocument();
  expect(within(main).getByText("sales30-runtime-v1")).toBeInTheDocument();
  expect(within(main).getAllByText("Chưa có dữ liệu")).toHaveLength(2);
  expect(screen.queryByRole("button", { name: "Bật camera" })).not.toBeInTheDocument();
});

it("keeps overview health independent from recognition and recovers after refresh", async () => {
  let offline = false;
  vi.stubGlobal("fetch", async (url: string) => {
    if (offline) throw new TypeError("offline");
    return new Response(JSON.stringify(url.endsWith("/health") ? runtimeHealth : runtimeMetadata));
  });
  render(<App />);
  await userEvent.click(screen.getByRole("button", { name: "Tổng quan" }));
  const main = screen.getByRole("main", { name: "Tổng quan" });
  expect(await within(main).findByText("Dịch vụ đang hoạt động")).toBeInTheDocument();
  offline = true;
  await userEvent.click(within(main).getByRole("button", { name: "Làm mới trạng thái dịch vụ" }));
  expect(await within(main).findByText("Dịch vụ ngoại tuyến")).toBeInTheDocument();
  expect(within(main).getByRole("status")).toHaveTextContent("Dữ liệu lần đọc trước");
  offline = false;
  await userEvent.click(within(main).getByRole("button", { name: "Làm mới trạng thái dịch vụ" }));
  expect(await within(main).findByText("Dịch vụ đang hoạt động")).toBeInTheDocument();
  expect(within(main).queryByRole("status")).not.toBeInTheDocument();
});

it("refreshes recognition identity after returning from a deployment page", async () => {
  let version = "baseline-before-deploy";
  vi.stubGlobal("fetch", async (url: string) => new Response(JSON.stringify(
    url.endsWith("/health") ? { ...runtimeHealth, model_version: version } : { ...runtimeMetadata, model_version: version },
  )));
  render(<App />);
  await userEvent.click(screen.getByText("Cấu hình AI", { exact: true }));
  expect(await screen.findByText(/baseline-before-deploy/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Mô hình nhận dạng" }));
  version = "candidate-after-deploy";
  await userEvent.click(screen.getByRole("button", { name: "Nhận dạng" }));
  expect(await screen.findByText(/candidate-after-deploy/)).toBeInTheDocument();
});

it("observes deployment completing later on the same recognition endpoint", async () => {
  let version="baseline-still-loading";
  vi.stubGlobal('fetch',async()=>new Response(JSON.stringify({...runtimeMetadata,model_version:version})));
  render(<App/>);
  await userEvent.click(screen.getByText('Cấu hình AI',{exact:true}));
  await screen.findByText(/baseline-still-loading/);
  version='candidate-finished-later';
  fireEvent(window,new Event('focus'));
  expect(await screen.findByText(/candidate-finished-later/)).toBeInTheDocument();
});
