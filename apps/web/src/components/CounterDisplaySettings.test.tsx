import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { CounterDisplaySettings } from "./CounterDisplaySettings";

const platformUrl = "http://localhost:8000";
afterEach(() => vi.unstubAllGlobals());

const overview = (extra: object = {}) => ({
  api_version: "1", workspace_id: "local", permissions: { manage: true }, displays: [], enrollments: [], ...extra,
});
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

it("creates a code, then confirms the claimed screen with its verification code", async () => {
  let current = overview();
  const created = { id: "e1", name: "Quầy 1", code: "123456", link_token: "t".repeat(43), expires_at: new Date(Date.now() + 600000).toISOString() };
  const fetcher = vi.fn(async (url: string, init: RequestInit) => {
    if (url.endsWith("/enrollments")) {
      current = overview({ enrollments: [{ id: "e1", name: "Quầy 1", status: "pending", expires_at: created.expires_at, verification: null }] });
      return json(created, 201);
    }
    if (url.endsWith("/confirm")) {
      current = overview({ displays: [{ id: "d1", name: "Quầy 1", online: false, staff: null, last_seen_at: null, created_at: "2026-10-21T00:00:00Z" }] });
      return json(current);
    }
    expect(init.method ?? "GET").toBe("GET");
    return json(current);
  });
  vi.stubGlobal("fetch", fetcher);
  render(<CounterDisplaySettings platformUrl={platformUrl} />);
  await screen.findByText("Chưa có màn hình quầy nào.");

  fireEvent.change(screen.getByLabelText("Tên quầy"), { target: { value: "  Quầy 1 " } });
  fireEvent.click(screen.getByRole("button", { name: "Thêm màn hình quầy" }));
  const card = await screen.findByRole("region", { name: "Đăng ký Quầy 1" });
  expect(within(card).getByLabelText("Mã 1 2 3 4 5 6")).toHaveTextContent("123 456");
  expect(within(card).getByRole("img", { name: "Mã QR mở màn hình quầy" })).toBeInTheDocument();
  const create = fetcher.mock.calls.find(([url]) => url.endsWith("/enrollments"))!;
  expect(JSON.parse(String(create[1].body))).toEqual({ name: "Quầy 1" });

  // The customer laptop claims the code; the next poll brings its verification code.
  current = overview({ enrollments: [{ id: "e1", name: "Quầy 1", status: "awaiting_confirmation", expires_at: created.expires_at, verification: "K7" }] });
  expect(await screen.findByLabelText("Mã đối chiếu K 7", {}, { timeout: 3000 })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Xác nhận" }));
  await screen.findByText("Đã xác nhận màn hình quầy.");
  expect(screen.getByText("Quầy 1")).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Đăng ký Quầy 1" })).not.toBeInTheDocument();
});

it("revokes a counter only after an explicit confirmation", async () => {
  const row = { id: "d1", name: "Quầy 1", online: true, staff: "Lan", last_seen_at: null, created_at: "2026-10-21T00:00:00Z" };
  const fetcher = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(async url => json(url.endsWith("/revoke") ? overview() : overview({ displays: [row] })));
  vi.stubGlobal("fetch", fetcher);
  render(<CounterDisplaySettings platformUrl={platformUrl} />);
  expect(await screen.findByText(/Lan đang phục vụ/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Huỷ" }));
  expect(fetcher.mock.calls.some(([url]) => url.endsWith("/revoke"))).toBe(false);
  const confirm = screen.getByRole("region", { name: "Xác nhận thay đổi" });
  fireEvent.click(within(confirm).getByRole("button", { name: "Xác nhận" }));
  await screen.findByText("Chưa có màn hình quầy nào.");
  expect(fetcher.mock.calls.find(([url]) => url.endsWith("/revoke"))?.[1]?.method).toBe("POST");
});

it("tells non-managers that only administrators manage counters", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json(overview({ permissions: { manage: false } }))));
  render(<CounterDisplaySettings platformUrl={platformUrl} />);
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Chỉ quản trị viên"));
  expect(screen.queryByLabelText("Tên quầy")).not.toBeInTheDocument();
});
