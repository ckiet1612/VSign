import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { AuthenticatedUser } from '../../../../contracts/v1/workspace';
import type { WorkspaceEvaluationsResponse } from '../../../../contracts/v1/evaluations';
import { workspaceRequest, WorkspaceApiError } from '../lib/workspaceApi';
import { forgetView, readViewCache, rememberView, viewCacheKey } from '../lib/viewCache';

export interface EvaluationOptions { platformUrl: string; workspaceId: string; user: AuthenticatedUser | null }
export type EvaluationAction = {type:'create';request_id:string;model_id:string;snapshot_id:string} | {type:'cancel';id:string};
type Access = 'ready' | 'login_required' | 'forbidden';
interface State {snapshot:WorkspaceEvaluationsResponse | null;access:Access;error:string;busy:boolean;stale:boolean;updatedAt:number | null}
const initial = (access:Access):State => ({snapshot:null,access,error:'',busy:access === 'ready',stale:false,updatedAt:null});
const record = (v:unknown):v is Record<string,unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v:unknown):v is string => typeof v === 'string' && v.length > 0 && v.length <= 8192;
const hash = (v:unknown) => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const int = (v:unknown) => Number.isSafeInteger(v) && Number(v) >= 0;
const ratio = (v:unknown) => typeof v === 'number' && Number.isFinite(v) && v >= 0 && v <= 1;
const date = (v:unknown) => typeof v === 'string' && /^\d{4}-\d\d-\d\dT.*(?:Z|[+-]\d\d:\d\d)$/.test(v) && Number.isFinite(Date.parse(v));
const metric = (v:unknown) => v === null || ratio(v);
function metrics(v:unknown) {
  return record(v) && ['accuracy','macro_f1','false_accept_rate'].every(k => metric(v[k])) &&
    typeof v.latency_p95_ms === 'number' && Number.isFinite(v.latency_p95_ms) && v.latency_p95_ms > 0 &&
    ['negative_count','false_accepts','uncertain_count'].every(k => int(v[k])) && Number(v.false_accepts) <= Number(v.negative_count) &&
    Array.isArray(v.per_class) && v.per_class.length <= 256 && v.per_class.every(row => record(row) && text(row.label) &&
      int(row.support) && int(row.errors) && Number(row.errors) <= Number(row.support) && ['precision','recall','f1'].every(k => metric(row[k]))) &&
    new Set(v.per_class.map(row => row.label)).size === v.per_class.length;
}
function report(v:unknown) {
  return record(v) && v.schema_version === '1' && ['candidate_artifact_sha256','baseline_artifact_sha256','labels_sha256','dataset_snapshot_sha256'].every(k => hash(v[k])) &&
    ['source_run_id','preprocessing_version','protocol_version'].every(k => text(v[k])) &&
    ['confidence_threshold','margin_threshold','baseline_confidence_threshold','baseline_margin_threshold'].every(k => ratio(v[k])) &&
    typeof v.held_out === 'boolean' && typeof v.independent_negatives === 'boolean' && int(v.positive_count) && int(v.negative_count) &&
    metrics(v.candidate) && metrics(v.baseline) && record(v.runtime) && Object.values(v.runtime).every(text);
}
function gate(v:unknown) {
  return record(v) && typeof v.passed === 'boolean' && Array.isArray(v.checks) && v.checks.length > 0 &&
    v.checks.every(c => record(c) && text(c.name) && text(c.detail) && typeof c.passed === 'boolean') &&
    v.passed === v.checks.every(c => c.passed);
}
export function parseEvaluations(value:unknown,workspaceId:string):WorkspaceEvaluationsResponse {
  if (!record(value) || value.api_version !== '1' || value.workspace_id !== workspaceId || !record(value.permissions) ||
    typeof value.permissions.create !== 'boolean' || typeof value.permissions.cancel !== 'boolean' ||
    !(value.active_model_id === null || text(value.active_model_id)) || !record(value.workers) ||
    !Object.entries(value.workers).every(([key,v]) => ['onnx','coreml','pytorch'].includes(key) && typeof v === 'boolean') ||
    !Array.isArray(value.models) || !value.models.every(m => record(m) && text(m.id) && text(m.model_version) && text(m.backend) && typeof m.active === 'boolean') ||
    !Array.isArray(value.snapshots) || !value.snapshots.every(s => record(s) && ['id','dataset_version','dataset_name'].every(k => text(s[k])) && int(s.sample_count) && hash(s.sha256)) ||
    !Array.isArray(value.runs) || value.runs.length > 50 || !value.runs.every(r => record(r) &&
      ['id','model_id','baseline_model_id','model_version','baseline_model_version','snapshot_id','dataset_version','backend','requested_by'].every(k => text(r[k])) &&
      hash(r.snapshot_sha256) && int(r.sample_count) && int(r.progress) && Number(r.progress) <= Number(r.sample_count)*2 &&
      ['queued','running','completed','failed','cancelled'].includes(String(r.status)) && date(r.created_at) &&
      (r.started_at === null || date(r.started_at)) && (r.finished_at === null || date(r.finished_at)) &&
      (r.error === null || text(r.error)) && typeof r.baseline_current === 'boolean' &&
      (r.status === 'completed' ? report(r.report) && gate(r.gate) : r.report === null && r.gate === null)) ||
    [value.models,value.snapshots,value.runs].some(rows => new Set(rows.map(row => row.id)).size !== rows.length)) {
    throw new Error('invalid_snapshot');
  }
  return value as unknown as WorkspaceEvaluationsResponse;
}

export function useWorkspaceEvaluations({platformUrl,workspaceId,user}:EvaluationOptions) {
  const userId=user?.id,role=user?.role;
  const scope=useMemo(() => ({platformUrl,workspaceId,userId,role}),[platformUrl,workspaceId,userId,role]);
  const current=useRef(scope); current.current=scope;
  const access:Access=!userId ? 'login_required' : ['owner','admin','system_admin','reviewer'].includes(role ?? '') ? 'ready' : 'forbidden';
  const cacheKey=useMemo(() => viewCacheKey('evaluations',scope),[scope]);
  // A tab revisit resumes from the last good read; it stays busy (so actions stay locked) until revalidated.
  const resumed=useCallback(():State => {
    const cached=access === 'ready' ? readViewCache<State>(cacheKey) : undefined;
    return cached ? {...cached,busy:true} : initial(access);
  },[access,cacheKey]);
  const [stored,setStored]=useState<{scope:typeof scope;value:State} | null>(null);
  const stateRef=useRef(stored);
  const mounted=useRef(false);
  const pending=useRef<{controller:AbortController;timer:number} | null>(null);
  const perform=useCallback(async (action?:EvaluationAction):Promise<boolean> => {
    if (!mounted.current || current.current !== scope || access !== 'ready' || pending.current) return false;
    const previous=stateRef.current?.scope === scope ? stateRef.current.value : resumed();
    if (action && (!['owner','admin','system_admin'].includes(role ?? '') || !previous.snapshot || previous.error || previous.stale ||
      previous.busy || previous.updatedAt === null || Date.now()-previous.updatedAt > 15000)) return false;
    if (action && previous.snapshot) {
      const s=previous.snapshot;
      if (action.type === 'create' && (!s.permissions.create || !s.active_model_id || !s.models.some(m => m.id === action.model_id) ||
        !s.snapshots.some(d => d.id === action.snapshot_id) || s.runs.some(r => ['queued','running'].includes(r.status) && r.id !== action.request_id))) return false;
      if (action.type === 'cancel' && (!s.permissions.cancel || !s.runs.some(r => r.id === action.id && ['queued','running'].includes(r.status)))) return false;
    }
    const publish=(value:State) => { const next={scope,value}; stateRef.current=next;setStored(next); };
    const request={controller:new AbortController(),timer:0}; pending.current=request;
    const valid=() => mounted.current && current.current === scope && pending.current === request;
    publish({...previous,busy:true});
    let onAbort=() => {};
    try {
      const timeout=new Promise<never>((_resolve,reject) => {
        onAbort=() => reject(new Error('cancelled'));
        request.controller.signal.addEventListener('abort',onAbort,{once:true});
        request.timer=window.setTimeout(() => {reject(new Error('timeout'));request.controller.abort();},8000);
      });
      const path=action?.type === 'cancel' ? `/${encodeURIComponent(action.id)}/cancel` : '';
      const payload=action?.type === 'create' ? {request_id:action.request_id,model_id:action.model_id,snapshot_id:action.snapshot_id} : {};
      const {body}=await Promise.race([workspaceRequest<unknown>(platformUrl,`/api/v1/workspace/evaluations${path}`,{
        method:action ? 'POST' : 'GET',cache:'no-store',...(action ? {headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)} : {}),
      },request.controller.signal),timeout]);
      if (!valid()) return false;
      const fresh:State={snapshot:parseEvaluations(body,workspaceId),access:'ready',error:'',busy:false,stale:false,updatedAt:Date.now()};
      publish(fresh);
      rememberView(cacheKey,fresh);
      return true;
    } catch (error) {
      if (!valid()) return false;
      if (error instanceof WorkspaceApiError && [401,403].includes(error.status)) {
        forgetView(cacheKey);
        publish({...initial(error.status === 401 ? 'login_required' : 'forbidden'),busy:false});
      } else {
        publish({...previous,busy:false,stale:!!previous.snapshot,error:error instanceof Error && error.message === 'invalid_snapshot'
          ? 'Phản hồi đánh giá không hợp lệ.' : error instanceof WorkspaceApiError && [409,422].includes(error.status)
          ? 'Model hoặc bản dữ liệu không tương thích, hoặc trạng thái đã thay đổi. Hãy làm mới.'
          : action ? 'Chưa xác nhận được thao tác. Hãy làm mới rồi thử lại cùng yêu cầu.' : 'Không thể tải đánh giá. Hãy làm mới.'});
      }
      return false;
    } finally {
      window.clearTimeout(request.timer);
      request.controller.signal.removeEventListener('abort',onAbort);
      if (pending.current === request) pending.current=null;
    }
  },[scope,access,role,platformUrl,workspaceId,resumed,cacheKey]);
  useEffect(() => {
    mounted.current=true;
    void perform();
    const timer=window.setInterval(() => {void perform();},5000);
    return () => {mounted.current=false;window.clearInterval(timer);const request=pending.current;pending.current=null;
      if (request) {window.clearTimeout(request.timer);request.controller.abort();}};
  },[perform]);
  const visible=stored?.scope === scope && userId ? stored.value : resumed();
  // Age only counts once a read has settled: a resumed copy is revalidating, not stale.
  const stale=visible.stale || (!visible.busy && !!visible.snapshot && visible.updatedAt !== null && Date.now()-visible.updatedAt > 15000);
  return {...visible,stale,canMutate:visible.access === 'ready' && ['owner','admin','system_admin'].includes(role ?? '') &&
    !!visible.snapshot && !visible.busy && !visible.error && !stale,
    refresh:useCallback(() => perform(),[perform]),mutate:useCallback((action:EvaluationAction) => perform(action),[perform])};
}
