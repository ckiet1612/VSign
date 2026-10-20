import { useCallback, useEffect, useRef, useState } from "react";
import type { CapturedFrames } from "../hooks/useSignCapture";
import type { Runtime, Summary, TestContext, TestPayload, Trial } from "./types";

class RequestError extends Error {
  readonly status: number;
  constructor(message: string, status: number) { super(message); this.status = status; }
}

export async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new RequestError(typeof detail?.detail === "string" ? detail.detail : `HTTP ${response.status}`, response.status);
  }
  return response.json() as Promise<T>;
}

export function useManualTests(base: string, sessionId: string) {
  const [runtime, setRuntime] = useState<Runtime | null>(null);
  const [trials, setTrials] = useState<Trial[]>([]);
  const [summary, setSummary] = useState<Summary>({ groups: [], recorded: 0, independent_evaluation: false });
  const [pending, setPending] = useState<TestPayload | null>(null);
  const [rejected, setRejected] = useState(false);
  const [lastTrial, setLastTrial] = useState<Trial | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const busyRef = useRef(false);
  const mounted = useRef(true);
  const api = `${base.replace(/\/$/, "")}/dev-tests`;
  const endpoint = useRef({ api, generation: 0 });
  if (endpoint.current.api !== api) endpoint.current = { api, generation: endpoint.current.generation + 1 };
  const generation = endpoint.current.generation;
  const isActive = useCallback(() => mounted.current && endpoint.current.generation === generation, [generation]);

  const refresh = useCallback(async () => {
    const [rows, stats] = await Promise.all([
      requestJson<{ trials: Trial[] }>(`${api}/trials`), requestJson<Summary>(`${api}/summary`),
    ]);
    if (isActive()) { setTrials(rows.trials); setSummary(stats); }
  }, [api, isActive]);

  useEffect(() => {
    mounted.current = true;
    setRuntime(null); setTrials([]); setLastTrial(null);
    setSummary({ groups: [], recorded: 0, independent_evaluation: false });
    setNotice("");
    let disposed = false;
    void requestJson<Runtime>(`${api}/config`).then(async value => {
      if (disposed) return;
      if (!value.enabled) throw new Error("Backend chưa bật chế độ test");
      setRuntime(value);
      await refresh();
    }).catch(error => { if (!disposed) setNotice(`Chưa kết nối được chế độ test: ${String(error)}`); });
    return () => { disposed = true; mounted.current = false; };
  }, [api, refresh]);

  const submit = useCallback(async (payload: TestPayload) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true); setPending(payload); setRejected(false); setNotice("");
    try {
      const saved = await requestJson<Trial>(`${api}/trials`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload), signal: AbortSignal.timeout(60_000) });
      if (!isActive()) return;
      setPending(null); setLastTrial(saved);
      try { await refresh(); if (isActive()) setNotice("Lượt test đã lưu."); }
      catch { if (isActive()) setNotice("Lượt test đã lưu; chưa tải lại được thống kê."); }
    } catch (error) {
      if (isActive()) {
        setRejected(error instanceof RequestError && [409, 422].includes(error.status));
        setNotice(`Lượt test chưa được xác nhận lưu. ${String(error)}`);
      }
    } finally {
      busyRef.current = false;
      if (isActive()) setBusy(false);
    }
  }, [api, refresh, isActive]);

  const createPayload = useCallback((context: TestContext, capturedAt: number): TestPayload => {
    if (!runtime) throw new Error("Backend chưa sẵn sàng");
    return { ...context, trial_id: crypto.randomUUID(), session_id: sessionId, captured_at: capturedAt,
      frames: [], source_frames: [], duration_ms: 0, runtime_key: runtime.runtime_key,
      pipeline: "manual-server-uniform-center-square-v1" };
  }, [runtime, sessionId]);

  const saveCapture = useCallback(async (context: TestContext, captured: CapturedFrames, capturedAt: number) => {
    if (pending || busyRef.current) return;
    const source = captured.sourceFrames;
    if (captured.frames.length !== 16 || !source || source.length < 8 || source.length > 42 || captured.durationMs < 650 || captured.durationMs > 3150) {
      await submit({ ...createPayload(context, capturedAt), technical_error: "Clip camera thiếu frame hoặc thời lượng không hợp lệ" });
      return;
    }
    await submit({ ...createPayload(context, capturedAt), duration_ms: captured.durationMs,
      frames: captured.frames, source_frames: source });
  }, [createPayload, pending, submit]);
  const saveFailure = useCallback(async (context: TestContext, message: string, capturedAt: number) => {
    if (pending || busyRef.current) return;
    await submit({ ...createPayload(context, capturedAt), technical_error: message.slice(0, 300) });
  }, [createPayload, pending, submit]);
  const retry = useCallback(async () => { if (pending) await submit(pending); }, [pending, submit]);

  const review = useCallback(async (trialId: string, valid: boolean, notes: string, reviewer: string) => {
    try {
      await requestJson(`${api}/trials/${trialId}/review`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ valid, notes, reviewer }) });
      if (!isActive()) return false;
      try { await refresh(); if (isActive()) setNotice("Đã lưu kiểm định clip."); }
      catch { if (isActive()) setNotice("Đã lưu kiểm định; chưa tải lại được thống kê."); }
      return true;
    } catch (error) { if (isActive()) setNotice(`Chưa lưu được kiểm định: ${String(error)}`); return false; }
  }, [api, refresh, isActive]);

  const reload = useCallback(async () => {
    try {
      const current = await requestJson<Runtime>(`${api}/config`);
      if (!current.enabled) throw new Error("Backend chưa bật chế độ test");
      if (!isActive()) return;
      setRuntime(current);
      await refresh(); if (isActive()) setNotice("Đã tải lại kết quả và cấu hình.");
    }
    catch (error) { if (isActive()) setNotice(`Chưa tải lại được kết quả: ${String(error)}`); }
  }, [api, refresh, isActive]);

  const discardRejected = useCallback(() => {
    if (rejected && !busyRef.current) {
      setPending(null); setRejected(false); setNotice("Đã bỏ lượt bị backend từ chối; chưa ghi kết quả cho lượt này.");
    }
  }, [rejected]);

  return { runtime, trials, summary, pending, rejected, busy, notice, lastTrial, saveCapture, saveFailure, retry, review, reload, discardRejected, api };
}
