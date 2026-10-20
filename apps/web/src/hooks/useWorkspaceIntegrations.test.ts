import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useWorkspaceIntegrations, parseIntegrations, type IntegrationOptions } from './useWorkspaceIntegrations';
import type { AuthenticatedUser } from '../../../../contracts/v1/workspace';

const user:AuthenticatedUser={id:'admin',email:'a@example.com',display_name:'Admin',role:'admin'};
const options:IntegrationOptions={platformUrl:'http://localhost:8000',workspaceId:'local',user};
const snapshot=() => ({api_version:'1',workspace_id:'local',permissions:{manage:true},webhook_ready:true,worker_online:true,
  available_scopes:['models:read'],available_events:['evaluation.completed'],limits:{key_per_minute:60,workspace_per_minute:300,
    webhook_per_minute:30,webhook_workspace_per_minute:60},keys:[],webhooks:[],deliveries:[]});
const logs=() => ({api_version:'1',workspace_id:'local',logs:[],next_cursor:null});
const response=(v:unknown) => new Response(JSON.stringify(v));
afterEach(() => {vi.unstubAllGlobals();vi.useRealTimers();});

it('reads only for admin and clears data on workspace or role changes',async () => {
  const fetcher=vi.fn(async (url:string) => response(url.includes('/logs') ? logs() : snapshot()));
  vi.stubGlobal('fetch',fetcher);
  const {result,rerender}=renderHook(useWorkspaceIntegrations,{initialProps:{...options,user:null} as IntegrationOptions});
  expect(fetcher).not.toHaveBeenCalled();
  rerender(options);
  await waitFor(() => expect(result.current.canMutate).toBe(true));
  rerender({...options,workspaceId:'other'});
  expect(result.current.snapshot).toBeNull();
  await waitFor(() => expect(result.current.error).toBeTruthy());
  rerender({...options,user:{...user,role:'viewer'}});
  expect(result.current.snapshot).toBeNull();
  expect(result.current.access).toBe('forbidden');
});

it('returns one-time secrets without retaining them in the read snapshot',async () => {
  vi.stubGlobal('fetch',vi.fn(async (url:string,init:RequestInit) => response(url.includes('/logs') ? logs()
    : init.method==='POST' ? {...snapshot(),secret:'one-time-secret',id:'key'} : snapshot())));
  const {result}=renderHook(() => useWorkspaceIntegrations(options));
  await waitFor(() => expect(result.current.canMutate).toBe(true));
  await act(async () => {expect(await result.current.mutate({path:'/keys',body:{request_id:'id'}})).toEqual({secret:'one-time-secret',id:'key'});});
  expect(JSON.stringify(result.current.snapshot)).not.toContain('one-time-secret');
});

it('blocks writes on stale errors and ignores late secrets after role changes',async () => {
  let resolve!:(value:Response) => void;
  const late=new Promise<Response>(done => {resolve=done;});
  vi.stubGlobal('fetch',vi.fn((url:string,init:RequestInit) => init.method==='POST' ? late : Promise.resolve(response(url.includes('/logs') ? logs() : snapshot()))));
  const {result,rerender}=renderHook(useWorkspaceIntegrations,{initialProps:options});
  await waitFor(() => expect(result.current.canMutate).toBe(true));
  let write!:Promise<unknown>;
  act(() => {write=result.current.mutate({path:'/keys',body:{request_id:'id'}});});
  rerender({...options,user:{...user,role:'viewer'}});
  await act(async () => {resolve(response({...snapshot(),secret:'late-secret',id:'key'}));expect(await write).toBeNull();});
  expect(result.current.snapshot).toBeNull();
  expect(result.current.canMutate).toBe(false);
});

it('rejects malformed nested rows and foreign workspace responses',() => {
  expect(() => parseIntegrations({...snapshot(),workspace_id:'other'},'local')).toThrow();
  expect(() => parseIntegrations({...snapshot(),keys:[{id:'x',scopes:['models:deploy']}]},'local')).toThrow();
  expect(() => parseIntegrations({...snapshot(),webhooks:[{id:'x',enabled:'true'}]},'local')).toThrow();
  expect(() => parseIntegrations({...snapshot(),deliveries:[{id:'x',attempts:-1}]},'local')).toThrow();
});

it('times out even if fetch ignores abort',async () => {
  vi.useFakeTimers();vi.stubGlobal('fetch',vi.fn(() => new Promise<Response>(()=>{})));
  const {result}=renderHook(() => useWorkspaceIntegrations(options));
  await act(async () => {await vi.advanceTimersByTimeAsync(8001);});
  expect(result.current.busy).toBe(false);expect(result.current.error).toBeTruthy();
});
