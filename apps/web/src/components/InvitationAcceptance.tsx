import { useEffect, useRef, useState } from 'react';
import type { InvitationDetails } from '../../../../contracts/v1/team';
import { parseInvitation } from '../hooks/useWorkspaceTeam';
import { teamRoleLabels } from '../lib/teamLabels';
import { WorkspaceApiError } from '../lib/workspaceApi';
import { workspaceHref } from '../lib/appRoutes';
import '../styles/team.css';

async function invitationRequest(platformUrl:string,path:string,body:Record<string,unknown>,controller:AbortController):Promise<unknown> {
  let timer=0,abort=()=>{};
  try {
    const deadline=new Promise<never>((_,reject)=>{abort=()=>reject(new Error('cancelled'));controller.signal.addEventListener('abort',abort,{once:true});
      timer=window.setTimeout(()=>{reject(new Error('timeout'));controller.abort();},8000);});
    const request=async()=>{
      const response=await fetch(`${platformUrl.replace(/\/$/,'')}/api/v1/invitations/${path}`,{
        method:'POST',credentials:'omit',cache:'no-store',referrerPolicy:'no-referrer',signal:controller.signal,
        headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      const value:unknown=await response.json();
      if(!response.ok) throw new WorkspaceApiError(response.status,typeof value==='object' && value && 'detail' in value && typeof value.detail==='string'?value.detail:'Lời mời không khả dụng.');
      return value;
    };
    return await Promise.race([request(),deadline]);
  } finally {window.clearTimeout(timer);controller.signal.removeEventListener('abort',abort);}
}
export function InvitationAcceptance({platformUrl}:{platformUrl:string}) {
  const [token,setToken]=useState(()=>new URLSearchParams(window.location.hash.slice(1)).get('token')??'');
  const [details,setDetails]=useState<InvitationDetails|null>(null),[password,setPassword]=useState(''),[name,setName]=useState('');
  const [error,setError]=useState(''),[busy,setBusy]=useState(true),[accepted,setAccepted]=useState(false),[attempt,setAttempt]=useState(0);
  const [requestId]=useState(()=>crypto.randomUUID());
  const mounted=useRef(false),write=useRef<AbortController|null>(null);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;write.current?.abort();};},[]);
  useEffect(()=>{
    window.history.replaceState(window.history.state,'',window.location.pathname+window.location.search);
    let meta=document.querySelector<HTMLMetaElement>('meta[name="referrer"]');const previous=meta?.content;
    if(!meta){meta=document.createElement('meta');meta.name='referrer';document.head.appendChild(meta);}meta.content='no-referrer';
    return()=>{if(previous!==undefined) meta!.content=previous;else meta!.remove();};
  },[]);
  useEffect(()=>{
    if(!token) {setBusy(false);if(!accepted) setError('Liên kết mời không hợp lệ hoặc đã bị xóa.');return;}
    let active=true;const controller=new AbortController();setBusy(true);setError('');
    if(!/^[A-Za-z0-9_-]{43}$/.test(token)){setBusy(false);setError('Liên kết mời không hợp lệ.');return;}
    void invitationRequest(platformUrl,'inspect',{token},controller).then(value=>{
      const next=parseInvitation(value);if(active){setDetails(next);setBusy(false);}
    }).catch(cause=>{if(active){setBusy(false);setError(cause instanceof WorkspaceApiError?cause.message:'Không thể kiểm tra lời mời.');}});
    return()=>{active=false;controller.abort();};
  },[platformUrl,token,attempt,accepted]);
  const submit=async()=>{
    if(!details || busy || !token || write.current) return;
    const controller=new AbortController();write.current=controller;setBusy(true);setError('');
    try {
      const value=await invitationRequest(platformUrl,'accept',{token,request_id:requestId,password,display_name:name},controller);
      if(!value || typeof value!=='object' || !('accepted' in value) || value.accepted!==true || !('workspace_id' in value) || value.workspace_id!==details.workspace_id || !('api_version' in value) || value.api_version!=='1') throw new Error('invalid_ack');
      if(mounted.current){setAccepted(true);setPassword('');setToken('');}
    } catch(cause) {if(mounted.current) setError(cause instanceof WorkspaceApiError?cause.message:'Chưa xác nhận tham gia. Thử lại cùng thông tin.');}
    finally {if(write.current===controller) write.current=null;if(mounted.current) setBusy(false);}
  };
  return <main className="team-page invitation-page" aria-labelledby="invitation-title"><header className="team-header"><h1 id="invitation-title">{accepted?'Đã tham gia workspace.':'Lời mời tham gia workspace'}</h1></header>
    {error && <p role="alert" className="team-warning">{error}</p>}
    {accepted?<><p>{details?.workspace_name}</p>{details && <p className="team-muted">Đăng nhập bằng email <strong className="selectable">{details.email}</strong> và mật khẩu vừa đặt.</p>}
      <a href={workspaceHref(details ? `?login=${encodeURIComponent(details.email)}` : '')}>Đăng nhập</a></>:details?<>
      <dl className="invitation-details"><dt>Workspace</dt><dd>{details.workspace_name}</dd><dt>Email</dt><dd className="selectable">{details.email}</dd><dt>Vai trò</dt><dd>{teamRoleLabels[details.role]}</dd><dt>Hết hạn</dt><dd>{new Date(details.expires_at).toLocaleString('vi-VN')}</dd></dl>
      <form className="team-form" onSubmit={e=>{e.preventDefault();void submit();}}><div className="team-fields">
        {!details.existing_account && <label>Tên hiển thị<small className="team-muted">Chỉ để hiển thị; đăng nhập bằng email ở trên.</small><input required maxLength={120} autoComplete="name" value={name} disabled={busy} onChange={e=>setName(e.target.value)}/></label>}
        <label>{details.existing_account?'Mật khẩu hiện tại':'Mật khẩu'}<input type="password" required minLength={details.existing_account?1:12} maxLength={256} autoComplete={details.existing_account?'current-password':'new-password'} value={password} disabled={busy} onChange={e=>setPassword(e.target.value)}/></label>
      </div><button type="submit" className="team-primary" disabled={busy}>{busy?'Đang xác nhận...':'Chấp nhận lời mời'}</button></form>
    </>:busy?<p role="status">Đang kiểm tra lời mời...</p>:token?<button type="button" onClick={()=>setAttempt(n=>n+1)}>Kiểm tra lại</button>:<a href={workspaceHref()}>Về workspace</a>}
  </main>;
}
