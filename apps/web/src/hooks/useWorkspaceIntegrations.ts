import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { AuthenticatedUser } from '../../../../contracts/v1/workspace';
import { integrationScopes, integrationEvents, type WorkspaceIntegrations, type IntegrationLogs } from '../../../../contracts/v1/integrations';
import { workspaceRequest, WorkspaceApiError } from '../lib/workspaceApi';
import { forgetView, readViewCache, rememberView, viewCacheKey } from '../lib/viewCache';

export interface IntegrationOptions {platformUrl:string;workspaceId:string;user:AuthenticatedUser|null;logKind?:string;cursor?:string}
export interface IntegrationAction {path:string;body:Record<string,unknown>}
interface State {snapshot:WorkspaceIntegrations|null;logs:IntegrationLogs|null;busy:boolean;stale:boolean;error:string;updatedAt:number|null;access:'ready'|'forbidden'|'login_required'}
const record=(v:unknown):v is Record<string,unknown> => !!v && typeof v==='object' && !Array.isArray(v);
const text=(v:unknown):v is string => typeof v==='string' && v.length>0 && v.length<=2048;
const integer=(v:unknown) => Number.isSafeInteger(v) && Number(v)>=0;
const date=(v:unknown) => typeof v==='string' && /^\d{4}-\d\d-\d\dT.*(?:Z|[+-]\d\d:\d\d)$/.test(v) && Number.isFinite(Date.parse(v));
const optionalDate=(v:unknown) => v===null || date(v);
const optionalText=(v:unknown) => v===null || text(v);
const rows=(v:unknown,check:(r:Record<string,unknown>)=>boolean) => Array.isArray(v) && v.length<=50 &&
  v.every(r=>record(r) && text(r.id) && date(r.created_at) && check(r)) && new Set(v.map(r=>r.id)).size===v.length;
const set=(v:unknown,allowed:readonly string[]) => Array.isArray(v) && v.length>0 && v.every(s=>typeof s==='string' && allowed.includes(s)) && new Set(v).size===v.length;

export function parseIntegrations(v:unknown,workspace:string):WorkspaceIntegrations {
  if (!record(v) || v.api_version!=='1' || v.workspace_id!==workspace || !record(v.permissions) || typeof v.permissions.manage!=='boolean' ||
      typeof v.webhook_ready!=='boolean' || typeof v.worker_online!=='boolean' || !set(v.available_scopes,integrationScopes) || !set(v.available_events,integrationEvents) ||
      !record(v.limits) || !['key_per_minute','workspace_per_minute','webhook_per_minute','webhook_workspace_per_minute'].every(k=>integer(v.limits && (v.limits as Record<string,unknown>)[k])) ||
      !rows(v.keys,r=>text(r.name) && text(r.prefix) && set(r.scopes,integrationScopes) && integer(r.requests_per_minute) && Number(r.requests_per_minute)>=1 && Number(r.requests_per_minute)<=60 &&
        date(r.expires_at) && optionalDate(r.revoked_at) && optionalDate(r.last_used_at)) ||
      !rows(v.webhooks,r=>text(r.name) && text(r.url) && /^https:\/\//.test(String(r.url)) && set(r.events,integrationEvents) && typeof r.enabled==='boolean' && integer(r.secret_version) && Number(r.secret_version)>0) ||
      !rows(v.deliveries,r=>['webhook_id','event_id','event_type'].every(k=>text(r[k])) && ['pending','sending','delivered','failed','cancelled'].includes(String(r.status)) &&
        integer(r.attempts) && Number(r.attempts)<=5 && (r.status_code===null || integer(r.status_code)) && optionalText(r.error) && date(r.available_at))) throw new Error('invalid_snapshot');
  // One-time secrets from mutation replies are deliberately excluded from stored state.
  return {api_version:'1',workspace_id:workspace,permissions:v.permissions,webhook_ready:v.webhook_ready,worker_online:v.worker_online,
    available_scopes:v.available_scopes,available_events:v.available_events,limits:v.limits,keys:v.keys,webhooks:v.webhooks,deliveries:v.deliveries} as WorkspaceIntegrations;
}

export function parseIntegrationLogs(v:unknown,workspace:string):IntegrationLogs {
  if (!record(v) || v.api_version!=='1' || v.workspace_id!==workspace || !optionalText(v.next_cursor) ||
    !rows(v.logs,r=>['api','webhook'].includes(String(r.kind)) && text(r.resource_id) && text(r.action) && integer(r.status_code) &&
      integer(r.duration_ms) && integer(r.attempt) && optionalText(r.error))) throw new Error('invalid_snapshot');
  return v as unknown as IntegrationLogs;
}

export function useWorkspaceIntegrations({platformUrl,workspaceId,user,logKind='',cursor=''}:IntegrationOptions) {
  const id=user?.id,role=user?.role;
  const scope=useMemo(()=>({platformUrl,workspaceId,id,role,logKind,cursor}),[platformUrl,workspaceId,id,role,logKind,cursor]);
  const current=useRef(scope);current.current=scope;
  const access:State['access']=!id ? 'login_required' : ['owner','admin','system_admin'].includes(role ?? '') ? 'ready' : 'forbidden';
  const empty=useCallback(():State=>({snapshot:null,logs:null,busy:access==='ready',error:'',stale:false,updatedAt:null,access}),[access]);
  const cacheKey=useMemo(()=>viewCacheKey('integrations',scope),[scope]);
  // A tab revisit resumes from the last good read; it stays busy (so actions stay locked) until revalidated.
  const resumed=useCallback(():State=>{const cached=access==='ready'?readViewCache<State>(cacheKey):undefined;return cached?{...cached,busy:true}:empty();},[access,cacheKey,empty]);
  const [stored,setStored]=useState<{scope:typeof scope;state:State}|null>(null);
  const stateRef=useRef(stored),mounted=useRef(false);
  // Last overview and log page shown, kept on screen while another log filter or page loads.
  const identity=JSON.stringify([platformUrl,workspaceId,id,role]);
  const shown=useRef<{identity:string;snapshot:State['snapshot'];logs:State['logs']}|null>(null);
  const pending=useRef<AbortController|null>(null);
  const perform=useCallback(async (action?:IntegrationAction):Promise<{secret:string|null;id:string|null}|null>=>{
    if (!mounted.current || current.current!==scope || access!=='ready' || pending.current) return null;
    const previous=stateRef.current?.scope===scope ? stateRef.current.state : resumed();
    if (action && (!previous.snapshot?.permissions.manage || previous.busy || previous.error || previous.stale || previous.updatedAt===null || Date.now()-previous.updatedAt>15000)) return null;
    const controller=new AbortController();pending.current=controller;
    const valid=()=>mounted.current && current.current===scope && pending.current===controller;
    const publish=(state:State)=>{const next={scope,state};stateRef.current=next;setStored(next);};
    publish({...previous,busy:true});
    let timer=0;
    let abort=()=>{};
    try {
      const deadline=new Promise<never>((_,reject)=>{
        abort=()=>reject(new Error('cancelled'));controller.signal.addEventListener('abort',abort,{once:true});
        timer=window.setTimeout(()=>{reject(new Error('timeout'));controller.abort();},8000);
      });
      const query=new URLSearchParams();if(logKind) query.set('kind',logKind);if(cursor) query.set('cursor',cursor);
      const reads=async()=>{
        const first=await workspaceRequest<unknown>(platformUrl,`/api/v1/workspace/integrations${action?.path ?? ''}`,{
          method:action?'POST':'GET',cache:'no-store',...(action?{headers:{'Content-Type':'application/json'},body:JSON.stringify(action.body)}:{})},controller.signal);
        const overview=parseIntegrations(first.body,workspaceId);
        // A committed mutation stays acknowledged even if its follow-up log read fails.
        let logs=previous.logs;
        if (!action) logs=parseIntegrationLogs((await workspaceRequest<unknown>(platformUrl,`/api/v1/workspace/integrations/logs?${query}`,{cache:'no-store'},controller.signal)).body,workspaceId);
        return {overview,logs,raw:first.body};
      };
      const result=await Promise.race([reads(),deadline]);
      if(!valid()) return null;
      const fresh:State={snapshot:result.overview,logs:result.logs,busy:false,error:'',stale:false,updatedAt:Date.now(),access:'ready'};
      publish(fresh);rememberView(cacheKey,fresh);
      return {secret:record(result.raw) && typeof result.raw.secret==='string' ? result.raw.secret : null,
        id:record(result.raw) && typeof result.raw.id==='string' ? result.raw.id : null};
    } catch(error) {
      if(!valid()) return null;
      if(error instanceof WorkspaceApiError && [401,403].includes(error.status)) {
        forgetView(cacheKey);shown.current=null;
        publish({...empty(),busy:false,access:error.status===401?'login_required':'forbidden'});
      } else publish({...previous,busy:false,stale:!!previous.snapshot,error:error instanceof Error && error.message==='invalid_snapshot'
        ? 'Phản hồi tích hợp không hợp lệ.' : error instanceof WorkspaceApiError && [409,422,503].includes(error.status)
        ? error.message : action ? 'Chưa xác nhận thao tác. Làm mới rồi thử lại cùng yêu cầu.' : 'Không thể tải tích hợp. Hãy làm mới.'});
      return null;
    } finally {
      window.clearTimeout(timer);controller.signal.removeEventListener('abort',abort);
      if(pending.current===controller) pending.current=null;
    }
  },[scope,access,empty,resumed,cacheKey,platformUrl,workspaceId,logKind,cursor]);
  useEffect(()=>{
    mounted.current=true;void perform();const interval=window.setInterval(()=>void perform(),5000);
    return ()=>{mounted.current=false;window.clearInterval(interval);const controller=pending.current;pending.current=null;controller?.abort();};
  },[perform]);
  const own=stored?.scope===scope && id ? stored.state : resumed();
  // A new log filter or page keeps the previous content until its own read lands (or fails), instead of blanking the page.
  const previewing=!own.snapshot && own.busy && !own.error && own.access==='ready' && shown.current?.identity===identity;
  const visible=previewing ? {...own,snapshot:shown.current!.snapshot,logs:shown.current!.logs} : own;
  if(own.snapshot && own.access==='ready') shown.current={identity,snapshot:own.snapshot,logs:own.logs};
  // Age only counts once a read has settled: a resumed copy is revalidating, not stale.
  const stale=visible.stale || (!visible.busy && !!visible.snapshot && visible.updatedAt!==null && Date.now()-visible.updatedAt>15000);
  return {...visible,stale,previewing,canMutate:access==='ready' && visible.access==='ready' && !!visible.snapshot?.permissions.manage && !visible.busy && !visible.error && !stale,
    refresh:useCallback(()=>perform(),[perform]),mutate:useCallback((action:IntegrationAction)=>perform(action),[perform])};
}
