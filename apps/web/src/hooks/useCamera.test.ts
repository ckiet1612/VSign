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
});
