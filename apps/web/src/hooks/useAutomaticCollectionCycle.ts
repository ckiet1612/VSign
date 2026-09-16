import { useCallback, useEffect, useRef, useState } from "react";
import type { CaptureStatus } from "./useSignCapture";

export type AutomaticCollectionPhase =
  | "off"
  | "waiting"
  | "preparing"
  | "recording"
  | "processing";

interface AutomaticCollectionCycleOptions {
  enabled: boolean;
  ready: boolean;
  blocked: boolean;
  captureStatus: CaptureStatus;
  onStart: () => void;
  onStop: () => void;
  countdownSeconds?: number;
  recordingMs?: number;
}

export interface AutomaticCollectionCycleController {
  phase: AutomaticCollectionPhase;
  countdown: number | null;
  continueAfterRejectedTake: () => void;
}

const COUNTDOWN_STEP_MS = 850;
const RECOVERY_TIMEOUT_MS = 6_000;

/**
 * Run hands-free, fixed-window collection cycles.
 *
 * A countdown starts before recording, so the beginning of the sign is not
 * lost. A completed sample blocks the next cycle until it has been saved.
 */
export function useAutomaticCollectionCycle({
  enabled,
  ready,
  blocked,
  captureStatus,
  onStart,
  onStop,
  countdownSeconds = 3,
  recordingMs = 2_100,
}: AutomaticCollectionCycleOptions): AutomaticCollectionCycleController {
  const [phase, setPhase] = useState<AutomaticCollectionPhase>("off");
  const [countdown, setCountdown] = useState<number | null>(null);
  const countdownTimerRef = useRef<number | null>(null);
  const stopTimerRef = useRef<number | null>(null);
  const recoveryTimerRef = useRef<number | null>(null);
  const scheduledRef = useRef(false);
  const startRef = useRef(onStart);
  const stopRef = useRef(onStop);
  startRef.current = onStart;
  stopRef.current = onStop;

  const clearTimers = useCallback(() => {
    for (const timer of [
      countdownTimerRef.current,
      stopTimerRef.current,
      recoveryTimerRef.current,
    ]) {
      if (timer !== null) window.clearTimeout(timer);
    }
    countdownTimerRef.current = null;
    stopTimerRef.current = null;
    recoveryTimerRef.current = null;
    scheduledRef.current = false;
  }, []);

  const continueAfterRejectedTake = useCallback(() => {
    if (!enabled) return;
    clearTimers();
    setCountdown(null);
    setPhase("waiting");
  }, [clearTimers, enabled]);

  useEffect(() => {
    if (enabled) return;
    clearTimers();
    setCountdown(null);
    setPhase("off");
  }, [clearTimers, enabled]);

  useEffect(() => {
    if (!enabled) return;
    if (!ready || blocked) {
      if (phase !== "recording" && phase !== "processing") {
        clearTimers();
        setCountdown(null);
        setPhase("waiting");
      }
      return;
    }
    if (captureStatus !== "idle" || scheduledRef.current) return;
    if (phase === "recording" || phase === "processing") return;

    scheduledRef.current = true;
    setPhase("preparing");
    setCountdown(countdownSeconds);
    let remaining = countdownSeconds;
    const tick = () => {
      remaining -= 1;
      if (remaining > 0) {
        setCountdown(remaining);
        countdownTimerRef.current = window.setTimeout(tick, COUNTDOWN_STEP_MS);
        return;
      }
      countdownTimerRef.current = null;
      setCountdown(null);
      setPhase("recording");
      startRef.current();
      stopTimerRef.current = window.setTimeout(() => {
        stopTimerRef.current = null;
        stopRef.current();
        setPhase("processing");
        recoveryTimerRef.current = window.setTimeout(() => {
          recoveryTimerRef.current = null;
          scheduledRef.current = false;
          setPhase("waiting");
        }, RECOVERY_TIMEOUT_MS);
      }, recordingMs);
    };
    countdownTimerRef.current = window.setTimeout(tick, COUNTDOWN_STEP_MS);
  }, [
    blocked,
    captureStatus,
    clearTimers,
    countdownSeconds,
    enabled,
    phase,
    ready,
    recordingMs,
  ]);

  useEffect(() => {
    if (!enabled || !blocked || phase !== "processing") return;
    if (recoveryTimerRef.current !== null) {
      window.clearTimeout(recoveryTimerRef.current);
      recoveryTimerRef.current = null;
    }
    scheduledRef.current = false;
    setPhase("waiting");
  }, [blocked, enabled, phase]);

  useEffect(() => clearTimers, [clearTimers]);

  return { phase, countdown, continueAfterRejectedTake };
}
