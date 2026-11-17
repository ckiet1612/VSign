import { useCallback, useEffect, useRef, useState } from "react";

const POLL_MS = 10_000;

interface Scope {
  key: string;
  controller: AbortController;
  revision: number;
  reading: boolean;
  saving: boolean;
}

interface Snapshot {
  key: string;
  enabled: boolean | null;
  supported: boolean;
  error: string | null;
}

async function enabledFrom(response: Response): Promise<boolean> {
  if (!response.ok) throw new Error("Modal policy unavailable");
  const body = await response.json() as { enabled?: unknown };
  if (typeof body?.enabled !== "boolean") throw new Error("Invalid Modal policy");
  return body.enabled;
}

export function useModalGpuPolicy(platformUrl: string, sessionKey: string | null) {
  const key = sessionKey === null ? null : `${platformUrl}|${sessionKey}`;
  const url = `${platformUrl}/api/v1/inference/modal-policy`;
  const scopeRef = useRef<Scope | null>(null);
  const [state, setState] = useState<Snapshot | null>(null);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const current = key === state?.key ? state : null;

  useEffect(() => {
    if (key === null) return;
    const scope: Scope = { key, controller: new AbortController(), revision: 0, reading: false, saving: false };
    scopeRef.current = scope;
    const { signal } = scope.controller;
    const refresh = async () => {
      if (scope.reading || scope.saving) return;
      scope.reading = true;
      const revision = scope.revision;
      const isCurrent = () => !signal.aborted && revision === scope.revision;
      try {
        const response = await fetch(url, { method: "GET", credentials: "include", cache: "no-store", signal });
        if (response.status === 404) {
          // Keep recognition compatible while the frontend and platform are updated separately.
          if (isCurrent()) setState(previous => ({ key, enabled: previous?.key === key ? previous.enabled : true,
            supported: false, error: null }));
        } else {
          const enabled = await enabledFrom(response);
          if (isCurrent()) setState({ key, enabled, supported: true, error: null });
        }
      } catch {
        if (isCurrent()) setState(previous => ({ key, enabled: previous?.key === key ? previous.enabled : null,
          supported: previous?.key === key ? previous.supported : true, error: "Không đọc được trạng thái GPU Modal." }));
      } finally {
        scope.reading = false;
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    return () => {
      window.clearInterval(timer);
      scope.controller.abort();
      if (scopeRef.current === scope) scopeRef.current = null;
    };
  }, [key, url]);

  const setEnabled = useCallback(async (next: boolean) => {
    const scope = scopeRef.current;
    if (key === null || !scope || scope.key !== key || scope.saving || !current?.supported || current.enabled === null) return;
    scope.saving = true;
    // Ignore an older GET even if it finishes after this write.
    scope.revision += 1;
    setSavingKey(key);
    try {
      const response = await fetch(url, { method: "POST", credentials: "include", signal: scope.controller.signal,
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: next }) });
      const enabled = await enabledFrom(response);
      if (scopeRef.current === scope) setState({ key, enabled, supported: true, error: null });
    } catch {
      if (scopeRef.current === scope) setState({ ...current, error: "Không lưu được trạng thái GPU Modal." });
    } finally {
      scope.saving = false;
      if (scopeRef.current === scope) setSavingKey(null);
    }
  }, [current, key, url]);

  return {
    enabled: current?.enabled ?? null,
    supported: current?.supported ?? true,
    error: current?.error ?? null,
    busy: key !== null && savingKey === key,
    setEnabled,
  };
}
