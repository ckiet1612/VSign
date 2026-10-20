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

  it.each(["input", "textarea", "select", "button", "a", "summary"])("không chiếm Space trong control %s", (tag) => {
    const input = document.createElement(tag);
    expect(
      shouldStartSpaceCapture({ code: "Space", repeat: false, target: input }),
    ).toBe(false);
  });
});
