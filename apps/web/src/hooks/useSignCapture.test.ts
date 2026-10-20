import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { encodeFrames } from "../lib/frameEncoder";
import { framingFrame } from "../lib/bodyFraming";
import { useSignCapture } from "./useSignCapture";

const encoder = vi.hoisted(() => ({ encode: vi.fn(), dispose: vi.fn() }));
vi.mock("../lib/frameEncoder", () => ({
  encodeFrames: vi.fn(),
  createStreamingEncoder: () => encoder,
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

describe("useSignCapture cancellation", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(encodeFrames).mockReset();
    encoder.encode.mockReset();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("stream: crop theo khung chốt lúc bắt đầu, encode từng frame khi đang ký và cắt đoạn tay giơ lên", async () => {
    let captured = 0;
    vi.stubGlobal("createImageBitmap", vi.fn(async () => ({ id: captured++, close: vi.fn() })));
    encoder.encode.mockImplementation(async (frame: { bitmap: ImageBitmap & { id: number } }) => `frame-${frame.bitmap.id}`);
    const context = { fillRect: vi.fn(), drawImage: vi.fn(), fillStyle: "", imageSmoothingEnabled: false, imageSmoothingQuality: "low" };
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(context as unknown as CanvasRenderingContext2D);
    const pose = Array.from({ length: 33 }, (_, index) => ({
      x: index === 11 ? 0.6 : index === 12 ? 0.4 : 0.5, y: 0.45, visibility: index === 15 || index === 16 ? 0.1 : 0.99,
    }));
    let calls = 0;
    const getFramingFrame = () => {
      const raised = calls >= 10 && calls <= 20;
      calls += 1;
      return framingFrame(0, raised ? [[{ x: 0.5, y: 0.5 }]] : [], pose);
    };
    const box = { x: 0.24, y: -47.2 / 720, width: 0.52, height: 665.6 / 720 };
    const getBodyBox = vi.fn(() => box);
    const onFrames = vi.fn();
    const video = { readyState: HTMLMediaElement.HAVE_CURRENT_DATA, videoWidth: 1280, videoHeight: 720 } as HTMLVideoElement;
    const { result } = renderHook(() => useSignCapture({
      videoRef: { current: video }, canStart: true, streamFrames: true, bodyFraming: true, getFramingFrame, getBodyBox,
      onCaptureStart: vi.fn(), onCaptureCancel: vi.fn(), onTooShort: vi.fn(), onFrames, onError: vi.fn(),
    }));
    act(() => result.current.start());
    await act(async () => { await vi.advanceTimersByTimeAsync(30 * 75 - 1); });
    // Every frame is already with the encoder before the sign ends.
    expect(encoder.encode).toHaveBeenCalledTimes(30);
    expect(encodeFrames).not.toHaveBeenCalled();
    await act(async () => { result.current.stop(); await vi.runOnlyPendingTimersAsync(); });

    expect(calls).toBe(30);
    expect(getBodyBox).toHaveBeenCalledOnce();
    const [source, sx, sy, sw, sh] = context.drawImage.mock.calls[0];
    expect(source).toBe(video);
    expect([sy, sx]).toEqual([0, expect.closeTo(307.2, 6)]);
    expect(sw).toBeCloseTo(665.6, 6);
    expect(sh).toBeCloseTo(618.4, 6);
    expect(onFrames).toHaveBeenCalledOnce();
    const frames = onFrames.mock.calls[0][0].frames as string[];
    expect(frames).toHaveLength(16);
    // Raised hands on frames 10..20 (75 ms apart), padded by 100 ms -> frames 9..21.
    const ids = [...new Set(frames.map((frame) => Number(frame.split("-")[1])))];
    expect(ids).toEqual(Array.from({ length: 13 }, (_, index) => 9 + index));
  });

  it("reset local state và báo reducer khi capture bị hủy", () => {
    const onCaptureCancel = vi.fn();
    const { result } = renderHook(() =>
      useSignCapture({
        videoRef: { current: null },
        canStart: true,
        onCaptureStart: vi.fn(),
        onCaptureCancel,
        onTooShort: vi.fn(),
        onFrames: vi.fn(),
        onError: vi.fn(),
      }),
    );

    act(() => result.current.start());
    expect(result.current.status).toBe("capturing");
    act(() => result.current.cancel());

    expect(result.current.status).toBe("idle");
    expect(onCaptureCancel).toHaveBeenCalledOnce();
  });

  it("hủy lượt đang thu khi route hoặc pipeline capture thay đổi", () => {
    const onCaptureCancel = vi.fn();
    const { result, rerender } = renderHook(
      ({ captureContextKey }) =>
        useSignCapture({
          videoRef: { current: null },
          canStart: true,
          captureContextKey,
          onCaptureStart: vi.fn(),
          onCaptureCancel,
          onTooShort: vi.fn(),
          onFrames: vi.fn(),
          onError: vi.fn(),
        }),
      { initialProps: { captureContextKey: "recognize:server:uniform:fixed" } },
    );

    act(() => result.current.start());
    expect(result.current.status).toBe("capturing");
    act(() =>
      rerender({ captureContextKey: "recognize:local:motion-weighted:adaptive" }),
    );

    expect(result.current.status).toBe("idle");
    expect(onCaptureCancel).toHaveBeenCalledOnce();
  });

  it("loại frame cũ hoàn tất sau khi một lượt mới đã bắt đầu", async () => {
    const pendingBitmap = deferred<ImageBitmap>();
    const staleBitmap = { close: vi.fn() } as unknown as ImageBitmap;
    vi.stubGlobal("createImageBitmap", vi.fn(() => pendingBitmap.promise));
    const video = {
      readyState: HTMLMediaElement.HAVE_CURRENT_DATA,
    } as HTMLVideoElement;
    const { result } = renderHook(() =>
      useSignCapture({
        videoRef: { current: video },
        canStart: true,
        onCaptureStart: vi.fn(),
        onCaptureCancel: vi.fn(),
        onTooShort: vi.fn(),
        onFrames: vi.fn(),
        onError: vi.fn(),
      }),
    );

    act(() => result.current.start());
    act(() => result.current.cancel());
    act(() => result.current.start());
    await act(async () => {
      pendingBitmap.resolve(staleBitmap);
      await pendingBitmap.promise;
    });

    expect(staleBitmap.close).toHaveBeenCalledOnce();
    act(() => result.current.cancel());
  });

  it("không để encode cũ callback hoặc reset lượt capture mới", async () => {
    const pendingEncode = deferred<string[]>();
    const firstBitmap = { close: vi.fn() } as unknown as ImageBitmap;
    const secondBitmap = { close: vi.fn() } as unknown as ImageBitmap;
    vi.stubGlobal(
      "createImageBitmap",
      vi.fn()
        .mockResolvedValueOnce(firstBitmap)
        .mockResolvedValueOnce(secondBitmap),
    );
    vi.mocked(encodeFrames).mockReturnValueOnce(pendingEncode.promise);
    vi.spyOn(performance, "now").mockReturnValueOnce(0).mockReturnValue(700);
    const video = {
      readyState: HTMLMediaElement.HAVE_CURRENT_DATA,
    } as HTMLVideoElement;
    const onFrames = vi.fn();
    const { result, rerender } = renderHook(
      ({ captureContextKey }) =>
        useSignCapture({
          videoRef: { current: video },
          canStart: true,
          captureContextKey,
          onCaptureStart: vi.fn(),
          onCaptureCancel: vi.fn(),
          onTooShort: vi.fn(),
          onFrames,
          onError: vi.fn(),
        }),
      { initialProps: { captureContextKey: "recognize:server:uniform:fixed" } },
    );

    act(() => result.current.start());
    await act(async () => Promise.resolve());
    act(() => result.current.stop());
    expect(result.current.status).toBe("encoding");

    act(() =>
      rerender({ captureContextKey: "recognize:local:motion-weighted:adaptive" }),
    );
    expect(result.current.status).toBe("idle");
    act(() => result.current.start());
    expect(result.current.status).toBe("capturing");

    await act(async () => {
      pendingEncode.resolve(["encoded-frame"]);
      await pendingEncode.promise;
    });

    expect(onFrames).not.toHaveBeenCalled();
    expect(result.current.status).toBe("capturing");
    act(() => result.current.cancel());
  });
});
