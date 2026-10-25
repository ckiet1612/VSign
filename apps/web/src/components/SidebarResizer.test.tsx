import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import {
  SIDEBAR_DEFAULT_WIDTH,
  SIDEBAR_MAX_WIDTH,
  SIDEBAR_MIN_WIDTH,
  useSidebarLayout,
} from "../hooks/useSidebarLayout";
import { SidebarResizer } from "./SidebarResizer";

beforeAll(() => {
  // jsdom lacks PointerEvent and pointer capture.
  if (!("PointerEvent" in window)) {
    class PointerEventPolyfill extends MouseEvent {
      pointerId: number;
      constructor(type: string, init: PointerEventInit = {}) {
        super(type, init);
        this.pointerId = init.pointerId ?? 0;
      }
    }
    vi.stubGlobal("PointerEvent", PointerEventPolyfill);
  }
  HTMLElement.prototype.setPointerCapture = vi.fn();
});
afterEach(() => window.localStorage.clear());

function renderResizer(props: Partial<Parameters<typeof SidebarResizer>[0]> = {}) {
  const shellRef = createRef<HTMLDivElement>();
  const handlers = { onResize: vi.fn(), onCollapse: vi.fn(), onReset: vi.fn() };
  render(<div ref={shellRef}><SidebarResizer shellRef={shellRef} width={240} collapsed={false} {...handlers} {...props} /></div>);
  return { shellRef, ...handlers, handle: screen.getByRole("separator", { name: "Độ rộng sidebar" }) };
}

describe("useSidebarLayout", () => {
  it("giới hạn độ rộng và lưu lại giữa các phiên", () => {
    const { result } = renderHook(() => useSidebarLayout());
    expect(result.current.width).toBe(SIDEBAR_DEFAULT_WIDTH);
    act(() => result.current.setWidth(999));
    expect(result.current.width).toBe(SIDEBAR_MAX_WIDTH);
    act(() => result.current.toggleCollapsed());
    expect(renderHook(() => useSidebarLayout()).result.current).toMatchObject({ width: SIDEBAR_MAX_WIDTH, collapsed: true });
  });
});

describe("SidebarResizer", () => {
  it("đổi độ rộng bằng bàn phím và thu gọn khi xuống dưới mức tối thiểu", () => {
    const { handle, onResize, onCollapse } = renderResizer({ width: SIDEBAR_MIN_WIDTH + 8 });
    fireEvent.keyDown(handle, { key: "ArrowRight" });
    expect(onResize).toHaveBeenCalledWith(SIDEBAR_MIN_WIDTH + 24);
    fireEvent.keyDown(handle, { key: "ArrowLeft" });
    expect(onCollapse).toHaveBeenCalledWith(true);
  });

  it("kéo sang trái quá ngưỡng thì thu gọn, kéo vừa phải thì đặt độ rộng mới", () => {
    const first = renderResizer();
    fireEvent.pointerDown(first.handle, { button: 0, clientX: 240, pointerId: 1 });
    fireEvent.pointerMove(first.handle, { clientX: 300, pointerId: 1 });
    fireEvent.pointerUp(first.handle, { clientX: 300, pointerId: 1 });
    expect(first.onResize).toHaveBeenCalledWith(300);
    expect(first.shellRef.current?.style.getPropertyValue("--sidebar-width")).toBe("300px");

    fireEvent.pointerDown(first.handle, { button: 0, clientX: 240, pointerId: 1 });
    fireEvent.pointerMove(first.handle, { clientX: 60, pointerId: 1 });
    fireEvent.pointerUp(first.handle, { clientX: 60, pointerId: 1 });
    expect(first.onCollapse).toHaveBeenCalledWith(true);
    expect(first.shellRef.current).toHaveClass("sidebar-collapsed");
  });

  it("không làm sidebar đang thu gọn nhảy ra khi chỉ click vào ranh giới", () => {
    const { handle, shellRef, onCollapse, onResize } = renderResizer({ collapsed: true });
    shellRef.current?.classList.add("sidebar-collapsed");

    fireEvent.pointerDown(handle, { button: 0, clientX: 68, pointerId: 1 });
    fireEvent.pointerUp(handle, { clientX: 68, pointerId: 1 });

    expect(shellRef.current).toHaveClass("sidebar-collapsed");
    expect(shellRef.current).not.toHaveClass("sidebar-resizing");
    expect(onCollapse).not.toHaveBeenCalled();
    expect(onResize).not.toHaveBeenCalled();
  });
});
