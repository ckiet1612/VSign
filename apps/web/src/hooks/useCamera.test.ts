import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useCamera } from "./useCamera";

function fakeStream() {
  const track = {
    stop: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  };
  const stream = {
    getTracks: () => [track],
    getVideoTracks: () => [track],
  } as unknown as MediaStream;
  return { stream, track };
}

describe("useCamera", () => {
  it("dừng stream nếu getUserMedia resolve sau unmount", async () => {
    let resolveStream!: (stream: MediaStream) => void;
    const pendingStream = new Promise<MediaStream>((resolve) => {
      resolveStream = resolve;
    });
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn(() => pendingStream) },
    });
    const { stream, track } = fakeStream();
    const videoRef = { current: null };
    const { result, unmount } = renderHook(() => useCamera(videoRef));

    let enablePromise!: Promise<void>;
    act(() => {
      enablePromise = result.current.enable();
    });
    unmount();
    await act(async () => {
      resolveStream(stream);
      await enablePromise;
    });

    expect(track.stop).toHaveBeenCalledOnce();
  });

  it("dừng stream đến muộn sau khi người dùng tắt camera", async () => {
    let resolveStream!: (stream: MediaStream) => void;
    const pendingStream = new Promise<MediaStream>((resolve) => {
      resolveStream = resolve;
    });
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn(() => pendingStream) },
    });
    const { stream, track } = fakeStream();
    const { result } = renderHook(() => useCamera({ current: null }));

    let enablePromise!: Promise<void>;
    act(() => {
      enablePromise = result.current.enable();
      result.current.disable();
    });
    await act(async () => {
      resolveStream(stream);
      await enablePromise;
    });

    expect(track.stop).toHaveBeenCalledOnce();
    expect(result.current.status).toBe("off");
  });

  it("theo dõi video từ xa: chỉ báo sẵn sàng khi khung hình còn chạy", () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "setTimeout", "clearTimeout", "performance", "Date"] });
    try {
      const track = { readyState: "live", muted: false, addEventListener: vi.fn(), removeEventListener: vi.fn() };
      const remote = { getVideoTracks: () => [track], getTracks: () => [track] } as unknown as MediaStream;
      const video = { srcObject: null as MediaStream | null, currentTime: 0, play: vi.fn(async () => undefined) };
      const videoRef = { current: video as unknown as HTMLVideoElement };
      const { result, rerender } = renderHook(({ stream }) => useCamera(videoRef, stream),
        { initialProps: { stream: remote as MediaStream | null } });
      expect(video.srcObject).toBe(remote);
      expect(result.current.status).toBe("requesting");

      video.currentTime = 0.1;
      act(() => { vi.advanceTimersByTime(250); });
      expect(result.current.status).toBe("ready");

      // The picture freezes: after the stall window it must not look live.
      act(() => { vi.advanceTimersByTime(2000); });
      expect(result.current.status).toBe("interrupted");
      expect(result.current.message).toMatch(/Mất video/);

      video.currentTime = 0.5;
      act(() => { vi.advanceTimersByTime(250); });
      expect(result.current.status).toBe("ready");
      track.muted = true;
      act(() => { vi.advanceTimersByTime(250); });
      expect(result.current.status).toBe("interrupted");

      rerender({ stream: null });
      expect(video.srcObject).toBeNull();
      expect(result.current.status).toBe("off");
    } finally {
      vi.useRealTimers();
    }
  });
});
