import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAutomaticSentence } from "./useAutomaticSentence";

describe("automatic sentence coordinator", () => {
  beforeEach(() => { vi.useFakeTimers(); vi.spyOn(performance, "now").mockImplementation(() => Date.now()); });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

  it("retains missing-sign evidence across composition errors and successful retries", async () => {
    const compose = vi.fn<(words: string[], signal: AbortSignal) => Promise<string>>()
      .mockRejectedValueOnce(new Error("Ghép câu lỗi"))
      .mockResolvedValueOnce("Mua sữa.");
    const { result, rerender } = renderHook(({ words }) => useAutomaticSentence({
      enabled: true, contextKey: "server", words, blocked: () => false, compose,
    }), { initialProps: { words: ["Mua"] } });
    act(() => result.current.missing("Có đoạn chưa nhận dạng"));
    await act(async () => vi.advanceTimersByTimeAsync(2000));
    expect(result.current.drafts[0].warning).toBe("Có đoạn chưa nhận dạng");
    expect(result.current.drafts[0].compositionWarning).toBe("Ghép câu lỗi");
    rerender({ words: ["Mua", "Sữa"] });
    await act(async () => vi.advanceTimersByTimeAsync(2000));
    expect(result.current.drafts[0].sentence).toBe("Mua sữa.");
    expect(result.current.drafts[0].warning).toBe("Có đoạn chưa nhận dạng");
    expect(result.current.drafts[0].status).toBe("review");
  });

  it("receives composer warnings without blocking the next sentence", async () => {
    const compose = vi.fn(async () => ({ sentence: "Laptop mới cũ.", warnings: ["Thuộc tính chưa rõ"] }));
    const { result } = renderHook(() => useAutomaticSentence({
      enabled: true, contextKey: "server", words: ["Laptop", "Mới", "Cũ"], blocked: () => false, compose,
    }));
    await act(async () => vi.advanceTimersByTimeAsync(2000));
    expect(result.current.drafts[0].sentence).toBe("Laptop mới cũ.");
    expect(result.current.drafts[0].compositionWarning).toBe("Thuộc tính chưa rõ");
    expect(result.current.drafts[0].status).toBe("review");
    await act(async () => vi.advanceTimersByTimeAsync(6000));
    expect(compose).toHaveBeenCalledOnce();
    let capture!: { id: number };
    act(() => { capture = result.current.activity()!; result.current.finish(capture); });
    act(() => result.current.accept(capture, ["Laptop", "Mới", "Cũ", "Sữa"]));
    await act(async () => vi.advanceTimersByTimeAsync(2000));
    expect(compose).toHaveBeenCalledTimes(2);
  });

  it("waits for inference drain and appends the late Rẻ before composing", async () => {
    let busy = true;
    const compose = vi.fn(async (words: string[]) => words.join(" ") + ".");
    const { result, rerender } = renderHook(({ words }) => useAutomaticSentence({
      enabled: true, contextKey: "server", words, blocked: () => busy, compose,
    }), { initialProps: { words: ["Tôi", "Muốn", "Mua", "Tủ lạnh"] } });
    await act(async () => vi.advanceTimersByTimeAsync(5000));
    expect(compose).not.toHaveBeenCalled();
    rerender({ words: ["Tôi", "Muốn", "Mua", "Tủ lạnh", "Rẻ"] });
    busy = false;
    await act(async () => vi.advanceTimersByTimeAsync(1900));
    expect(compose).toHaveBeenCalledOnce();
    expect(compose.mock.calls[0][0].at(-1)).toBe("Rẻ");
    expect(result.current.drafts[0].status).toBe("draft");
  });

  it("aborts stale composition when signing resumes and never displays its reply", async () => {
    let resolve!: (sentence: string) => void;
    const compose = vi.fn<(words: string[], signal: AbortSignal) => Promise<string>>(() => new Promise<string>(yes => { resolve = yes; }));
    const { result, rerender } = renderHook(({ words }) => useAutomaticSentence({
      enabled: true, contextKey: "server", words, blocked: () => false, compose,
    }), { initialProps: { words: ["Tôi", "Muốn", "Mua", "Tủ lạnh"] } });
    await act(async () => vi.advanceTimersByTimeAsync(1900));
    const signal = compose.mock.calls[0][1];
    act(() => result.current.activity());
    expect(signal.aborted).toBe(true);
    rerender({ words: ["Tôi", "Muốn", "Mua", "Tủ lạnh", "Rẻ"] });
    await act(async () => resolve("Tôi muốn mua tủ lạnh."));
    expect(result.current.drafts[0].sentence).toBe("");
    expect(result.current.drafts[0].words.at(-1)).toBe("Rẻ");
  });

  it("composes recognized words after model uncertainty and keeps the review warning", async () => {
    const compose = vi.fn(async () => "Mua.");
    const { result } = renderHook(() => useAutomaticSentence({
      enabled: true, contextKey: "server", words: ["Mua"], blocked: () => false, compose,
    }));
    act(() => result.current.missing("Có đoạn chưa nhận dạng"));
    await act(async () => vi.advanceTimersByTimeAsync(2000));
    expect(compose).toHaveBeenCalledOnce();
    expect(result.current.drafts[0].warning).toBe("Có đoạn chưa nhận dạng");
    expect(result.current.drafts[0].sentence).toBe("Mua.");
    expect(result.current.drafts[0].status).toBe("review");
  });

  it("disables automatic composition in manual/collection mode and discards old replies on clear", async () => {
    let resolve!: (sentence: string) => void;
    const compose = vi.fn(() => new Promise<string>(yes => { resolve = yes; }));
    const { result, rerender } = renderHook(({ enabled, words }) => useAutomaticSentence({
      enabled, contextKey: "server", words, blocked: () => false, compose,
    }), { initialProps: { enabled: false, words: ["Mua"] } });
    await act(async () => vi.advanceTimersByTimeAsync(5000));
    expect(compose).not.toHaveBeenCalled();
    rerender({ enabled: true, words: ["Mua"] });
    await act(async () => vi.advanceTimersByTimeAsync(1900));
    rerender({ enabled: true, words: [] });
    await act(async () => resolve("Mua."));
    expect(result.current.drafts).toEqual([]);
  });

  it("does not erase a missing segment on camera/transport context change", async () => {
    const compose = vi.fn(async () => "Mua.");
    const { result, rerender } = renderHook(({ contextKey }) => useAutomaticSentence({
      enabled: true, contextKey, words: ["Mua"], blocked: () => false, compose,
    }), { initialProps: { contextKey: "server" } });
    act(() => result.current.missing("Có đoạn chưa nhận dạng"));
    rerender({ contextKey: "local" });
    await act(async () => vi.advanceTimersByTimeAsync(5000));
    expect(compose).not.toHaveBeenCalled();
    expect(result.current.drafts[0].status).toBe("review");
  });

  it("continues the same sentence when recognition pauses and resumes on the same model", async () => {
    const compose = vi.fn(async (words: string[]) => words.join(" ") + ".");
    const { result, rerender } = renderHook(({ enabled, words }) => useAutomaticSentence({
      enabled, contextKey: "recognize:v1", words, blocked: () => false, compose,
    }), { initialProps: { enabled: true, words: ["Mua"] } });
    let pending!: NonNullable<ReturnType<typeof result.current.activity>>;
    act(() => { pending = result.current.activity()!; });
    rerender({ enabled: false, words: ["Mua"] });
    rerender({ enabled: true, words: ["Mua"] });
    act(() => result.current.accept(pending, ["Mua", "Rẻ"]));
    rerender({ enabled: true, words: ["Mua", "Tivi"] });
    await act(async () => vi.advanceTimersByTimeAsync(2000));
    expect(result.current.drafts).toHaveLength(1);
    expect(result.current.drafts[0].words).toEqual(["Mua", "Tivi"]);
    expect(result.current.drafts[0].sentence).toBe("Mua Tivi.");
    expect(result.current.drafts[0].warning).toBe("Có đoạn ký bị gián đoạn · cần kiểm tra");
  });

  it("recomposes a sentence whose composition was cut off by a pause", async () => {
    const compose = vi.fn<(words: string[], signal: AbortSignal) => Promise<string>>()
      .mockImplementationOnce(() => new Promise(() => undefined))
      .mockResolvedValueOnce("Mua sữa.");
    const { result, rerender } = renderHook(({ enabled }) => useAutomaticSentence({
      enabled, contextKey: "recognize:v1", words: ["Mua", "Sữa"], blocked: () => false, compose,
    }), { initialProps: { enabled: true } });
    await act(async () => vi.advanceTimersByTimeAsync(2000));
    expect(result.current.drafts[0].status).toBe("composing");
    rerender({ enabled: false });
    rerender({ enabled: true });
    await act(async () => vi.advanceTimersByTimeAsync(2000));
    expect(compose).toHaveBeenCalledTimes(2);
    expect(result.current.drafts).toHaveLength(1);
    expect(result.current.drafts[0].sentence).toBe("Mua sữa.");
  });

  it("can reset a session containing only an unrecognized segment and no words", () => {
    const { result } = renderHook(() => useAutomaticSentence({
      enabled: true, contextKey: "server", words: [], blocked: () => false, compose: vi.fn(),
    }));
    act(() => result.current.missing("Có đoạn chưa nhận dạng"));
    expect(result.current.drafts).toHaveLength(1);
    act(() => result.current.reset());
    expect(result.current.drafts).toEqual([]);
  });

  it("times out a stalled composition and retains the raw words for review", async () => {
    const compose = vi.fn<(words: string[], signal: AbortSignal) => Promise<string>>(() => new Promise(() => {}));
    const { result } = renderHook(() => useAutomaticSentence({
      enabled: true, contextKey: "server", words: ["Mua"], blocked: () => false, compose,
    }));
    await act(async () => vi.advanceTimersByTimeAsync(25000));
    expect(result.current.drafts[0].status).toBe("review");
    expect(result.current.drafts[0].words).toEqual(["Mua"]);
    expect(compose).toHaveBeenCalledOnce();
    expect(compose.mock.calls[0][1].aborted).toBe(true);
  });

  it("recomposes every word after signing resumes instead of starting a new sentence", async () => {
    let capturing = false;
    const compose = vi.fn<(words: string[], signal: AbortSignal) => Promise<string>>()
      .mockImplementationOnce(() => new Promise(() => {}))
      .mockResolvedValueOnce("Mua tủ lạnh.");
    const { result, rerender } = renderHook(({ words }) => useAutomaticSentence({
      enabled: true, contextKey: "server", words, blocked: () => capturing, compose,
    }), { initialProps: { words: ["Mua"] } });
    await act(async () => vi.advanceTimersByTimeAsync(6100));
    capturing = true;
    let capture!: NonNullable<ReturnType<typeof result.current.activity>>;
    act(() => { capture = result.current.activity()!; });
    expect(compose.mock.calls[0][1].aborted).toBe(true);
    act(() => {
      result.current.finish(capture);
      result.current.accept(capture, ["Mua", "Tủ lạnh"]);
    });
    rerender({ words: ["Mua", "Tủ lạnh"] });
    capturing = false;
    await act(async () => vi.advanceTimersByTimeAsync(2000));
    expect(compose.mock.calls[1][0]).toEqual(["Mua", "Tủ lạnh"]);
    expect(result.current.drafts.map(item => item.sentence)).toEqual(["Mua tủ lạnh."]);
  });

  it("does not let a timed-out composition block later recompositions forever", async () => {
    const compose = vi.fn<(words: string[], signal: AbortSignal) => Promise<string>>()
      .mockImplementationOnce(() => new Promise(() => {}))
      .mockResolvedValueOnce("Mua tủ lạnh.");
    const { result, rerender } = renderHook(({ words }) => useAutomaticSentence({
      enabled: true, contextKey: "server", words, blocked: () => false, compose,
    }), { initialProps: { words: ["Mua"] } });
    await act(async () => vi.advanceTimersByTimeAsync(22000));
    expect(result.current.drafts[0].compositionWarning).toBe("Ghép câu quá thời gian · cần kiểm tra");
    act(() => {
      const capture = result.current.activity()!;
      result.current.finish(capture);
      result.current.accept(capture, ["Mua", "Tủ lạnh"]);
    });
    rerender({ words: ["Mua", "Tủ lạnh"] });
    await act(async () => vi.advanceTimersByTimeAsync(2000));
    expect(result.current.drafts.map(item => item.status)).toEqual(["draft"]);
    expect(result.current.drafts[0].sentence).toBe("Mua tủ lạnh.");
  });

  it("cancels a wordless capture on context change and recovers without a clear action", async () => {
    const compose = vi.fn(async (words: string[]) => words.join(" ") + ".");
    const { result, rerender } = renderHook(({ contextKey, words }) => useAutomaticSentence({
      enabled: true, contextKey, words, blocked: () => false, compose,
    }), { initialProps: { contextKey: "server", words: [] as string[] } });
    let old!: NonNullable<ReturnType<typeof result.current.activity>>;
    act(() => { old = result.current.activity()!; });
    rerender({ contextKey: "local", words: [] });
    act(() => result.current.accept(old, ["Mua"]));
    expect(result.current.drafts[0].words).toEqual([]);
    act(() => {
      const capture = result.current.activity()!;
      result.current.finish(capture);
      result.current.accept(capture, ["Tủ lạnh"]);
    });
    rerender({ contextKey: "local", words: ["Tủ lạnh"] });
    await act(async () => vi.advanceTimersByTimeAsync(2000));
    expect(result.current.drafts[0].warning).not.toBe("");
    expect(result.current.drafts[1].sentence).toBe("Tủ lạnh.");
  });
});
