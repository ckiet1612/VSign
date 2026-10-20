import { useEffect, useLayoutEffect, useMemo, useRef } from 'react';
import { parseEffectiveSettings } from '../lib/workspaceSettings';
import { workspaceRequest } from '../lib/workspaceApi';

interface Options {
  platformUrl: string; workspaceId: string; identity: string | null; enabled: boolean;
  blocked: boolean; onApply: (mode: 'manual' | 'automatic') => void;
}

const storageKey = (platformUrl: string, workspaceId: string, identity: string) =>
  `vsign.captureDefault:${platformUrl}:${workspaceId}:${identity}`;

function remembered(key: string): 'manual' | 'automatic' | null {
  try {
    const value = window.localStorage.getItem(key);
    return value === 'manual' || value === 'automatic' ? value : null;
  } catch { return null; }
}

export function useWorkspaceSessionDefaults({ platformUrl, workspaceId, identity, enabled, blocked, onApply }: Options) {
  const scope = useMemo(() => ({ platformUrl, workspaceId, identity, enabled }), [platformUrl, workspaceId, identity, enabled]);
  const current = useRef(scope); current.current = scope;
  const blockedScope = useRef<typeof scope | null>(null);
  const apply = useRef(onApply); apply.current = onApply;
  // A user action permanently wins over a late startup default for this session.
  if (blocked) blockedScope.current = scope;
  // The last default seen for this account applies before the first paint, so a reload does not show
  // manual and then flip to automatic when the settings read returns. The read below still corrects it.
  useLayoutEffect(() => {
    if (!enabled || !identity || blockedScope.current === scope) return;
    const cached = remembered(storageKey(platformUrl, workspaceId, identity));
    if (cached) apply.current(cached);
  }, [scope, enabled, identity, platformUrl, workspaceId]);
  useEffect(() => {
    if (!enabled || !identity) return;
    const controller = new AbortController();
    let active = true, timer = 0;
    const deadline = new Promise<never>((_, reject) => {
      timer = window.setTimeout(() => { controller.abort(); reject(new Error('timeout')); }, 8000);
    });
    void Promise.race([workspaceRequest<unknown>(platformUrl, '/api/v1/workspace/settings/effective', { cache: 'no-store' }, controller.signal), deadline])
      .then(({ body }) => {
        const defaults = parseEffectiveSettings(body, workspaceId);
        try { window.localStorage.setItem(storageKey(platformUrl, workspaceId, identity), defaults.runtime_defaults.capture_mode); } catch { /* Private mode: only the flip-free reload is lost. */ }
        if (active && current.current === scope && blockedScope.current !== scope) apply.current(defaults.runtime_defaults.capture_mode);
      }).catch(() => { /* An unavailable default leaves the existing manual mode intact. */ })
      .finally(() => window.clearTimeout(timer));
    return () => { active = false; controller.abort(); window.clearTimeout(timer); };
  }, [scope, enabled, identity, platformUrl, workspaceId]);
}
