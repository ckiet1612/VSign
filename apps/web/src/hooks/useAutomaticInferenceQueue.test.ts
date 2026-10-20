import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { PredictionMessage } from "@contracts";
import type { AutomaticInferenceJob } from "../lib/automaticInferenceQueue";
import { useAutomaticInferenceQueue } from "./useAutomaticInferenceQueue";

function job(sequence: number): AutomaticInferenceJob {
  return {
    sequence, capturedAt: 1000 + sequence,
    landmarkFrames: [], baselineLandmarkFrames: [],
    rgbFrames: new Array(16).fill("data:image/webp;base64,AAAA"),
    timing: { captureMs: 2100, encodeMs: 15 },
    route: "server",
  };
}

function reply(sequence: number): PredictionMessage {
  return {
    type: "prediction", sequence, status: "ok", label: "Chào", confidence: 0.9,
    top_k: [{ label: "Chào", confidence: 0.9 }], model_version: "test-v3",
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

describe("automatic inference queue lifecycle", () => {
  function mount(send = vi.fn<(_: AutomaticInferenceJob) => void | Promise<PredictionMessage>>()) {
    const onStarted = vi.fn();
    const onPrediction = vi.fn();
    const onError = vi.fn();
    const hook = renderHook(
      ({ enabled, contextKey, serverConnected, blocked = false }) => useAutomaticInferenceQueue({
        enabled, contextKey, serverConnected, blocked, send, onStarted, onPrediction, onError,
      }),
      { initialProps: { enabled: true, contextKey: "server", serverConnected: true, blocked: false } },
    );
    return { ...hook, send, onStarted, onPrediction, onError };
  }

  it("giữ FIFO, công bố đầy và đo timing theo reply khớp", () => {
    const clock = vi.spyOn(performance, "now").mockReturnValue(100);
    const { result, send } = mount();
    act(() => { result.current.enqueue(job(0)); result.current.enqueue(job(1)); result.current.enqueue(job(2)); });
    expect(result.current.waitingCount).toBe(2);
    expect(result.current.full).toBe(true);
    expect(send).toHaveBeenCalledOnce();
    clock.mockReturnValue(600);
    act(() => { expect(result.current.receive(reply(0))).toBe(true); });
    expect(result.current.waitingCount).toBe(1);
    expect(result.current.lastTiming).toEqual({
      sequence: 0, captureMs: 2100, encodeMs: 15, queueWaitMs: 0, responseMs: 500,
    });
    expect(send.mock.calls[1][0].sequence).toBe(1);
    clock.mockRestore();
  });

  it("đổi context bỏ lượt chờ và bỏ reply cũ nhưng vẫn drain slot", () => {
    const { result, rerender, send, onPrediction } = mount();
    act(() => { result.current.enqueue(job(0)); result.current.enqueue(job(1)); });
    rerender({ enabled: false, contextKey: "manual", serverConnected: true, blocked: false });
    expect(result.current.waitingCount).toBe(0);
    expect(result.current.busy).toBe(true);
    act(() => result.current.receive(reply(0)));
    expect(onPrediction).not.toHaveBeenCalled();
    expect(result.current.busy).toBe(false);
    expect(send).toHaveBeenCalledOnce();
  });

  it("local promise cũng chỉ chạy từng lượt, bỏ kết quả sau hủy", async () => {
    const pending = deferred<PredictionMessage>();
    const send = vi.fn().mockReturnValueOnce(pending.promise);
    const { result, rerender, onPrediction } = mount(send);
    act(() => {
      result.current.enqueue({ ...job(0), route: "local" });
      result.current.enqueue({ ...job(1), route: "local" });
    });
    expect(send).toHaveBeenCalledOnce();
    rerender({ enabled: false, contextKey: "off", serverConnected: false, blocked: false });
    expect(result.current.busy).toBe(true);
    await act(async () => pending.resolve(reply(0)));
    expect(result.current.busy).toBe(false);
    expect(send).toHaveBeenCalledOnce();
    expect(onPrediction).not.toHaveBeenCalled();
  });

  it("socket đóng giải phóng lượt server mất reply để fallback local hoạt động", () => {
    const { result, rerender, onPrediction } = mount();
    act(() => { result.current.enqueue(job(0)); result.current.enqueue(job(1)); });
    rerender({ enabled: true, contextKey: "local", serverConnected: false, blocked: false });
    expect(result.current.busy).toBe(false);
    expect(result.current.waitingCount).toBe(0);
    act(() => { expect(result.current.receive(reply(0))).toBe(false); });
    expect(onPrediction).not.toHaveBeenCalled();
  });

  it("lỗi submit được báo, giải phóng slot và hủy các lượt chờ", async () => {
    const pending = deferred<PredictionMessage>();
    const { result, onError } = mount(vi.fn().mockReturnValueOnce(pending.promise));
    act(() => { result.current.enqueue(job(0)); result.current.enqueue(job(1)); });
    await act(async () => pending.reject(new Error("Inference failed")));
    expect(onError).toHaveBeenCalledWith("Inference failed");
    expect(result.current.busy).toBe(false);
    expect(result.current.waitingCount).toBe(0);
  });

  it("không gửi khi disabled và không cập nhật sau unmount", async () => {
    const pending = deferred<PredictionMessage>();
    const { result, rerender, unmount, send, onPrediction } = mount(vi.fn().mockReturnValueOnce(pending.promise));
    rerender({ enabled: false, contextKey: "off", serverConnected: true, blocked: false });
    act(() => { expect(result.current.enqueue(job(0))).toBe(false); });
    expect(send).not.toHaveBeenCalled();
    rerender({ enabled: true, contextKey: "server", serverConnected: true, blocked: false });
    act(() => result.current.enqueue(job(1)));
    unmount();
    await act(async () => pending.resolve(reply(1)));
    expect(onPrediction).not.toHaveBeenCalled();
  });

  it("đợi lượt thủ công đang chạy trước khi gửi clip tự động", () => {
    const { result, rerender, send } = mount();
    rerender({ enabled: true, contextKey: "server", serverConnected: true, blocked: true });
    act(() => result.current.enqueue(job(1)));
    expect(send).not.toHaveBeenCalled();
    expect(result.current.waitingCount).toBe(1);
    rerender({ enabled: true, contextKey: "server", serverConnected: true, blocked: false });
    expect(send).toHaveBeenCalledOnce();
    expect(result.current.busy).toBe(true);
  });
});
