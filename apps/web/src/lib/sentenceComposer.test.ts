import { describe, expect, it, vi } from "vitest";
import { composeSentence } from "./sentenceComposer";

describe("composeSentence", () => {
  it("rejects malformed grammar warnings rather than presenting an unchecked draft", async () => {
    const fetcher = vi.fn(async () => ({ ok: true, json: async () => ({
      sentence: "Laptop mới cũ.", warnings: "not-an-array",
    }) }));
    await expect(composeSentence("http://localhost:8000", ["Laptop", "Mới", "Cũ"], fetcher))
      .rejects.toThrow("Câu hoàn thiện không hợp lệ.");
  });
  it("gửi đúng chuỗi từ đã xác nhận và đọc câu hoàn thiện", async () => {
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        sentence: "Tôi muốn mua điện thoại.",
        provider: "openai",
        model: "test-model",
      }),
    });

    const result = await composeSentence(
      "http://localhost:8000",
      ["Tôi", "Muốn", "Mua", "Điện thoại"],
      fetcher,
    );

    expect(fetcher).toHaveBeenCalledWith(
      "http://localhost:8000/sentence/compose",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ words: ["Tôi", "Muốn", "Mua", "Điện thoại"] }),
      },
    );
    expect(result.sentence).toBe("Tôi muốn mua điện thoại.");
  });

  it("báo lỗi khi máy chủ trả payload không hợp lệ", async () => {
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ sentence: "" }),
    });

    await expect(
      composeSentence("http://localhost:8000", ["Cảm ơn"], fetcher),
    ).rejects.toThrow("Câu hoàn thiện không hợp lệ");
  });
});
