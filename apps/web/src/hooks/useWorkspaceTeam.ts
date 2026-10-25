import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { AuthenticatedUser } from '../../../../contracts/v1/workspace';
import { teamActions, type TeamOverview, type TeamSnapshot, type TeamTab, type TeamRole,
  type TeamInvitation, type TeamEvent, type TeamChange, type InvitationDetails } from '../../../../contracts/v1/team';
import { workspaceRequest, WorkspaceApiError } from '../lib/workspaceApi';
import { permissionLabels } from '../lib/teamLabels';
import { forgetView, readViewCache, rememberView, viewCacheKey } from '../lib/viewCache';

export interface TeamOptions {
  platformUrl:string; workspaceId:string; user:AuthenticatedUser|null; tab:TeamTab;
  search?:string; cursor?:string; memberId?:string; action?:string; fromAt?:string; toAt?:string;
}
export interface TeamAction {path:string; body:Record<string,unknown>}
interface State {snapshot:TeamSnapshot|null; busy:boolean; stale:boolean; error:string; updatedAt:number|null; access:'ready'|'forbidden'|'login_required'}
const record=(v:unknown):v is Record<string,unknown> => !!v && typeof v==='object' && !Array.isArray(v);
const text=(v:unknown):v is string => typeof v==='string' && v.length>0 && v.length<=2048;
const optionalText=(v:unknown) => v===null || text(v);
const integer=(v:unknown) => Number.isSafeInteger(v) && Number(v)>=0;
const date=(v:unknown):v is string => typeof v==='string' && /^\d{4}-\d\d-\d\dT.*(?:Z|[+-]\d\d:\d\d)$/.test(v) && Number.isFinite(Date.parse(v));
const roles=['owner','admin','operator','reviewer','viewer'];
const internalRoles=[...roles,'model_admin','system_admin'];
const grantable=roles.slice(1),statuses=['active','suspended','removed'];
const oneOf=(v:unknown,allowed:readonly string[]) => typeof v==='string' && allowed.includes(v);
const list=(v:unknown,check:(r:Record<string,unknown>)=>boolean):v is Record<string,unknown>[] => Array.isArray(v) && v.length<=50 &&
  v.every(r=>record(r) && text(r.id) && check(r)) && new Set(v.map(r=>r.id)).size===v.length;
function envelope(v:unknown,workspace:string):asserts v is Record<string,unknown> {
  if(!record(v) || v.api_version!=='1' || v.workspace_id!==workspace) throw new Error('invalid_snapshot');
}
export function parseTeamOverview(v:unknown,workspace:string,systemAdmin=false):TeamOverview {
  envelope(v,workspace);
  if(!record(v.permissions) || typeof v.permissions.manage!=='boolean' || !record(v.counts) ||
    !statuses.every(s=>integer((v.counts as Record<string,unknown>)[s])) || !optionalText(v.next_cursor) ||
    !Array.isArray(v.grantable_roles) || !v.grantable_roles.length || !v.grantable_roles.every(r=>oneOf(r,grantable)) ||
    new Set(v.grantable_roles).size!==v.grantable_roles.length ||
    !list(v.members,r=>text(r.email) && text(r.display_name) && oneOf(r.role,systemAdmin?internalRoles:roles) && oneOf(r.status,statuses) &&
      typeof r.active==='boolean' && typeof r.protected==='boolean' && integer(r.revision) && date(r.created_at))) throw new Error('invalid_snapshot');
  return {api_version:'1',workspace_id:workspace,permissions:{manage:v.permissions.manage},grantable_roles:[...v.grantable_roles],
    counts:{active:v.counts.active,suspended:v.counts.suspended,removed:v.counts.removed},
    members:v.members.map(r=>({id:r.id,email:r.email,display_name:r.display_name,role:r.role,status:r.status,
      active:r.active,protected:r.protected,revision:r.revision,created_at:r.created_at})),next_cursor:v.next_cursor} as TeamOverview;
}
function parseRoles(v:unknown,workspace:string,systemAdmin=false):TeamRole[] {
  envelope(v,workspace);
  if(!list(v.roles,r=>oneOf(r.id,systemAdmin?internalRoles:roles) && Array.isArray(r.permissions) && r.permissions.length<=30 &&
    r.permissions.every(p=>text(p) && Object.hasOwn(permissionLabels,p)) && new Set(r.permissions).size===r.permissions.length)) throw new Error('invalid_snapshot');
  return v.roles.map(r=>({id:r.id,permissions:[...(r.permissions as string[])]})) as TeamRole[];
}
function parseInvitations(v:unknown,workspace:string) {
  envelope(v,workspace);
  if(!optionalText(v.next_cursor) || !list(v.invitations,r=>text(r.email) && oneOf(r.role,grantable) &&
    oneOf(r.status,['pending','accepted','expired','revoked']) && text(r.created_by) && date(r.created_at) && date(r.expires_at))) throw new Error('invalid_snapshot');
  return {invitations:v.invitations.map(r=>({id:r.id,email:r.email,role:r.role,status:r.status,created_by:r.created_by,
    created_at:r.created_at,expires_at:r.expires_at})) as TeamInvitation[],next_cursor:v.next_cursor as string|null};
}
function change(v:unknown):TeamChange|null {
  if(v===null) return null;
  if(!record(v) || Object.keys(v).some(k=>!['role','status','email','member_id'].includes(k)) ||
    ('role' in v && !oneOf(v.role,internalRoles)) || ('status' in v && !oneOf(v.status,statuses)) ||
    ('email' in v && !text(v.email)) || ('member_id' in v && !text(v.member_id))) throw new Error('invalid_snapshot');
  return {...v} as TeamChange;
}
function parseEvents(v:unknown,workspace:string) {
  envelope(v,workspace);
  if(!optionalText(v.next_cursor) || !list(v.events,r=>oneOf(r.action,teamActions) && ['actor_id','member_id','resource_id'].every(k=>optionalText(r[k])) &&
    oneOf(r.outcome,['success','failure']) && date(r.created_at))) throw new Error('invalid_snapshot');
  return {events:v.events.map(r=>({id:r.id,action:r.action,actor_id:r.actor_id,member_id:r.member_id,resource_id:r.resource_id,
    outcome:r.outcome,created_at:r.created_at,before:change(r.before),after:change(r.after)})) as TeamEvent[],next_cursor:v.next_cursor as string|null};
}
export function parseInvitation(v:unknown):InvitationDetails {
  if(!record(v) || v.api_version!=='1' || !text(v.workspace_id) || !text(v.workspace_name) || !text(v.email) ||
    !oneOf(v.role,grantable) || !date(v.expires_at) || typeof v.existing_account!=='boolean' || !oneOf(v.auth_mode,['session','local_admin'])) throw new Error('invalid_snapshot');
  return {api_version:'1',workspace_id:v.workspace_id,workspace_name:v.workspace_name,email:v.email,role:v.role,
    expires_at:v.expires_at,existing_account:v.existing_account,auth_mode:v.auth_mode} as InvitationDetails;
}

export function useWorkspaceTeam({platformUrl,workspaceId,user,tab,search='',cursor='',memberId='',action:actionFilter='',fromAt='',toAt=''}:TeamOptions) {
  const id=user?.id,role=user?.role;
  const scope=useMemo(()=>({platformUrl,workspaceId,id,role,tab,search,cursor,memberId,actionFilter,fromAt,toAt}),
    [platformUrl,workspaceId,id,role,tab,search,cursor,memberId,actionFilter,fromAt,toAt]);
  const current=useRef(scope);current.current=scope;
  const access:State['access']=!id?'login_required':['owner','admin','system_admin'].includes(role??'')?'ready':'forbidden';
  const empty=useCallback(():State=>({snapshot:null,busy:access==='ready',error:'',stale:false,updatedAt:null,access}),[access]);
  const cacheKey=useMemo(()=>viewCacheKey('team',scope),[scope]);
  // A tab revisit resumes from the last good read; it stays busy (so actions stay locked) until revalidated.
  const resumed=useCallback(():State=>{const cached=access==='ready'?readViewCache<State>(cacheKey):undefined;return cached?{...cached,busy:true}:empty();},[access,cacheKey,empty]);
  const [stored,setStored]=useState<{scope:typeof scope;state:State}|null>(null);
  const stateRef=useRef(stored),mounted=useRef(false),pending=useRef<AbortController|null>(null),pendingPoll=useRef(false);
  // Last list shown for this tab, kept on screen while another search, filter or page loads.
  const identity=JSON.stringify([platformUrl,workspaceId,id,role,tab]);
  const shown=useRef<{identity:string;snapshot:TeamSnapshot}|null>(null);
  const perform=useCallback(async(action?:TeamAction,background=false):Promise<{id:string|null;secret:string|null}|null>=>{
    if(!mounted.current || current.current!==scope || access!=='ready') return null;
    // An action pre-empts a background poll instead of being dropped behind it.
    if(pending.current && action && pendingPoll.current) pending.current.abort();
    else if(pending.current) return null;
    const previous=stateRef.current?.scope===scope?stateRef.current.state:resumed();
    if(action && (!previous.snapshot?.overview.permissions.manage || previous.busy || previous.error || previous.stale || previous.updatedAt===null || Date.now()-previous.updatedAt>15000)) return null;
    const controller=new AbortController();pending.current=controller;pendingPoll.current=background;
    const valid=()=>mounted.current && current.current===scope && pending.current===controller;
    const publish=(state:State)=>{const next={scope,state};stateRef.current=next;setStored(next);};
    // A poll over rows already on screen revalidates silently: locking the page every 5 s dimmed buttons and blurred inputs.
    if(!(background && previous.snapshot)) publish({...previous,busy:true});
    let timer=0,abort=()=>{};
    try {
      const deadline=new Promise<never>((_,reject)=>{
        abort=()=>reject(new Error('cancelled'));controller.signal.addEventListener('abort',abort,{once:true});
        timer=window.setTimeout(()=>{reject(new Error('timeout'));controller.abort();},8000);
      });
      const request=async()=>{
        if(action) {
          const raw=(await workspaceRequest<unknown>(platformUrl,`/api/v1/workspace/team${action.path}`,{
            method:'POST',cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify(action.body)},controller.signal)).body;
          if(action.path==='/invitations' && (!record(raw) || raw.id!==action.body.request_id ||
            !(raw.secret===null || typeof raw.secret==='string' && /^[A-Za-z0-9_-]{43}$/.test(raw.secret)))) throw new Error('invalid_snapshot');
          const old=previous.snapshot!;
          const snapshot=action.path.startsWith('/members/') ? {...old,overview:parseTeamOverview(raw,workspaceId,role==='system_admin')}
            : {...old,...parseInvitations(raw,workspaceId)};
          return {snapshot,raw};
        }
        const query=new URLSearchParams();
        if(tab==='members') {if(search) query.set('search',search);if(cursor) query.set('cursor',cursor);}
        const overview=parseTeamOverview((await workspaceRequest<unknown>(platformUrl,`/api/v1/workspace/team?${query}`,{cache:'no-store'},controller.signal)).body,workspaceId,role==='system_admin');
        let snapshot:TeamSnapshot={overview,roles:[],invitations:[],events:[],next_cursor:overview.next_cursor};
        if(tab!=='members') {
          const extra=new URLSearchParams();if(cursor) extra.set('cursor',cursor);
          if(tab==='audit') {if(memberId) extra.set('member_id',memberId);if(actionFilter) extra.set('action',actionFilter);if(fromAt) extra.set('from_at',fromAt);if(toAt) extra.set('to_at',toAt);}
          const raw=(await workspaceRequest<unknown>(platformUrl,`/api/v1/workspace/team/${tab==='audit'?'audit':tab}?${extra}`,{cache:'no-store'},controller.signal)).body;
          snapshot=tab==='roles'?{...snapshot,roles:parseRoles(raw,workspaceId,role==='system_admin'),next_cursor:null}:tab==='invitations'?{...snapshot,...parseInvitations(raw,workspaceId)}:{...snapshot,...parseEvents(raw,workspaceId)};
        }
        return {snapshot,raw:null};
      };
      const result=await Promise.race([request(),deadline]);if(!valid()) return null;
      const fresh:State={snapshot:result.snapshot,busy:false,error:'',stale:false,updatedAt:Date.now(),access:'ready'};
      publish(fresh);rememberView(cacheKey,fresh);
      return {id:record(result.raw)&&text(result.raw.id)?result.raw.id:null,
        secret:record(result.raw)&&typeof result.raw.secret==='string'&&/^[A-Za-z0-9_-]{43}$/.test(result.raw.secret)?result.raw.secret:null};
    } catch(error) {
      if(!valid()) return null;
      if(error instanceof WorkspaceApiError && [401,403].includes(error.status)) {forgetView(cacheKey);shown.current=null;publish({...empty(),busy:false,access:error.status===401?'login_required':'forbidden'});}
      else publish({...previous,busy:false,stale:!!previous.snapshot,error:error instanceof Error && error.message==='invalid_snapshot'
        ? 'Phản hồi thành viên không hợp lệ.' : error instanceof WorkspaceApiError && [409,422,429,503].includes(error.status) ? error.message
        : action?'Chưa xác nhận thao tác. Làm mới rồi thử lại cùng yêu cầu.':'Không thể tải thành viên. Hãy làm mới.'});
      return null;
    } finally {window.clearTimeout(timer);controller.signal.removeEventListener('abort',abort);if(pending.current===controller) {pending.current=null;pendingPoll.current=false;}}
  },[scope,access,empty,resumed,cacheKey,platformUrl,workspaceId,tab,search,cursor,memberId,actionFilter,fromAt,toAt,role]);
  useEffect(()=>{mounted.current=true;void perform();const interval=window.setInterval(()=>void perform(undefined,true),5000);
    return ()=>{mounted.current=false;window.clearInterval(interval);const controller=pending.current;pending.current=null;controller?.abort();};},[perform]);
  const own=stored?.scope===scope && id?stored.state:resumed();
  // A new query keeps the previous rows of the same tab until its own read lands (or fails), instead of blanking the page.
  const previewing=!own.snapshot && own.busy && !own.error && own.access==='ready' && shown.current?.identity===identity;
  const visible=previewing?{...own,snapshot:shown.current!.snapshot}:own;
  if(own.snapshot && own.access==='ready') shown.current={identity,snapshot:own.snapshot};
  // Age only counts once a read has settled: a resumed copy is revalidating, not stale.
  const stale=visible.stale || (!visible.busy && !!visible.snapshot && visible.updatedAt!==null && Date.now()-visible.updatedAt>15000);
  return {snapshot:visible.snapshot,busy:visible.busy,error:visible.error,access:visible.access,stale,previewing,
    canMutate:access==='ready' && visible.access==='ready' && !!visible.snapshot?.overview.permissions.manage && !visible.busy && !visible.error && !stale,
    refresh:useCallback(()=>perform(),[perform]),mutate:useCallback((action:TeamAction)=>perform(action),[perform])};
}
