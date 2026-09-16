import { describe, expect, it } from "vitest";
import { shouldStartSpaceCapture } from "./keyboard";

describe("Space hold shortcut", () => {
  it("không bắt đầu capture mới khi key repeat", () => {
    expect(
      shouldStartSpaceCapture({ code: "Space", repeat: false, target: document.body }),
    ).toBe(true);
    expect(
      shouldStartSpaceCapture({ code: "Space", repeat: true, target: document.body }),
    ).toBe(false);
  });

  it("không chiếm Space trong control nhập liệu", () => {
    const input = document.createElement("input");
    expect(
      shouldStartSpaceCapture({ code: "Space", repeat: false, target: input }),
    ).toBe(false);
  });
});
