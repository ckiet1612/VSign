import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AppSidebar } from "./AppSidebar";

describe("AppSidebar", () => {
  it("reserves logout for an icon and exposes the full account labels on hover", async () => {
    const onLogout = vi.fn(async () => undefined);
    const displayName = "Quan tri vien he thong VSign voi ten rat dai";
    render(<AppSidebar activeView="overview" onNavigate={vi.fn()} onLogout={onLogout}
      user={{ id: "admin", email: "admin@example.com", display_name: displayName, role: "system_admin" }} />);

    expect(screen.getByText(displayName)).toHaveAttribute("title", displayName);
    expect(screen.getByText("Quản trị hệ thống")).toHaveAttribute("title", "Quản trị hệ thống");
    const logout = screen.getByRole("button", { name: "Đăng xuất" });
    expect(logout).toHaveAttribute("title", "Đăng xuất");
    expect(logout).toHaveTextContent("");
    expect(logout.querySelector("span")).toBeNull();
    await userEvent.click(logout);
    expect(onLogout).toHaveBeenCalledOnce();
  });

  it("shows the local admin without offering logout", () => {
    render(<AppSidebar activeView="models" onNavigate={vi.fn()}
      user={{ id: "local-admin", email: "local@vsign.invalid", display_name: "Admin local", role: "admin" }} />);
    expect(screen.getByText("Admin local")).toBeInTheDocument();
    expect(screen.getByText("Quản trị doanh nghiệp")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Đăng xuất" })).not.toBeInTheDocument();
  });

  it("hiển thị logo, người dùng và điều hướng bằng nhãn nghiệp vụ", async () => {
    const onNavigate = vi.fn();
    const user = userEvent.setup();
    render(
      <AppSidebar
        activeView="recognize"
        capabilities={{
          data: true,
          evaluation: true,
          activity: true,
          monitoring: true,
          integrations: true,
          team: true,
        }}
        user={{ id: "user-1", email: "admin@example.com", display_name: "Admin", role: "owner" }}
        onLogout={vi.fn(async () => undefined)}
        onNavigate={onNavigate}
      />,
    );

    expect(screen.getByRole("navigation", { name: "Workspace" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "VSign" })).toBeInTheDocument();
    expect(screen.getByText("Chủ doanh nghiệp")).toBeInTheDocument();
    expect(screen.getByText("Admin")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Đăng xuất" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Nhận dạng" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: "Giám sát" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Tích hợp" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Mô hình nhận dạng" }));
    expect(onNavigate).toHaveBeenCalledWith("models");
  });

  it("giữ mục chưa có capability ở trạng thái disabled thay vì ẩn khỏi taxonomy", () => {
    render(
      <AppSidebar
        activeView="recognize"
        capabilities={{ monitoring: false, integrations: false }}
        onNavigate={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Giám sát" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Tích hợp" })).toBeDisabled();
  });

  it("đóng drawer mobile sau khi chọn mục điều hướng", async () => {
    const onNavigate = vi.fn();
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<AppSidebar activeView="overview" mobileOpen onClose={onClose} onNavigate={onNavigate} />);

    expect(screen.getByRole("complementary")).toHaveClass("mobile-open");
    await user.click(screen.getByRole("button", { name: "Nhận dạng" }));
    expect(onNavigate).toHaveBeenCalledWith("recognize");
    expect(onClose).toHaveBeenCalledOnce();
  });
});
