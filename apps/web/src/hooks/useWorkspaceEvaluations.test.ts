import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useWorkspaceEvaluations, type EvaluationOptions } from './useWorkspaceEvaluations';
import type { AuthenticatedUser } from '../../../../contracts/v1/workspace';

const user: AuthenticatedUser = { id:'admin',email:'admin@example.com',display_name:'Admin',role:'admin' };
const options = { platformUrl:'http://localhost:8000',workspaceId:'local',user:user as AuthenticatedUser | null };
const snapshot = () => ({ api_version:'1',workspace_id:'local',permissions:{create:true,cancel:true},
  active_model_id:'base',workers:{onnx:true},models:[{id:'base',model_version:'base-v1',backend:'onnx',active:true},
    {id:'candidate',model_version:'candidate-v1',backend:'onnx',active:false}],
  snapshots:[{id:'snapshot',dataset_version:'dataset',dataset_name:'Heldout',sample_count:10,sha256:'a'.repeat(64)}],runs:[] });
const response = (value:unknown) => new Response(JSON.stringify(value));
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

it('loads only for an identified actor and erases prior workspace results', async () => {
  const fetcher = vi.fn().mockImplementation(async () => response(snapshot()));
  vi.stubGlobal('fetch',fetcher);
  const {result,rerender} = renderHook(useWorkspaceEvaluations,{initialProps:{...options,user:null} as EvaluationOptions});
  expect(fetcher).not.toHaveBeenCalled();
  rerender(options);
  await waitFor(() => expect(result.current.snapshot?.workspace_id).toBe('local'));
  rerender({...options,workspaceId:'other'});
  expect(result.current.snapshot).toBeNull();
  await waitFor(() => expect(result.current.error).toBeTruthy());
  expect(result.current.canMutate).toBe(false);
});

it('preserves the exact request id on an explicit retry after a lost acknowledgement', async () => {
  let failed = false;
  const fetcher = vi.fn().mockImplementation(async (_url:string,init:RequestInit) => {
    if (init.method === 'POST' && !failed) { failed=true; throw new Error('lost ack'); }
    return response(snapshot());
  });
  vi.stubGlobal('fetch',fetcher);
  const {result} = renderHook(() => useWorkspaceEvaluations(options));
  await waitFor(() => expect(result.current.canMutate).toBe(true));
  const action = {type:'create' as const,request_id:'same-id',model_id:'candidate',snapshot_id:'snapshot'};
  await act(async () => { expect(await result.current.mutate(action)).toBe(false); });
  expect(result.current.canMutate).toBe(false);
  await act(async () => { await result.current.refresh(); });
  await act(async () => { expect(await result.current.mutate(action)).toBe(true); });
  const writes = fetcher.mock.calls.filter(([,init]) => init.method === 'POST');
  expect(writes).toHaveLength(2);
  expect(JSON.parse(writes[0][1].body)).toEqual({request_id:'same-id',model_id:'candidate',snapshot_id:'snapshot'});
  expect(writes[0][1].body).toBe(writes[1][1].body);
});

it('blocks reviewer mutations and rejects malformed nested reports', async () => {
  const fetcher = vi.fn().mockImplementation(async () => response({...snapshot(),permissions:{create:false,cancel:false}}));
  vi.stubGlobal('fetch',fetcher);
  const {result} = renderHook(() => useWorkspaceEvaluations({...options,user:{...user,role:'reviewer'}}));
  await waitFor(() => expect(result.current.snapshot).not.toBeNull());
  await act(async () => { expect(await result.current.mutate({type:'create',request_id:'x',model_id:'candidate',snapshot_id:'snapshot'})).toBe(false); });
  expect(fetcher).toHaveBeenCalledTimes(1);
  fetcher.mockImplementation(async () => response({...snapshot(),runs:[{id:'bad',report:{candidate:{macro_f1:Infinity}}}]}));
  await act(async () => { await result.current.refresh(); });
  expect(result.current.error).toBeTruthy();
  expect(result.current.stale).toBe(true);
});

it('ignores an old reply after role changes', async () => {
  let resolve!: (value:Response) => void;
  const old = new Promise<Response>(done => { resolve=done; });
  vi.stubGlobal('fetch',vi.fn().mockReturnValueOnce(old).mockImplementation(async () => response({...snapshot(),permissions:{create:false,cancel:false}})));
  const {result,rerender} = renderHook(useWorkspaceEvaluations,{initialProps:options});
  rerender({...options,user:{...user,role:'reviewer'}});
  await waitFor(() => expect(result.current.snapshot?.permissions.create).toBe(false));
  await act(async () => { resolve(response(snapshot())); });
  expect(result.current.snapshot?.permissions.create).toBe(false);
});

it('bounds a read even if the network ignores cancellation', async () => {
  vi.useFakeTimers();
  vi.stubGlobal('fetch',vi.fn(() => new Promise<Response>(() => {})));
  const {result}=renderHook(() => useWorkspaceEvaluations(options));
  await act(async () => {await vi.advanceTimersByTimeAsync(8001);});
  expect(result.current.busy).toBe(false);
  expect(result.current.error).toBeTruthy();
  expect(result.current.snapshot).toBeNull();
});
