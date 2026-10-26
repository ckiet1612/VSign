import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useWorkspaceNavigation } from "./useWorkspaceNavigation";

describe("useWorkspaceNavigation", () => {
  it("đọc view từ URL và giữ được deep link khi chuyển trang", () => {
    window.history.replaceState({}, "", "/models");
    const { result } = renderHook(() => useWorkspaceNavigation());
    expect(result.current.view).toBe("models");
    act(() => result.current.navigate("recognize"));
    expect(result.current.view).toBe("recognize");
    expect(window.location.pathname).toBe("/recognize");
    expect(window.location.search).toBe("");
  });

  it("mở landing view ngay ở lần render đầu khi URL chưa có view", () => {
    window.history.replaceState({}, "", "/");
    const { result } = renderHook(() => useWorkspaceNavigation("overview"));
    expect(result.current.view).toBe("overview");
    expect(window.location.pathname).toBe("/overview");
  });

  it("ghi view=recognize khi landing khác để reload vẫn ở Nhận dạng", () => {
    window.history.replaceState({}, "", "/");
    const { result } = renderHook(() => useWorkspaceNavigation("overview"));
    act(() => result.current.navigate("recognize"));
    expect(window.location.pathname).toBe("/recognize");
    const reloaded = renderHook(() => useWorkspaceNavigation("overview"));
    expect(reloaded.result.current.view).toBe("recognize");
  });

  it("deep link vẫn thắng landing view", () => {
    window.history.replaceState({}, "", "/team");
    const { result } = renderHook(() => useWorkspaceNavigation("overview"));
    expect(result.current.view).toBe("team");
  });

  it("nhận diện view cha khi URL có tab con", () => {
    window.history.replaceState({}, "", "/data/sessions");
    const { result } = renderHook(() => useWorkspaceNavigation());
    expect(result.current.view).toBe("data");
  });

  it("giữ query cũ để tương thích và đưa URL về path sạch", () => {
    window.history.replaceState({}, "", "/?view=models&tab=details");
    const { result } = renderHook(() => useWorkspaceNavigation());
    expect(result.current.view).toBe("models");
    expect(window.location.pathname).toBe("/models");
    expect(window.location.search).toBe("?tab=details");
  });
});
