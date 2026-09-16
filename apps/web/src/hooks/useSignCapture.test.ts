import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useSignCapture } from "./useSignCapture";

describe("useSignCapture cancellation", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

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
});
