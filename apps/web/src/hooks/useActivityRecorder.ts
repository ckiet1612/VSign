import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { WorkspaceClientEventRequest } from "@workspace-contracts";

const MAX_PENDING = 200;

export function useActivityRecorder(platformUrl: string, accountId: string | null) {
  const key = `${platformUrl}|${accountId ?? ""}`;
  const scope = useMemo(() => ({ key }), [key]);
  const identity = useRef<typeof scope | null>(scope);
  identity.current = scope;
  const state = useRef({ scope, queue: [] as WorkspaceClientEventRequest[], running: false,
    failed: false, controller: null as AbortController | null });
  const [status, setStatus] = useState({ pending: 0, busy: false, error: "" });
  const [dropped, setDropped] = useState(0);

  useEffect(() => {
    identity.current = scope;
    const current = state.current;
    current.controller?.abort();
    state.current = { scope, queue: [], running: false, failed: false, controller: null };
    setStatus({ pending: 0, busy: false, error: "" });
    setDropped(0);
    return () => { identity.current = null; state.current.controller?.abort(); };
  }, [scope]);

  const drain = useCallback(async () => {
    const current = state.current;
    if (current.scope !== scope || current.running || current.failed || !accountId) return;
    current.running = true;
    while (current.queue.length && identity.current === scope && state.current === current) {
      const payload = current.queue[0];
      const controller = new AbortController();
      current.controller = controller;
      const timeout = window.setTimeout(() => controller.abort(), 8000);
      setStatus({ pending: current.queue.length, busy: true, error: "" });
      try {
        const response = await fetch(`${platformUrl.replace(/\/$/, "")}/api/v1/workspace/audit/client-events`, {
          method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload), signal: controller.signal,
        });
        if (!response.ok) throw new Error(response.status === 401
          ? "Phiên đăng nhập đã hết hạn. Hãy đăng nhập lại để ghi nhật ký."
          : response.status === 403 ? "Tài khoản không có quyền ghi sự kiện này." : "Chưa ghi được nhật ký hoạt động.");
        const body: unknown = await response.json();
        if (!body || typeof body !== "object" || !("status" in body) || body.status !== "recorded" ||
          !("event_id" in body) || body.event_id !== payload.event_id) throw new Error("Phản hồi ghi nhật ký không hợp lệ.");
        if (identity.current !== scope || state.current !== current) return;
        current.queue.shift();
      } catch (error) {
        if (identity.current !== scope || state.current !== current) return;
        current.failed = true;
        setStatus({ pending: current.queue.length, busy: false, error: error instanceof Error && error.name !== "AbortError"
          ? error.message : "Ghi nhật ký quá thời gian chờ." });
        break;
      } finally {
        window.clearTimeout(timeout);
        current.controller = null;
      }
    }
    current.running = false;
    if (identity.current === scope && state.current === current && !current.failed) {
      setStatus({ pending: current.queue.length, busy: false, error: "" });
    }
  }, [accountId, scope, platformUrl]);

  const record = useCallback((payload: WorkspaceClientEventRequest) => {
    const current = state.current;
    if (!accountId || identity.current !== scope || current.scope !== scope) return;
    if (current.queue.length >= MAX_PENDING) {
      setDropped(previous => previous + 1);
      return;
    }
    current.queue.push({ ...payload });
    setStatus(previous => ({ ...previous, pending: current.queue.length }));
    void drain();
  }, [accountId, drain, scope]);
  const retry = useCallback(() => {
    if (state.current.scope !== scope) return;
    state.current.failed = false;
    void drain();
  }, [drain, scope]);
  return { record, retry, dropped, context: scope, ...status };
}
