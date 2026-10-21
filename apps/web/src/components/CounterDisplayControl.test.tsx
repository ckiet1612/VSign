import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { CounterDisplayController } from "../hooks/useCounterDisplay";
import { CounterDisplayControl } from "./CounterDisplayControl";

const row = (id: string, name: string, extra: object = {}) => ({
  id, name, online: false, staff: null, last_seen_at: null, created_at: "2026-10-21T00:00:00Z", ...extra,
});

function controller(extra: Partial<CounterDisplayController> = {}): CounterDisplayController {
  return {
    overview: { api_version: "1", workspace_id: "local", permissions: { manage: true },
      displays: [row("d1", "Quầy 1", { online: true }), row("d2", "Quầy 2", { staff: "Minh" })], enrollments: [] },
    listError: "", refresh: vi.fn(async () => undefined), selectedId: null, displayName: "",
    connected: false, channelStatus: "closed", deviceOnline: false, occupiedBy: null, notice: "",
    videoState: "idle", remoteStream: undefined,
    connect: vi.fn(), endSession: vi.fn(), newConversation: vi.fn(), publish: vi.fn(), dismissNotice: vi.fn(),
    ...extra,
  } as unknown as CounterDisplayController;
}

it("picks a counter from the camera source menu and closes it", () => {
  const display = controller();
  render(<CounterDisplayControl display={display} onNewConversation={vi.fn()} locked={false} />);
  const trigger = screen.getByRole("button", { name: /Nguồn camera/ });
  expect(trigger).toHaveTextContent("Máy này");
  expect(trigger).toHaveAttribute("aria-expanded", "false");

  fireEvent.click(trigger);
  const menu = screen.getByRole("menu", { name: "Chọn nguồn camera" });
  expect(display.refresh).toHaveBeenCalled();
  expect(within(menu).getByRole("menuitemradio", { name: /Camera máy này/ })).toHaveAttribute("aria-checked", "true");
  expect(within(menu).getByRole("menuitemradio", { name: /Quầy 1/ })).toHaveTextContent("Đang mở");
  expect(within(menu).getByRole("menuitemradio", { name: /Quầy 2/ })).toHaveTextContent("Chưa mở · Minh đang dùng");

  fireEvent.click(within(menu).getByRole("menuitemradio", { name: /Quầy 1/ }));
  expect(display.connect).toHaveBeenCalledWith("d1");
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
});

it("closes the menu with Escape and outside clicks, and stays shut while a capture runs", () => {
  const { rerender } = render(<CounterDisplayControl display={controller()} onNewConversation={vi.fn()} locked={false} />);
  const trigger = screen.getByRole("button", { name: /Nguồn camera/ });
  fireEvent.click(trigger);
  fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();

  fireEvent.click(trigger);
  fireEvent.pointerDown(document.body);
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();

  rerender(<CounterDisplayControl display={controller()} onNewConversation={vi.fn()} locked />);
  expect(screen.getByRole("button", { name: /Nguồn camera/ })).toBeDisabled();
});

it("shows the served counter with its live status and session actions", () => {
  const onNewConversation = vi.fn();
  const display = controller({ connected: true, selectedId: "d1", displayName: "Quầy 1", channelStatus: "open",
    deviceOnline: true, videoState: "connected", remoteStream: {} as MediaStream });
  render(<CounterDisplayControl display={display} onNewConversation={onNewConversation} locked={false} />);
  const group = screen.getByRole("group", { name: "Màn hình khách" });
  expect(group).toHaveTextContent("Quầy 1");
  expect(within(group).getByRole("status")).toHaveTextContent("Đang phục vụ");
  fireEvent.click(within(group).getByRole("button", { name: "Cuộc hội thoại mới" }));
  expect(onNewConversation).toHaveBeenCalled();
  fireEvent.click(within(group).getByRole("button", { name: "Kết thúc phiên" }));
  expect(display.endSession).toHaveBeenCalled();
});

it("offers a takeover for an occupied counter and lets notices be dismissed", () => {
  const display = controller({ selectedId: "d2", occupiedBy: "Minh", notice: "Minh đã tiếp quản quầy này." });
  render(<CounterDisplayControl display={display} onNewConversation={vi.fn()} locked={false} />);
  expect(screen.getByText(/đang được/)).toHaveTextContent("Quầy 2 đang được Minh sử dụng.");
  fireEvent.click(screen.getByRole("button", { name: "Tiếp quản" }));
  expect(display.connect).toHaveBeenCalledWith("d2", true);
  fireEvent.click(screen.getByRole("button", { name: "Đóng thông báo" }));
  expect(display.dismissNotice).toHaveBeenCalled();
});

it("is hidden from staff who cannot add counters when none exist", () => {
  const display = controller({ overview: { api_version: "1", workspace_id: "local", permissions: { manage: false }, displays: [], enrollments: [] } });
  const { container } = render(<CounterDisplayControl display={display} onNewConversation={vi.fn()} locked={false} />);
  expect(container).toBeEmptyDOMElement();
});
