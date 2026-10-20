import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useWorkspaceSettings } from './useWorkspaceSettings';
import { savedSettings, settingsSnapshot, settingsUser } from '../test/settingsFixture';

const options = { platformUrl: 'http://localhost:8000', workspaceId: 'local', user: settingsUser };
const requestId = '123e4567-e89b-12d3-a456-426614174002';
const action = { path: '/update' as const, body: { request_id: requestId, expected_revision: 0, runtime_defaults: { capture_mode: 'automatic' } } };
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

it('reads only for authenticated users and rejects a foreign snapshot', async () => {
  const fetcher = vi.fn(async () => new Response(JSON.stringify(settingsSnapshot())));
  vi.stubGlobal('fetch', fetcher);
  const { result, rerender } = renderHook(useWorkspaceSettings, { initialProps: { ...options, user: null } as Parameters<typeof useWorkspaceSettings>[0] });
  expect(fetcher).not.toHaveBeenCalled();
  rerender(options); await waitFor(() => expect(result.current.ready).toBe(true));
  rerender({ ...options, workspaceId: 'other' }); expect(result.current.snapshot).toBeNull();
  await waitFor(() => expect(result.current.error).toBeTruthy());
  expect(result.current.ready).toBe(false);
});

it('does not acknowledge a save with a foreign request ID', async () => {
  vi.stubGlobal('fetch', vi.fn(async (_url: string, init: RequestInit) => new Response(JSON.stringify(init.method === 'POST'
    ? savedSettings('123e4567-e89b-12d3-a456-426614174099') : settingsSnapshot()))));
  const { result } = renderHook(() => useWorkspaceSettings(options));
  await waitFor(() => expect(result.current.ready).toBe(true));
  await act(async () => { expect(await result.current.mutate(action)).toBeNull(); });
  expect(result.current.error).toBeTruthy(); expect(result.current.failed).toEqual(action);
});

it('keeps an uncertain mutation across refresh and retries its exact body', async () => {
  let attempts = 0;
  const fetcher = vi.fn(async (_url: string, init: RequestInit) => {
    if (init.method !== 'POST') return new Response(JSON.stringify(settingsSnapshot()));
    if (++attempts === 1) throw new Error('connection lost');
    return new Response(JSON.stringify(savedSettings(requestId, { runtime_defaults: { capture_mode: 'automatic' } })));
  });
  vi.stubGlobal('fetch', fetcher);
  const { result } = renderHook(() => useWorkspaceSettings(options));
  await waitFor(() => expect(result.current.ready).toBe(true));
  await act(async () => { await result.current.mutate(action); });
  expect(result.current.failed).toEqual(action);
  await act(async () => { await result.current.refresh(); });
  expect(result.current.failed).toEqual(action); expect(result.current.ready).toBe(false);
  await act(async () => { await result.current.retry(); });
  expect(result.current.failed).toBeNull(); expect(result.current.snapshot?.runtime_defaults.capture_mode).toBe('automatic');
  const writes = fetcher.mock.calls.filter(([, init]) => init.method === 'POST');
  expect(writes).toHaveLength(2); expect(writes[0][1].body).toEqual(writes[1][1].body);
});

it('drops late results on role or identity changes', async () => {
  let finish!: (value: Response) => void;
  vi.stubGlobal('fetch', vi.fn((_url: string, init: RequestInit) => init.method === 'POST'
    ? new Promise<Response>(resolve => { finish = resolve; }) : Promise.resolve(new Response(JSON.stringify(settingsSnapshot())))));
  const { result, rerender } = renderHook(useWorkspaceSettings, { initialProps: options as Parameters<typeof useWorkspaceSettings>[0] });
  await waitFor(() => expect(result.current.ready).toBe(true));
  let pending!: Promise<unknown>;
  act(() => { pending = result.current.mutate(action); });
  rerender({ ...options, user: null });
  await act(async () => { finish(new Response(JSON.stringify(savedSettings(requestId)))); expect(await pending).toBeNull(); });
  expect(result.current.snapshot).toBeNull(); expect(result.current.ready).toBe(false);
});

it('clears private data after access denial and times out ignored aborts', async () => {
  vi.useFakeTimers();
  vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => {})));
  const { result } = renderHook(() => useWorkspaceSettings(options));
  await act(async () => { await vi.advanceTimersByTimeAsync(8001); });
  expect(result.current.busy).toBe(false); expect(result.current.error).toBeTruthy();
});

it('erases a private snapshot when refreshed authority is denied', async () => {
  const fetcher = vi.fn(async () => new Response(JSON.stringify(settingsSnapshot())));
  vi.stubGlobal('fetch', fetcher);
  const { result } = renderHook(() => useWorkspaceSettings(options));
  await waitFor(() => expect(result.current.ready).toBe(true));
  fetcher.mockImplementationOnce(async () => new Response('{}', { status: 403 }));
  await act(async () => { await result.current.refresh(); });
  expect(result.current.snapshot).toBeNull(); expect(result.current.access).toBe('forbidden');
});

it('locks writes once the last confirmed read is stale', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(settingsSnapshot()))));
  const { result } = renderHook(() => useWorkspaceSettings(options));
  await waitFor(() => expect(result.current.ready).toBe(true));
  const now = Date.now(); const clock = vi.spyOn(Date, 'now').mockReturnValue(now + 60001);
  await act(async () => { expect(await result.current.mutate(action)).toBeNull(); });
  expect(result.current.stale).toBe(true); expect(result.current.failed).toBeNull();
  expect(vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0);
  clock.mockRestore();
});
