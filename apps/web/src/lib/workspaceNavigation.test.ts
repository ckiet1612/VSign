import { describe, expect, it } from "vitest";
import {
  ADMIN_NAVIGATION,
  PRIMARY_NAVIGATION,
  isWorkspaceView,
  type WorkspaceView,
} from "./workspaceNavigation";

describe("workspace navigation", () => {
  it("giữ thứ tự điều hướng B2B và không đưa công cụ phát triển vào nhóm chính", () => {
    expect(PRIMARY_NAVIGATION.map(item => item.id)).toEqual([
      "overview",
      "recognize",
      "reports",
      "data",
      "evaluation",
      "monitoring",
      "models",
      "activity",
    ]);
    expect(ADMIN_NAVIGATION.map(item => item.id)).toEqual(["integrations", "team", "settings"]);
    expect(PRIMARY_NAVIGATION.some(item => item.id === ("dev-test" as WorkspaceView))).toBe(false);
  });

  it("chỉ chấp nhận các view đã định nghĩa", () => {
    expect(isWorkspaceView("models")).toBe(true);
    expect(isWorkspaceView("monitoring")).toBe(true);
    expect(isWorkspaceView("integrations")).toBe(true);
    expect(isWorkspaceView("dev-test")).toBe(false);
    expect(isWorkspaceView("")).toBe(false);
  });
});
