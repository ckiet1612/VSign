import { afterEach, describe, expect, it } from "vitest";
import { trackInputModality } from "./inputModality";

describe("input modality", () => {
  let stop = () => undefined as void;
  afterEach(() => stop());
  const root = document.documentElement;
  const press = (key: string) => document.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
  const pointer = (type: string) => document.dispatchEvent(Object.assign(new Event(type, { bubbles: true }), { isPrimary: true }));

  it("keeps the pointer modality when Space or Enter presses a clicked tab", () => {
    stop = trackInputModality();
    pointer("pointerdown");
    expect(root.dataset.input).toBe("pointer");
    expect(root.dataset.pointerDown).toBe("");
    pointer("pointerup");
    expect(root.dataset.pointerDown).toBeUndefined();
    press(" ");
    press("Enter");
    expect(root.dataset.input).toBe("pointer");
  });

  it("switches to keyboard once focus is moved with Tab or the arrows, and back on a click", () => {
    stop = trackInputModality();
    press("Tab");
    expect(root.dataset.input).toBe("keyboard");
    pointer("pointerdown");
    expect(root.dataset.input).toBe("pointer");
    press("ArrowRight");
    expect(root.dataset.input).toBe("keyboard");
  });

  it("removes its marks when stopped", () => {
    stop = trackInputModality();
    pointer("pointerdown");
    stop();
    expect(root.dataset.input).toBeUndefined();
    expect(root.dataset.pointerDown).toBeUndefined();
  });
});
