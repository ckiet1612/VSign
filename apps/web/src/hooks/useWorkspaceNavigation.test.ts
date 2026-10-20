import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useWorkspaceNavigation } from "./useWorkspaceNavigation";

describe("useWorkspaceNavigation", () => {
  it("đọc view từ URL và giữ được deep link khi chuyển trang", () => {
    window.history.replaceState({}, "", "/?view=models");
    const { result } = renderHook(() => useWorkspaceNavigation());
    expect(result.current.view).toBe("models");
    act(() => result.current.navigate("recognize"));
    expect(result.current.view).toBe("recognize");
    expect(window.location.search).toBe("");
  });

  it("mở landing view ngay ở lần render đầu khi URL chưa có view", () => {
    window.history.replaceState({}, "", "/");
    const { result } = renderHook(() => useWorkspaceNavigation("overview"));
    expect(result.current.view).toBe("overview");
    expect(window.location.search).toBe("?view=overview");
  });

  it("ghi view=recognize khi landing khác để reload vẫn ở Nhận dạng", () => {
    window.history.replaceState({}, "", "/");
    const { result } = renderHook(() => useWorkspaceNavigation("overview"));
    act(() => result.current.navigate("recognize"));
    expect(window.location.search).toBe("?view=recognize");
    const reloaded = renderHook(() => useWorkspaceNavigation("overview"));
    expect(reloaded.result.current.view).toBe("recognize");
  });

  it("deep link vẫn thắng landing view", () => {
    window.history.replaceState({}, "", "/?view=team");
    const { result } = renderHook(() => useWorkspaceNavigation("overview"));
    expect(result.current.view).toBe("team");
  });
});
