import { useCallback, useEffect, useRef, useState } from "react";
import type { InferenceMetadata } from "@contracts";

interface RuntimeHealth {
  status: "ok";
  backend: string;
  model_version: string;
  protocol_version: string;
}

export interface RuntimeSnapshot {
  endpoint: string;
  health: RuntimeHealth | null;
  metadata: InferenceMetadata | null;
  healthError: string;
  metadataError: string;
  checkedAt: number | null;
  lastHealthyAt: number | null;
  metadataUpdatedAt: number | null;
  healthLatencyMs: number | null;
  checking: boolean;
}

export function emptyRuntime(endpoint: string): RuntimeSnapshot {
  return { endpoint, health: null, metadata: null, healthError: "", metadataError: "",
    checkedAt: null, lastHealthyAt: null, metadataUpdatedAt: null, healthLatencyMs: null, checking: false };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function hasIdentity(value: Record<string, unknown>): boolean {
  return ["backend", "model_version", "protocol_version"].every(key =>
    typeof value[key] === "string" && value[key].trim().length > 0);
}

function isHealth(value: unknown): value is RuntimeHealth {
  return isRecord(value) && value.status === "ok" && hasIdentity(value);
}

function isMetadata(value: unknown): value is InferenceMetadata {
  if (!isRecord(value) || !hasIdentity(value)) return false;
  const strings = (item: unknown) => Array.isArray(item) && item.every(label => typeof label === "string" && label.trim().length > 0);
  return ["labels", "collection_labels", "supported_image_formats"].every(key => strings(value[key])) &&
    ["mock", "candidate_labels_unverified", "collection_enabled", "sentence_ai_enabled"].every(key => typeof value[key] === "boolean") &&
    ["frame_count", "frame_width", "frame_height", "collection_target_per_hand"].every(key => Number.isSafeInteger(value[key]) && Number(value[key]) > 0) &&
    ["confidence_threshold", "margin_threshold"].every(key => typeof value[key] === "number" && Number.isFinite(value[key]) && value[key] >= 0 && value[key] <= 1);
}

type ReadResult<T> = { body: T; error: ""; elapsed: number } | { body: null; error: string; elapsed: null };

async function read<T>(url: string, signal: AbortSignal, validate: (body: unknown) => body is T): Promise<ReadResult<T>> {
  const started = performance.now();
  try {
    const response = await fetch(url, { signal, cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const body: unknown = await response.json();
    if (!validate(body)) throw new Error("Phản hồi backend không hợp lệ");
    return { body, error: "", elapsed: performance.now() - started };
  } catch (cause) {
    return { body: null, elapsed: null, error: signal.aborted ? "Hết thời gian chờ backend (5 giây)"
      : cause instanceof TypeError ? "Không thể kết nối backend" : cause instanceof Error ? cause.message : "Không thể đọc backend" };
  }
}

export function useRuntimeStatus(httpUrl: string, enabled: boolean) {
  const endpoint = httpUrl.replace(/\/+$/, "");
  const [snapshot, setSnapshot] = useState(() => emptyRuntime(endpoint));
  const refreshRef = useRef<() => Promise<void>>(async () => undefined);
  const refresh = useCallback(() => refreshRef.current(), []);

  useEffect(() => {
    if (!enabled) return;
    let active = true;
    let controller: AbortController | null = null;
    const check = async () => {
      if (!active || controller) return;
      const request = new AbortController();
      controller = request;
      setSnapshot(current => ({ ...(current.endpoint === endpoint ? current : emptyRuntime(endpoint)), checking: true }));
      const timeout = window.setTimeout(() => request.abort(), 5000);
      try {
        const [health, metadata] = await Promise.all([
          read(`${endpoint}/health`, request.signal, isHealth),
          read(`${endpoint}/metadata`, request.signal, isMetadata),
        ]);
        if (!active) return;
        const checkedAt = Date.now();
        const mismatch = health.body && metadata.body && ["backend", "model_version", "protocol_version"].some(key =>
          health.body![key as keyof RuntimeHealth] !== metadata.body![key as keyof InferenceMetadata]);
        const acceptedMetadata = !mismatch ? metadata.body : null;
        setSnapshot(current => ({
          endpoint,
          health: health.body ?? current.health,
          metadata: acceptedMetadata ?? current.metadata,
          healthError: health.error,
          metadataError: mismatch ? "Health và metadata không khớp runtime" : metadata.error,
          checkedAt,
          lastHealthyAt: health.body ? checkedAt : current.lastHealthyAt,
          metadataUpdatedAt: acceptedMetadata ? checkedAt : current.metadataUpdatedAt,
          healthLatencyMs: health.elapsed,
          checking: false,
        }));
      } finally {
        window.clearTimeout(timeout);
        controller = null;
      }
    };
    refreshRef.current = check;
    void check();
    const checkIfVisible = () => { if (document.visibilityState === "visible") void check(); };
    const interval = window.setInterval(checkIfVisible, 10000);
    document.addEventListener("visibilitychange", checkIfVisible);
    window.addEventListener("focus", checkIfVisible);
    return () => {
      active = false;
      controller?.abort();
      refreshRef.current = async () => undefined;
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", checkIfVisible);
      window.removeEventListener("focus", checkIfVisible);
    };
  }, [enabled, endpoint]);

  const current = snapshot.endpoint === endpoint ? snapshot : emptyRuntime(endpoint);
  return { ...current, checking: enabled && (current.checking || current.checkedAt === null), refresh };
}
