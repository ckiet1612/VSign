import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { WorkspacePage } from "./WorkspacePage";
import { runtimeSnapshot } from "../test/runtimeFixture";

const baseProps = {
  connection: "connected" as const,
  modelVersion: "sales30-v3",
  backend: "coreml",
  protocolVersion: "1.0",
  labelCount: 31,
  labelsVerified: true,
  collectionEnabled: true,
  collectionTarget: 50,
};

describe("WorkspacePage", () => {
  it("hiển thị tổng quan từ runtime thật mà không tạo số liệu giả", () => {
    render(<WorkspacePage {...baseProps} view="overview" />);
    expect(screen.getByRole("heading", { name: "Tổng quan" })).toBeInTheDocument();
    expect(screen.getByText("AI đang hoạt động")).toBeInTheDocument();
    expect(screen.getByText("sales30-v3")).toBeInTheDocument();
    expect(screen.getByText("31 ký hiệu")).toBeInTheDocument();
    expect(screen.queryByText(/lượt nhận dạng hôm nay/i)).not.toBeInTheDocument();
  });

  it("hiển thị model contract trong trang mô hình và triển khai", () => {
    render(<WorkspacePage {...baseProps} view="models" />);
    expect(screen.getByRole("heading", { name: "Mô hình nhận dạng" })).toBeInTheDocument();
    expect(screen.queryByText("coreml")).not.toBeInTheDocument();
    expect(screen.queryByText("Protocol 1.0")).not.toBeInTheDocument();
    expect(screen.getByText("Đã xác minh")).toBeInTheDocument();
  });

  it("không giả trạng thái cho module chưa có nguồn dữ liệu", () => {
    render(<WorkspacePage {...baseProps} view="evaluation" />);
    expect(screen.getByRole("heading", { name: "Chưa có báo cáo đánh giá" })).toBeInTheDocument();
    expect(screen.getByText("Chưa có kết quả đánh giá cho workspace này.")).toBeInTheDocument();
  });

  it("hiển thị giám sát thiếu nguồn mà không bịa metrics", () => {
    render(<WorkspacePage {...baseProps} view="monitoring" />);
    expect(screen.getByRole("heading", { name: "Giám sát" })).toBeInTheDocument();
    expect(screen.getAllByText("Chưa có dữ liệu").length).toBeGreaterThan(0);
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it("dùng health thật cho tổng quan dù WebSocket chưa kết nối", () => {
    render(<WorkspacePage {...baseProps} view="overview" connection="disconnected" runtime={runtimeSnapshot} />);
    expect(screen.getByText("Dịch vụ đang hoạt động")).toBeInTheDocument();
    expect(screen.getByText("sales30-runtime-v1")).toBeInTheDocument();
    expect(screen.getByText("2 ký hiệu")).toBeInTheDocument();
    expect(screen.queryByText("Protocol 1.0")).not.toBeInTheDocument();
    expect(screen.queryByText("sales30-v3")).not.toBeInTheDocument();
  });

  it("giám sát ghi rõ độ trễ health và không dùng nó làm latency inference", () => {
    const refresh = vi.fn();
    render(<WorkspacePage {...baseProps} view="monitoring" runtime={runtimeSnapshot} onRefreshRuntime={refresh} />);
    expect(screen.getByText("12.5 ms")).toBeInTheDocument();
    expect(screen.getByText("Độ trễ kiểm tra kết nối")).toBeInTheDocument();
    expect(screen.queryByText("http://localhost:8003/health")).not.toBeInTheDocument();
    expect(screen.getAllByText("Chưa có dữ liệu")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Làm mới trạng thái dịch vụ" }));
    expect(refresh).toHaveBeenCalledOnce();
  });

  it("không giả model, protocol hoặc số nhãn khi chưa đọc metadata", () => {
    render(<WorkspacePage {...baseProps} view="overview" runtime={{
      ...runtimeSnapshot, health: null, metadata: null, checkedAt: null,
      lastHealthyAt: null, metadataUpdatedAt: null, healthLatencyMs: null, checking: true,
    }} />);
    expect(screen.getByText("Đang kiểm tra dịch vụ")).toBeInTheDocument();
    expect(screen.getByText("Chưa có thông tin ký hiệu")).toBeInTheDocument();
    expect(screen.queryByText("sales30-v3")).not.toBeInTheDocument();
    expect(screen.queryByText("Protocol 1.0")).not.toBeInTheDocument();
    expect(screen.queryByText("Không ghi dữ liệu")).not.toBeInTheDocument();
  });

  it("báo metadata cũ và backend lỗi thay vì trạng thái xanh", () => {
    render(<WorkspacePage {...baseProps} view="monitoring" runtime={{
      ...runtimeSnapshot, healthError: "Không thể kết nối backend", healthLatencyMs: null,
    }} />);
    expect(screen.getByText("Dịch vụ ngoại tuyến")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Dữ liệu lần đọc trước");
    expect(screen.queryByText("Dịch vụ đang hoạt động")).not.toBeInTheDocument();
  });

  it("không coi backend mock là AI thật", () => {
    render(<WorkspacePage {...baseProps} view="overview" runtime={{
      ...runtimeSnapshot, metadata: { ...runtimeSnapshot.metadata, mock: true },
    }} />);
    expect(screen.getByText("Dịch vụ mô phỏng")).toBeInTheDocument();
  });

  it("không gán nhãn và cờ mock cũ cho model mới khi metadata lỗi", () => {
    render(<WorkspacePage {...baseProps} view="overview" runtime={{
      ...runtimeSnapshot,
      health: { ...runtimeSnapshot.health, model_version: "new-real-model" },
      metadata: { ...runtimeSnapshot.metadata, mock: true },
      metadataError: "HTTP 503",
    }} />);
    expect(screen.getByText("Dịch vụ đang hoạt động")).toBeInTheDocument();
    expect(screen.getByText("new-real-model")).toBeInTheDocument();
    expect(screen.queryByText("Dịch vụ mô phỏng")).not.toBeInTheDocument();
    expect(screen.queryByText("2 ký hiệu")).not.toBeInTheDocument();
    expect(screen.getByText("Chưa có thông tin")).toBeInTheDocument();
  });

  it("hiển thị khung tích hợp mà không giả API key hay webhook", () => {
    render(<WorkspacePage {...baseProps} view="integrations" />);
    expect(screen.getByRole("heading", { name: "Tích hợp" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Chưa có tích hợp" })).toBeInTheDocument();
    expect(screen.getByText("Chưa có kết nối được cấu hình cho doanh nghiệp.")).toBeInTheDocument();
    expect(screen.queryByText(/API key/i)).not.toBeInTheDocument();
  });

  it("hiển thị thành viên thật với vai trò", () => {
    render(<WorkspacePage {...baseProps} view="team" members={[{
      id: "user-1", email: "admin@example.com", display_name: "Admin", role: "owner", active: true,
    }]} />);
    expect(screen.getByRole("heading", { name: "Thành viên & quyền" })).toBeInTheDocument();
    expect(screen.getByText(/admin@example.com/)).toBeInTheDocument();
    expect(screen.getByText("Chủ doanh nghiệp")).toBeInTheDocument();
  });

  it("hiển thị audit event thật thay vì KPI giả", () => {
    render(<WorkspacePage {...baseProps} view="activity" auditEvents={[{
      event_id: "event-1", workspace_id: "local", event_type: "auth.login", actor_type: "user",
      actor_id: "user-1", occurred_at: "2026-10-13T10:00:00Z", resource_type: null, resource_id: null,
      outcome: "success", metadata: {},
    }]} />);
    expect(screen.getByRole("heading", { name: "Hoạt động" })).toBeInTheDocument();
    expect(screen.getByText("auth.login")).toBeInTheDocument();
    expect(screen.queryByText(/lượt nhận dạng hôm nay/i)).not.toBeInTheDocument();
  });
});
