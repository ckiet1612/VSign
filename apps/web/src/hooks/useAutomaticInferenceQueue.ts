import { useCallback, useEffect, useRef, useState } from "react";
import type { PredictionMessage } from "@contracts";
import {
  AutomaticInferenceQueue,
  type AutomaticInferenceJob,
  type AutomaticInferenceTiming,
} from "../lib/automaticInferenceQueue";

interface Options {
  enabled: boolean;
  contextKey: string;
  serverConnected: boolean;
  blocked?: boolean;
  send: (job: AutomaticInferenceJob) => void | Promise<PredictionMessage>;
  onStarted: (sequence: number) => void;
  onPrediction: (prediction: PredictionMessage) => void;
  onError: (message: string) => void;
}

export function useAutomaticInferenceQueue(options: Options) {
  const queueRef = useRef(new AutomaticInferenceQueue<AutomaticInferenceJob>());
  const optionsRef = useRef(options);
  const mountedRef = useRef(true);
  const runningRef = useRef<{ job: AutomaticInferenceJob; contextKey: string } | null>(null);
  const pumpRef = useRef<() => void>(() => undefined);
  const receiveRef = useRef<(prediction: PredictionMessage) => boolean>(() => false);
  const [state, setState] = useState({ waitingCount: 0, busy: false, full: false });
  const [lastTiming, setLastTiming] = useState<AutomaticInferenceTiming | null>(null);
  // Replies to provisional jobs, held until the sign is confirmed (or dropped).
  const heldRef = useRef(new Map<number, { prediction: PredictionMessage; timing: AutomaticInferenceTiming }>());
  const confirmedAtRef = useRef(new Map<number, number>());
  optionsRef.current = options;

  const publish = useCallback(() => {
    if (!mountedRef.current) return;
    const queue = queueRef.current;
    setState({ waitingCount: queue.pendingCount, busy: queue.busy, full: queue.full });
  }, []);

  const receive = useCallback((prediction: PredictionMessage) => {
    const completed = queueRef.current.complete(prediction.sequence, performance.now());
    if (!completed) return false;
    const running = runningRef.current;
    runningRef.current = null;
    const current = optionsRef.current;
    if (
      mountedRef.current && current.enabled && !completed.cancelled &&
      running?.contextKey === current.contextKey
    ) {
      const timing: AutomaticInferenceTiming = {
        ...completed.job.timing, sequence: prediction.sequence,
        queueWaitMs: completed.queueWaitMs, responseMs: completed.responseMs,
      };
      if (completed.job.provisional) {
        heldRef.current.set(prediction.sequence, { prediction, timing });
      } else {
        const confirmedAt = confirmedAtRef.current.get(prediction.sequence);
        confirmedAtRef.current.delete(prediction.sequence);
        setLastTiming(confirmedAt === undefined ? timing
          : { ...timing, resultWaitMs: Math.max(0, performance.now() - confirmedAt) });
        current.onPrediction(prediction);
      }
    }
    publish();
    pumpRef.current();
    return true;
  }, [publish]);
  receiveRef.current = receive;

  const pump = useCallback(() => {
    const current = optionsRef.current;
    if (!mountedRef.current || !current.enabled || current.blocked) return;
    const job = queueRef.current.startNext(performance.now());
    if (!job) return;
    const contextKey = current.contextKey;
    runningRef.current = { job, contextKey };
    publish();
    // A provisional job only becomes a visible request once the sign is confirmed.
    if (!job.provisional) current.onStarted(job.sequence);
    const failed = (error: unknown) => {
      const completed = queueRef.current.complete(job.sequence, performance.now());
      if (!completed) return;
      runningRef.current = null;
      const latest = optionsRef.current;
      if (
        mountedRef.current && latest.enabled && !completed.cancelled &&
        latest.contextKey === contextKey
      ) {
        queueRef.current.cancel();
        latest.onError(error instanceof Error ? error.message : "Không thể xử lý lượt ký hiệu.");
      }
      publish();
      pumpRef.current();
    };
    try {
      const pending = current.send(job);
      if (pending) {
        void pending.then((prediction) => receiveRef.current(prediction)).catch(failed);
      }
    } catch (error) {
      failed(error);
    }
  }, [publish]);
  pumpRef.current = pump;

  useEffect(() => {
    mountedRef.current = true;
    const queue = queueRef.current;
    return () => {
      mountedRef.current = false;
      queue.cancel();
    };
  }, []);

  useEffect(() => {
    queueRef.current.cancel();
    heldRef.current.clear();
    confirmedAtRef.current.clear();
    setLastTiming(null);
    publish();
  }, [options.contextKey, options.enabled, publish]);

  useEffect(() => {
    const running = runningRef.current;
    if (options.serverConnected || running?.job.route !== "server") return;
    // The closed socket can no longer deliver an acknowledgement. Drop its
    // pending clips and allow a different transport (e.g. local fallback).
    queueRef.current.cancel();
    queueRef.current.complete(running.job.sequence, performance.now());
    runningRef.current = null;
    publish();
  }, [options.serverConnected, publish]);

  useEffect(() => {
    if (!options.blocked) pump();
  }, [options.blocked, pump]);

  const enqueue = useCallback((job: AutomaticInferenceJob): boolean => {
    if (!mountedRef.current || !optionsRef.current.enabled) return false;
    if (!queueRef.current.enqueue(job, performance.now())) return false;
    publish();
    pump();
    return true;
  }, [publish, pump]);

  /**
   * The sign ended on the rest its provisional job was cut at. Returns false when that
   * job is gone (e.g. it never fit in the queue); the caller then enqueues normally.
   */
  const confirm = useCallback((sequence: number): boolean => {
    const current = optionsRef.current;
    const held = heldRef.current.get(sequence);
    if (held) {
      heldRef.current.delete(sequence);
      if (!mountedRef.current || !current.enabled) return true;
      current.onStarted(sequence);
      setLastTiming({ ...held.timing, resultWaitMs: 0 });
      current.onPrediction(held.prediction);
      return true;
    }
    const where = queueRef.current.confirm(sequence);
    if (!where) return false;
    const job = where === "running" ? runningRef.current?.job : null;
    if (job) job.provisional = false;
    else queueRef.current.markConfirmed(sequence);
    confirmedAtRef.current.set(sequence, performance.now());
    if (where === "running") current.onStarted(sequence);
    // A confirmed waiting job now counts toward the queue limit.
    publish();
    return true;
  }, [publish]);

  const retract = useCallback((sequence: number) => {
    heldRef.current.delete(sequence);
    confirmedAtRef.current.delete(sequence);
    queueRef.current.retract(sequence);
    publish();
    pumpRef.current();
  }, [publish]);

  const isPending = useCallback(() => queueRef.current.busy || queueRef.current.pendingCount > 0, []);
  return { ...state, lastTiming, enqueue, confirm, retract, receive, isPending };
}
