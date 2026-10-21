import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SystemDashboard } from "./SystemDashboard";
import { dashboardFixture } from "../test/dashboardFixture";
import { runtimeSnapshot } from "../test/runtimeFixture";

const user = { id: "system", email: "system@example.com", display_name: "Admin", role: "system_admin" as const };
const props = { platformUrl: "http://platform", workspaceId: "local", user, runtime: runtimeSnapshot, onNavigate: vi.fn() };
beforeEach(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});
afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });

it("renders real totals, chart data, quota progress and worker blockers", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(dashboardFixture(30)))));
  render(<SystemDashboard {...props} />);
  expect(await screen.findByText("128")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Mẫu thu theo ngày" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Phân bố ký hiệu" })).toBeInTheDocument();
  expect(screen.getByRole("progressbar", { name: "Hạn mức Chào" })).toHaveAttribute("aria-valuenow", "128");
  expect(screen.getByText("candidate-v1")).toBeInTheDocument();
  expect(screen.getByText("Worker triển khai chưa sẵn sàng")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Xem dữ liệu" }));
  expect(props.onNavigate).toHaveBeenCalledWith("data");
});

it("refetches the selected range and refreshes on command", async () => {
  const fetcher = vi.fn(async (url: string) => new Response(JSON.stringify(dashboardFixture(Number(new URL(url).searchParams.get("days")) as 7 | 30 | 90))));
  vi.stubGlobal("fetch", fetcher);
  render(<SystemDashboard {...props} />);
  await screen.findByText("128");
  fireEvent.click(screen.getByRole("radio", { name: "7 ngày" }));
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.endsWith("days=7"))).toBe(true));
  await screen.findByText("128");
  fireEvent.click(screen.getByRole("button", { name: "Làm mới tổng quan" }));
  await waitFor(() => expect(fetcher.mock.calls).toHaveLength(3));
});

it("keeps the previous range on screen while another range loads", async () => {
  let resolveWeek!: (response: Response) => void;
  vi.stubGlobal("fetch", (url: string) => url.endsWith("days=7") ? new Promise<Response>(resolve => { resolveWeek = resolve; })
    : Promise.resolve(new Response(JSON.stringify(dashboardFixture(30)))));
  render(<SystemDashboard {...props} />);
  await screen.findByText("128");
  fireEvent.click(screen.getByRole("radio", { name: "7 ngày" }));
  expect(screen.getByText("128")).toBeInTheDocument();
  expect(screen.queryByText("Đang tải thống kê...")).not.toBeInTheDocument();
  expect(screen.getByText("Trong 30 ngày")).toBeInTheDocument();
  resolveWeek(new Response(JSON.stringify(dashboardFixture(7))));
  expect(await screen.findByText("Trong 7 ngày")).toBeInTheDocument();
});

it("shows an error instead of fabricated zero metrics and offers retry", async () => {
  const fetcher = vi.fn(async () => new Response("{}", { status: 503 }));
  vi.stubGlobal("fetch", fetcher);
  render(<SystemDashboard {...props} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Không thể tải thống kê");
  expect(screen.queryByText("128")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Thử lại" }));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
});

it("rejects cross-workspace data rather than displaying another workspace totals", async () => {
  vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ ...dashboardFixture(30), workspace_id: "other" })));
  render(<SystemDashboard {...props} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Phản hồi thống kê không hợp lệ");
  expect(screen.queryByText("128")).not.toBeInTheDocument();
});

it("renders honest empty charts and no invented growth rates", async () => {
  const fixture = dashboardFixture(30);
  fixture.totals = { samples: 0, datasets_draft: 0, datasets_sealed: 0, models: 0, evaluations: 0 };
  fixture.period = { samples: 0, evaluations: 0, events: 0 };
  fixture.daily_samples = fixture.daily_samples.map(row => ({ ...row, count: 0 }));
  fixture.label_progress = []; fixture.recent_activity = []; fixture.recent_evaluations = [];
  vi.stubGlobal("fetch", async () => new Response(JSON.stringify(fixture)));
  render(<SystemDashboard {...props} />);
  expect(await screen.findByText("Chưa có mẫu thu trong kỳ")).toBeInTheDocument();
  expect(screen.getByText("Chưa có dữ liệu ký hiệu")).toBeInTheDocument();
  expect(screen.getByText("Chưa có lượt đánh giá trong kỳ")).toBeInTheDocument();
  expect(screen.queryByText(/tăng trưởng/i)).not.toBeInTheDocument();
});

it("labels common system events in Vietnamese and preserves unknown event names", async () => {
  const fixture = dashboardFixture(30);
  fixture.recent_activity = ["permission.denied", "auth.login_failed", "model.baseline_observed", "display.enrollment_confirmed", "display.future_action", "custom.event"].map(event_type => ({
    id: event_type, event_type, outcome: "failure", occurred_at: "2026-10-18T11:00:00Z",
  }));
  vi.stubGlobal("fetch", async () => new Response(JSON.stringify(fixture)));
  render(<SystemDashboard {...props} />);
  expect(await screen.findByText("Từ chối truy cập")).toBeInTheDocument();
  expect(screen.getByText("Đăng nhập thất bại")).toBeInTheDocument();
  expect(screen.getByText("Ghi nhận phiên bản ban đầu")).toBeInTheDocument();
  expect(screen.getByText("Xác nhận màn hình khách")).toBeInTheDocument();
  // A new event of a known group is named by its group rather than shown as a raw type.
  expect(screen.getByText("Màn hình khách")).toBeInTheDocument();
  expect(screen.getByText("custom.event")).toBeInTheDocument();
});
