import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { AuthenticatedUser } from '../../../../contracts/v1/workspace';
import type { RetentionPreview, WorkspaceSettingsSnapshot } from '../../../../contracts/v1/settings';
import { parseRetentionPreview, parseWorkspaceSettings } from '../lib/workspaceSettings';
import { workspaceRequest, WorkspaceApiError } from '../lib/workspaceApi';
import { forgetView, readViewCache, rememberView, viewCacheKey } from '../lib/viewCache';

export interface SettingsAction { path: '/update' | '/notifications'; body: { request_id: string; expected_revision: number; [key: string]: unknown } }
interface Options { platformUrl: string; workspaceId: string; user: AuthenticatedUser | null }
interface State {
  snapshot: WorkspaceSettingsSnapshot | null; preview: RetentionPreview | null; busy: boolean; error: string;
  stale: boolean; failed: SettingsAction | null; updatedAt: number; access: 'ready' | 'forbidden' | 'login_required';
}
const empty = (): State => ({ snapshot: null, preview: null, busy: false, error: '', stale: false, failed: null, updatedAt: 0, access: 'ready' });

export function useWorkspaceSettings({ platformUrl, workspaceId, user }: Options) {
  const scope = useMemo(() => ({ platformUrl, workspaceId, id: user?.id, role: user?.role }), [platformUrl, workspaceId, user?.id, user?.role]);
  const current = useRef(scope); current.current = scope;
  const mounted = useRef(false), pending = useRef<AbortController | null>(null);
  const cacheKey = useMemo(() => viewCacheKey('settings', scope), [scope]);
  // A tab revisit resumes from the last good read; it stays busy (so saving stays locked) until revalidated.
  const resumed = useCallback((): State => {
    const cached = scope.id ? readViewCache<State>(cacheKey) : undefined;
    return cached ? { ...cached, busy: true, preview: null, failed: null } : empty();
  }, [scope.id, cacheKey]);
  const [stored, setStored] = useState<{ scope: typeof scope; state: State } | null>(null);
  const latest = useRef(stored);
  const [clock, setClock] = useState(Date.now());
  const perform = useCallback(async (action?: SettingsAction, retry = false, preview = false): Promise<WorkspaceSettingsSnapshot | null> => {
    if (!mounted.current || current.current !== scope || !scope.id || pending.current) return null;
    const previous = latest.current?.scope === scope ? latest.current.state : resumed();
    const publish = (state: State) => { latest.current = { scope, state }; setStored({ scope, state }); };
    if (action && (!retry && previous.failed || !previous.snapshot || previous.access !== 'ready' ||
      action.path === '/update' && !previous.snapshot.permissions.manage)) return null;
    if ((action && !retry || preview) && (previous.stale || previous.error || Date.now() - previous.updatedAt > 60000)) {
      publish({ ...previous, stale: !!previous.snapshot, error: 'Cài đặt đã cũ. Hãy làm mới trước khi tiếp tục.' }); return null;
    }
    if (preview && !previous.snapshot?.permissions.manage) return null;
    const controller = new AbortController(); pending.current = controller;
    const valid = () => mounted.current && current.current === scope && pending.current === controller;
    publish({ ...previous, busy: true, error: '' });
    let timer = 0, abort = () => {};
    try {
      const deadline = new Promise<never>((_, reject) => {
        abort = () => reject(new Error('cancelled'));
        controller.signal.addEventListener('abort', abort, { once: true });
        timer = window.setTimeout(() => { reject(new Error('timeout')); controller.abort(); }, 8000);
      });
      const result = await Promise.race([workspaceRequest<unknown>(platformUrl, `/api/v1/workspace/settings${preview ? '/retention/preview' : action?.path ?? ''}`, {
        method: action ? 'POST' : 'GET', cache: 'no-store', ...(action ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(action.body) } : {}),
      }, controller.signal), deadline]);
      if (!valid()) return null;
      if (preview) {
        const value = parseRetentionPreview(result.body, workspaceId);
        if (value.revision !== previous.snapshot?.revision) throw new Error('preview_conflict');
        publish({ ...previous, busy: false, preview: value }); return previous.snapshot;
      }
      const snapshot = parseWorkspaceSettings(result.body, workspaceId, scope.id);
      if (action && (snapshot.request_id !== action.body.request_id || snapshot.applied_revision !== action.body.expected_revision + 1 ||
        (action.path === '/notifications' ? snapshot.notifications.revision : snapshot.revision) < snapshot.applied_revision)) throw new Error('invalid_settings');
      const fresh: State = { snapshot, preview: previous.preview?.revision === snapshot.revision ? previous.preview : null, busy: false,
        error: '', stale: false, failed: action ? null : previous.failed, updatedAt: Date.now(), access: 'ready' };
      publish(fresh);
      if (!fresh.failed) rememberView(cacheKey, { ...fresh, preview: null });
      return snapshot;
    } catch (error) {
      if (!valid()) return null;
      const denied = error instanceof WorkspaceApiError && [401, 403].includes(error.status);
      if (denied) forgetView(cacheKey);
      const definite = error instanceof WorkspaceApiError && [401, 403, 404, 409, 413, 422].includes(error.status);
      const message = denied ? 'Bạn không có quyền truy cập cài đặt này.' : error instanceof Error && error.message === 'invalid_settings'
        ? 'Phản hồi cài đặt không hợp lệ. Hãy làm mới.' : error instanceof Error && error.message === 'preview_conflict'
        ? 'Chính sách retention đã thay đổi. Hãy làm mới.' : error instanceof WorkspaceApiError && error.status === 409
        ? 'Cài đặt đã thay đổi. Làm mới trước khi lưu.' : error instanceof WorkspaceApiError && [413, 422].includes(error.status)
        ? 'Nội dung cài đặt chưa hợp lệ.' : action ? 'Chưa xác nhận thao tác lưu. Hãy thử lại cùng yêu cầu.' : 'Không thể tải cài đặt. Hãy thử lại.';
      publish({ ...previous, busy: false, snapshot: denied ? null : previous.snapshot, preview: null, stale: !!previous.snapshot,
        failed: denied ? null : action ? definite ? null : action : previous.failed, error: message,
        access: denied ? (error.status === 401 ? 'login_required' : 'forbidden') : previous.access });
      return null;
    } finally {
      window.clearTimeout(timer); controller.signal.removeEventListener('abort', abort);
      if (pending.current === controller) pending.current = null;
    }
  }, [scope, platformUrl, workspaceId, resumed, cacheKey]);
  useEffect(() => {
    mounted.current = true; void perform();
    const timer = window.setInterval(() => setClock(Date.now()), 5000);
    return () => { mounted.current = false; window.clearInterval(timer); const controller = pending.current; pending.current = null; controller?.abort(); };
  }, [perform]);
  const visible = stored?.scope === scope && user ? stored.state : resumed();
  // Age only counts once a read has settled: a resumed copy is revalidating, not stale.
  const stale = visible.stale || !visible.busy && !!visible.snapshot && Math.max(clock, Date.now()) - visible.updatedAt > 60000;
  return { ...visible, stale, ready: !!user && visible.access === 'ready' && !!visible.snapshot && !visible.busy && !visible.error && !stale && !visible.failed,
    refresh: useCallback(() => perform(), [perform]), mutate: useCallback((action: SettingsAction) => perform(action), [perform]),
    retry: useCallback(() => visible.failed ? perform(visible.failed, true) : perform(), [perform, visible.failed]),
    loadPreview: useCallback(() => perform(undefined, false, true), [perform]) };
}
