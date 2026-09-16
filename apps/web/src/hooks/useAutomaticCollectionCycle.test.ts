import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAutomaticCollectionCycle } from "./useAutomaticCollectionCycle";

describe("useAutomaticCollectionCycle", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("counts down, records once, then waits while the sample is blocked", () => {
    const onStart = vi.fn();
    const onStop = vi.fn();
    const { result, rerender } = renderHook(
      ({ blocked }) =>
        useAutomaticCollectionCycle({
          enabled: true,
          ready: true,
          blocked,
          captureStatus: "idle",
          onStart,
          onStop,
        }),
      { initialProps: { blocked: false } },
    );

    expect(result.current.phase).toBe("preparing");
    expect(result.current.countdown).toBe(3);
    act(() => vi.advanceTimersByTime(2_550));
    expect(onStart).toHaveBeenCalledTimes(1);
    expect(result.current.phase).toBe("recording");
    act(() => vi.advanceTimersByTime(2_100));
    expect(onStop).toHaveBeenCalledTimes(1);
    expect(result.current.phase).toBe("processing");

    rerender({ blocked: true });
    expect(result.current.phase).toBe("waiting");
    act(() => vi.advanceTimersByTime(10_000));
    expect(onStart).toHaveBeenCalledTimes(1);
  });

  it("cancels a pending countdown when automatic collection is disabled", () => {
    const onStart = vi.fn();
    const { result, rerender } = renderHook(
      ({ enabled }) =>
        useAutomaticCollectionCycle({
          enabled,
          ready: true,
          blocked: false,
          captureStatus: "idle",
          onStart,
          onStop: vi.fn(),
        }),
      { initialProps: { enabled: true } },
    );
    rerender({ enabled: false });
    expect(result.current.phase).toBe("off");
    act(() => vi.advanceTimersByTime(10_000));
    expect(onStart).not.toHaveBeenCalled();
  });
});
