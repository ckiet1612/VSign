import { beforeEach, describe, expect, it, vi } from "vitest";
import { copyText } from "./copy";

describe("copyText", () => {
  beforeEach(() => {
    Object.defineProperty(document, "execCommand", {
      configurable: true,
      value: vi.fn(() => true),
    });
  });

  it("dùng Clipboard API khi thành công", async () => {
    const clipboard = { writeText: vi.fn().mockResolvedValue(undefined) };
    await expect(copyText("xin chào", clipboard)).resolves.toBe("clipboard");
    expect(clipboard.writeText).toHaveBeenCalledWith("xin chào");
  });

  it("fallback khi Clipboard API thất bại", async () => {
    const clipboard = { writeText: vi.fn().mockRejectedValue(new Error("denied")) };
    await expect(copyText("cảm ơn", clipboard)).resolves.toBe("fallback");
    expect(document.execCommand).toHaveBeenCalledWith("copy");
  });

  it("báo lỗi khi cả hai cách sao chép đều thất bại", async () => {
    Object.defineProperty(document, "execCommand", {
      configurable: true,
      value: vi.fn(() => false),
    });
    await expect(copyText("xin lỗi", undefined)).rejects.toThrow(
      "không cho phép sao chép",
    );
  });
});
