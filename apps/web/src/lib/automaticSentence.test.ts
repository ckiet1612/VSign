import { describe, expect, it } from "vitest";
import { AutomaticSentence, SENTENCE_PAUSE_MS } from "./automaticSentence";

describe("automatic sentence drafts", () => {
  it("skips an unrecognized capture without a warning and still composes the words", () => {
    const sentence = new AutomaticSentence();
    sentence.sync(["Mua"], 0);
    const capture = sentence.activity(100);
    sentence.skip(capture, 200);
    expect(sentence.drafts[0].warning).toBe("");
    expect(sentence.prepare(200 + SENTENCE_PAUSE_MS, false)?.words).toEqual(["Mua"]);
  });
  it("does not erase a capture gap when composition fails and later recovers", () => {
    const sentence = new AutomaticSentence();
    sentence.sync(["Mua"], 0);
    sentence.missing("Có đoạn chưa nhận dạng", 100);
    const request = sentence.prepare(2000, false)!;
    sentence.fail(request, "Ghép câu quá thời gian");
    expect(sentence.drafts[0].warning).toBe("Có đoạn chưa nhận dạng");
    expect(sentence.drafts[0].compositionWarning).toBe("Ghép câu quá thời gian");
    expect(sentence.drafts[0].status).toBe("review");
    sentence.sync(["Mua", "Sữa"], 5000);
    const next = sentence.prepare(7000, false)!;
    sentence.resolve(next, "Mua sữa.");
    expect(sentence.drafts[0].warning).toBe("Có đoạn chưa nhận dạng");
    expect(sentence.drafts[0].compositionWarning).toBe("");
    expect(sentence.drafts[0].status).toBe("review");
  });
  it("keeps grammar review separate from capture gaps and clears it on recomposition", () => {
    const sentence = new AutomaticSentence();
    sentence.sync(["Laptop", "Mới", "Cũ"], 0);
    sentence.missing("Có đoạn chưa nhận dạng", 100);
    const request = sentence.prepare(2000, false)!;
    sentence.resolve(request, "Laptop mới cũ.", ["Thuộc tính chưa rõ"]);
    expect(sentence.drafts[0].warning).toBe("Có đoạn chưa nhận dạng");
    expect(sentence.drafts[0].compositionWarning).toBe("Thuộc tính chưa rõ");
    expect(sentence.drafts[0].status).toBe("review");
    expect(sentence.prepare(4000, false)).toBeNull();
    sentence.sync(["Laptop", "Mới"], 5000);
    const next = sentence.prepare(7000, false)!;
    sentence.resolve(next, "Laptop mới.", []);
    expect(sentence.drafts[0].compositionWarning).toBe("");
    expect(sentence.drafts[0].warning).toBe("Có đoạn chưa nhận dạng");
    expect(sentence.drafts[0].status).toBe("review");
  });
  it("keeps a capture gap on the single draft and normalizes every word together", () => {
    const sentence = new AutomaticSentence();
    sentence.sync(["Tôi", "Muốn", "Mua"], 0);
    sentence.missing("Có đoạn chưa nhận dạng", 100);
    const capture = sentence.activity(6000);
    sentence.finish(capture, 7000);
    sentence.accept(capture, ["Tôi", "Muốn", "Mua", "Tủ lạnh"], 8000);
    const request = sentence.prepare(10000, false)!;
    expect(request.words).toEqual(["Tôi", "Muốn", "Mua", "Tủ lạnh"]);
    sentence.resolve(request, "Tôi muốn mua tủ lạnh.");
    expect(sentence.drafts).toHaveLength(1);
    expect(sentence.drafts[0].warning).toBe("Có đoạn chưa nhận dạng");
  });

  it("keeps captures separated by a long pause in one draft, in capture order", () => {
    const sentence = new AutomaticSentence();
    const first = sentence.activity(0);
    sentence.finish(first, 1000);
    const second = sentence.activity(6100);
    sentence.finish(second, 7000);
    sentence.accept(first, ["Mua"], 8000);
    sentence.accept(second, ["Mua", "Tủ lạnh"], 8100);
    expect(sentence.drafts.map(item => item.words)).toEqual([["Mua", "Tủ lạnh"]]);
    expect(sentence.prepare(10100, false)?.words).toEqual(["Mua", "Tủ lạnh"]);
  });

  it("drops a pending composition when signing resumes and normalizes the extended word set", () => {
    const sentence = new AutomaticSentence();
    sentence.sync(["Mua"], 0);
    const request = sentence.prepare(SENTENCE_PAUSE_MS, false)!;
    const capture = sentence.activity(6000);
    sentence.finish(capture, 7000);
    expect(sentence.resolve(request, "Mua.")).toBe(false);
    sentence.accept(capture, ["Mua", "Tủ lạnh"], 8000);
    expect(sentence.prepare(10000, false)?.words).toEqual(["Mua", "Tủ lạnh"]);
  });

  it("waits for the end of a long capture before measuring the inter-sentence pause", () => {
    const sentence = new AutomaticSentence();
    const first = sentence.activity(0);
    sentence.finish(first, 3000);
    sentence.accept(first, ["Mua"], 3500);
    const suffix = sentence.activity(6000);
    sentence.finish(suffix, 7000);
    sentence.accept(suffix, ["Mua", "Tủ lạnh"], 7500);
    expect(sentence.drafts).toHaveLength(1);
    expect(sentence.drafts[0].words).toEqual(["Mua", "Tủ lạnh"]);
  });

  it("keeps a late uncertainty on its original sentence rather than blocking the next one", () => {
    const sentence = new AutomaticSentence();
    const first = sentence.activity(0);
    sentence.finish(first, 1000);
    const second = sentence.activity(6100);
    sentence.finish(second, 7000);
    sentence.missing("Có đoạn chưa nhận dạng", 8000, first);
    sentence.accept(second, ["Tủ lạnh"], 8500);
    expect(sentence.drafts[0].status).toBe("review");
    expect(sentence.prepare(11000, false)?.words).toEqual(["Tủ lạnh"]);
  });

  it("waits for a quiet boundary and keeps every recognized qualifier", () => {
    const sentence = new AutomaticSentence();
    sentence.sync(["Tôi", "Muốn", "Mua", "Tủ lạnh"], 100);
    expect(sentence.prepare(100 + SENTENCE_PAUSE_MS - 1, false)).toBeNull();
    expect(sentence.prepare(100 + SENTENCE_PAUSE_MS, true)).toBeNull();
    const capture = sentence.activity(3000);
    sentence.finish(capture, 4000);
    sentence.accept(capture, ["Tôi", "Muốn", "Mua", "Tủ lạnh", "Rẻ"], 7000);
    const request = sentence.prepare(7000 + SENTENCE_PAUSE_MS, false)!;
    expect(request.words).toEqual(["Tôi", "Muốn", "Mua", "Tủ lạnh", "Rẻ"]);
    expect(sentence.resolve(request, "Tôi muốn mua tủ lạnh rẻ.")).toBe(true);
    expect(sentence.drafts[0].status).toBe("draft");
  });

  it("invalidates an in-flight composition when signing resumes", () => {
    const sentence = new AutomaticSentence();
    sentence.sync(["Tôi", "Muốn", "Mua", "Tủ lạnh"], 0);
    const old = sentence.prepare(SENTENCE_PAUSE_MS, false)!;
    const capture = sentence.activity(SENTENCE_PAUSE_MS + 10);
    expect(sentence.resolve(old, "Tôi muốn mua tủ lạnh.")).toBe(false);
    sentence.finish(capture, 3000);
    sentence.accept(capture, [...old.words, "Rẻ"], 9000);
    const revised = sentence.prepare(9000 + SENTENCE_PAUSE_MS, false)!;
    expect(revised.words.at(-1)).toBe("Rẻ");
  });

  it("revises an already displayed draft for a late suffix without creating a second sentence", () => {
    const sentence = new AutomaticSentence();
    sentence.sync(["Tôi", "Muốn", "Mua", "Tủ lạnh"], 0);
    const request = sentence.prepare(SENTENCE_PAUSE_MS, false)!;
    sentence.resolve(request, "Tôi muốn mua tủ lạnh.");
    const capture = sentence.activity(4999);
    sentence.finish(capture, 6000);
    sentence.accept(capture, [...request.words, "Rẻ"], 10000);
    expect(sentence.drafts).toHaveLength(1);
    expect(sentence.drafts[0].sentence).toBe("");
    expect(sentence.drafts[0].words.at(-1)).toBe("Rẻ");
  });

  it("re-normalizes the whole word set after a long pause instead of starting a new sentence", () => {
    const sentence = new AutomaticSentence();
    sentence.sync(["Chào"], 0);
    sentence.resolve(sentence.prepare(SENTENCE_PAUSE_MS, false)!, "Chào.");
    const capture = sentence.activity(60000);
    sentence.finish(capture, 60500);
    sentence.accept(capture, ["Chào", "Tôi", "Muốn", "Mua"], 61000);
    expect(sentence.drafts.map(item => item.words)).toEqual([["Chào", "Tôi", "Muốn", "Mua"]]);
    expect(sentence.prepare(61000 + SENTENCE_PAUSE_MS, false)?.words).toEqual(["Chào", "Tôi", "Muốn", "Mua"]);
  });

  it("composes the recognized words once after an uncertain segment while retaining review", () => {
    const sentence = new AutomaticSentence();
    sentence.sync(["Tôi", "Muốn", "Mua", "Tủ lạnh"], 0);
    sentence.missing("Có đoạn chưa nhận dạng", 1000);
    const first = sentence.prepare(10000, false)!;
    expect(first.words).toEqual(["Tôi", "Muốn", "Mua", "Tủ lạnh"]);
    expect(sentence.resolve(first, "Tôi muốn mua tủ lạnh.")).toBe(true);
    expect(sentence.drafts[0].status).toBe("review");
    expect(sentence.drafts[0].warning).toBe("Có đoạn chưa nhận dạng");
    expect(sentence.prepare(10500, false)).toBeNull();
    sentence.sync(["Tôi", "Muốn", "Mua", "Tủ lạnh", "Rẻ"], 11000);
    expect(sentence.drafts[0].warning).toBe("Có đoạn chưa nhận dạng");
    const revised = sentence.prepare(20000, false)!;
    expect(revised.words.at(-1)).toBe("Rẻ");
  });

  it("clear, undo and context reset invalidate replies, including identical restored text", () => {
    const sentence = new AutomaticSentence();
    sentence.sync(["Mua"], 0);
    const old = sentence.prepare(SENTENCE_PAUSE_MS, false)!;
    sentence.reset();
    sentence.sync(["Mua"], 0);
    expect(sentence.resolve(old, "Mua.")).toBe(false);
    const next = sentence.prepare(SENTENCE_PAUSE_MS, false)!;
    sentence.sync([], 3000);
    expect(sentence.resolve(next, "Mua.")).toBe(false);
    expect(sentence.drafts).toEqual([]);
  });

  it("does not retry failed composition forever without new words", () => {
    const sentence = new AutomaticSentence();
    sentence.sync(["Mua"], 0);
    const request = sentence.prepare(SENTENCE_PAUSE_MS, false)!;
    sentence.fail(request, "Không kết nối được máy chủ");
    expect(sentence.prepare(10000, false)).toBeNull();
    expect(sentence.drafts[0].status).toBe("review");
  });

  it("keeps a repeated word signed after a pause as a new word of the same draft", () => {
    const sentence = new AutomaticSentence();
    sentence.sync(["Mua"], 0);
    sentence.resolve(sentence.prepare(1800, false)!, "Mua.");
    const capture = sentence.activity(6000);
    sentence.finish(capture, 7000);
    sentence.accept(capture, ["Mua", "Mua"], 7500);
    expect(sentence.prepare(9500, false)?.words).toEqual(["Mua", "Mua"]);
  });

  it("ignores old capture tokens after clearing, even when the new words are identical", () => {
    const sentence = new AutomaticSentence();
    const old = sentence.activity(0);
    sentence.finish(old, 1000);
    sentence.reset();
    const next = sentence.activity(6000);
    sentence.finish(next, 7000);
    sentence.accept(old, ["Mua"], 8000);
    sentence.missing("Lỗi cũ", 8100, old);
    expect(sentence.drafts[0].words).toEqual([]);
    expect(sentence.drafts[0].warning).toBe("");
    sentence.accept(next, ["Mua"], 8500);
    expect(sentence.prepare(10500, false)?.words).toEqual(["Mua"]);
  });

  it("undo invalidates the pending composition and re-normalizes the remaining words", () => {
    const sentence = new AutomaticSentence();
    sentence.sync(["Mua"], 0);
    sentence.resolve(sentence.prepare(1800, false)!, "Mua.");
    const capture = sentence.activity(6000);
    sentence.finish(capture, 7000);
    sentence.accept(capture, ["Mua", "Tủ lạnh", "Rẻ"], 7500);
    const request = sentence.prepare(9500, false)!;
    sentence.sync(["Mua", "Tủ lạnh"], 10000);
    expect(sentence.resolve(request, "Mua tủ lạnh rẻ.")).toBe(false);
    expect(sentence.prepare(12000, false)?.words).toEqual(["Mua", "Tủ lạnh"]);
  });

});
