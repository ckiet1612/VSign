import {act,renderHook,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {useWorkspaceTeam,parseTeamOverview} from './useWorkspaceTeam';
import {teamUser,teamOverview,teamInvitations} from '../test/teamFixture';
const options={platformUrl:'http://localhost:8000',workspaceId:'local',user:teamUser,tab:'members' as const};
afterEach(()=>{vi.unstubAllGlobals();vi.useRealTimers();});
it('reads only for managers and rejects foreign or malformed data',async()=>{
  const fetcher=vi.fn(async()=>new Response(JSON.stringify(teamOverview())));vi.stubGlobal('fetch',fetcher);
  const {result,rerender}=renderHook(useWorkspaceTeam,{initialProps:{...options,user:null} as Parameters<typeof useWorkspaceTeam>[0]});
  expect(fetcher).not.toHaveBeenCalled();rerender(options);
  await waitFor(()=>expect(result.current.canMutate).toBe(true));
  rerender({...options,workspaceId:'other'});expect(result.current.snapshot).toBeNull();
  await waitFor(()=>expect(result.current.error).toBeTruthy());
  expect(()=>parseTeamOverview({...teamOverview(),members:[{...teamOverview().members[0],role:'model_admin'}]},'local')).toThrow();
});
it('returns invitation secrets once without retaining them in stored state',async()=>{
  vi.stubGlobal('fetch',vi.fn(async(_url:string,init:RequestInit)=>new Response(JSON.stringify(init.method==='POST'
    ? {...teamInvitations(),id:'one',secret:'x'.repeat(43)} : teamOverview()))));
  const {result}=renderHook(()=>useWorkspaceTeam(options));await waitFor(()=>expect(result.current.canMutate).toBe(true));
  await act(async()=>expect(await result.current.mutate({path:'/invitations',body:{request_id:'one'}})).toEqual({id:'one',secret:'x'.repeat(43)}));
  expect(JSON.stringify(result.current.snapshot)).not.toContain('x'.repeat(43));
});
it('drops a late mutation result when role changes',async()=>{
  let resolve!:(value:Response)=>void;const late=new Promise<Response>(done=>{resolve=done;});
  vi.stubGlobal('fetch',vi.fn((_url:string,init:RequestInit)=>init.method==='POST'?late:Promise.resolve(new Response(JSON.stringify(teamOverview())))));
  const {result,rerender}=renderHook(useWorkspaceTeam,{initialProps:options as Parameters<typeof useWorkspaceTeam>[0]});
  await waitFor(()=>expect(result.current.canMutate).toBe(true));let write!:Promise<unknown>;
  act(()=>{write=result.current.mutate({path:'/invitations',body:{request_id:'one'}});});
  rerender({...options,user:{...teamUser,role:'viewer'}});
  await act(async()=>{resolve(new Response(JSON.stringify({...teamInvitations(),secret:'x'.repeat(43),id:'one'})));expect(await write).toBeNull();});
  expect(result.current.snapshot).toBeNull();expect(result.current.canMutate).toBe(false);
});
it('times out even when fetch ignores abort',async()=>{
  vi.useFakeTimers();vi.stubGlobal('fetch',vi.fn(()=>new Promise<Response>(()=>{})));
  const {result}=renderHook(()=>useWorkspaceTeam(options));
  await act(async()=>{await vi.advanceTimersByTimeAsync(8001);});
  expect(result.current.busy).toBe(false);expect(result.current.error).toBeTruthy();
});
it.each([{}, {id:'foreign',secret:null}, {id:'one'}, {id:'one',secret:'bad'}])('does not acknowledge malformed invitation replies %j',async fields=>{
  vi.stubGlobal('fetch',vi.fn(async(_url:string,init:RequestInit)=>new Response(JSON.stringify(init.method==='POST'
    ? {...teamInvitations(),...fields} : teamOverview()))));
  const {result}=renderHook(()=>useWorkspaceTeam(options));await waitFor(()=>expect(result.current.canMutate).toBe(true));
  await act(async()=>expect(await result.current.mutate({path:'/invitations',body:{request_id:'one'}})).toBeNull());
  expect(result.current.error).toBeTruthy();expect(result.current.canMutate).toBe(false);
});
it('keeps the previous rows on screen while a new search loads, then swaps them',async()=>{
  let release!:()=>void;const held=new Promise<void>(done=>{release=done;});
  vi.stubGlobal('fetch',vi.fn(async(url:string)=>{
    if(url.includes('search=')) {await held;return new Response(JSON.stringify({...teamOverview(),members:[]}));}
    return new Response(JSON.stringify(teamOverview()));
  }));
  const {result,rerender}=renderHook(useWorkspaceTeam,{initialProps:options as Parameters<typeof useWorkspaceTeam>[0]});
  await waitFor(()=>expect(result.current.canMutate).toBe(true));
  const rows=result.current.snapshot!.overview.members.length;
  rerender({...options,search:'nobody'});
  expect(result.current.snapshot?.overview.members).toHaveLength(rows);
  expect(result.current.previewing).toBe(true);expect(result.current.canMutate).toBe(false);
  await act(async()=>{release();});
  await waitFor(()=>expect(result.current.previewing).toBe(false));
  expect(result.current.snapshot?.overview.members).toHaveLength(0);
});
it('resumes a revisited tab from its last read while it revalidates',async()=>{
  vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify(teamOverview()))));
  const first=renderHook(()=>useWorkspaceTeam(options));
  await waitFor(()=>expect(first.result.current.canMutate).toBe(true));first.unmount();
  vi.stubGlobal('fetch',vi.fn(()=>new Promise<Response>(()=>{})));
  const again=renderHook(()=>useWorkspaceTeam(options));
  expect(again.result.current.snapshot?.overview.members.length).toBeGreaterThan(0);
  expect(again.result.current.busy).toBe(true);expect(again.result.current.stale).toBe(false);expect(again.result.current.canMutate).toBe(false);
  again.unmount();
  // Another user never sees that copy.
  const other=renderHook(()=>useWorkspaceTeam({...options,user:{...teamUser,id:'someone-else'}}));
  expect(other.result.current.snapshot).toBeNull();
});
