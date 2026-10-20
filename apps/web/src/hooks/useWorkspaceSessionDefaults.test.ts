import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useWorkspaceSessionDefaults } from './useWorkspaceSessionDefaults';

const effective = { api_version: '1', workspace_id: 'local', runtime_defaults: { capture_mode: 'automatic' },
  collection: { enabled: true, process_enabled: true, require_consent: false, default_quota_per_label: 100, revision: 0 } };
const options = { platformUrl: 'http://localhost:8000', workspaceId: 'local', identity: 'admin:admin', enabled: true, blocked: false };
afterEach(() => vi.unstubAllGlobals());
it('applies the server default once and never refetches after a current-session change', async () => {
  const apply = vi.fn(); const fetcher = vi.fn(async () => new Response(JSON.stringify(effective))); vi.stubGlobal('fetch', fetcher);
  const { rerender } = renderHook(useWorkspaceSessionDefaults, { initialProps: { ...options, onApply: apply } });
  await waitFor(() => expect(apply).toHaveBeenCalledWith('automatic'));
  rerender({ ...options, onApply: apply, blocked: true }); rerender({ ...options, onApply: apply });
  expect(apply).toHaveBeenCalledTimes(1); expect(fetcher).toHaveBeenCalledTimes(1);
});
it('never overwrites a manual choice or a camera session while its request is pending', async () => {
  let finish!: (response: Response) => void;
  vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { finish = resolve; })));
  const apply = vi.fn(); const { rerender } = renderHook(useWorkspaceSessionDefaults, { initialProps: { ...options, onApply: apply } });
  rerender({ ...options, onApply: apply, blocked: true }); rerender({ ...options, onApply: apply });
  await act(async () => { finish(new Response(JSON.stringify(effective))); });
  expect(apply).not.toHaveBeenCalled();
});
it('ignores foreign workspace defaults and a logged-out late response', async () => {
  const apply = vi.fn(); vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(effective))));
  const { rerender } = renderHook(useWorkspaceSessionDefaults, { initialProps: { ...options, workspaceId: 'other', onApply: apply } });
  await act(async () => {}); expect(apply).not.toHaveBeenCalled();
  rerender({ ...options, workspaceId: 'other', onApply: apply, enabled: false });
  expect(apply).not.toHaveBeenCalled();
});
it('applies the remembered default before the read returns, only for the same account', async () => {
  vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => {})));
  window.localStorage.setItem('vsign.captureDefault:http://localhost:8000:local:admin:admin', 'automatic');
  const apply = vi.fn();
  renderHook(useWorkspaceSessionDefaults, { initialProps: { ...options, onApply: apply } });
  expect(apply).toHaveBeenCalledWith('automatic');
  const other = vi.fn();
  renderHook(useWorkspaceSessionDefaults, { initialProps: { ...options, identity: 'viewer:viewer', onApply: other } });
  expect(other).not.toHaveBeenCalled();
});
