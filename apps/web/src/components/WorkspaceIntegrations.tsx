import { useEffect, useRef, useState } from 'react';
import { useTabMotion } from '../hooks/useTabMotion';
import type { AuthenticatedUser } from '../../../../contracts/v1/workspace';
import type { IntegrationWebhook } from '../../../../contracts/v1/integrations';
import { useWorkspaceIntegrations, type IntegrationAction } from '../hooks/useWorkspaceIntegrations';
import { ArrowLeft, ArrowRight, Copy, Plus, RefreshCw, Trash2, X, Play, Check, Inbox, Key } from '../icons';
import { CardHead, PageHero } from './PageChrome';
import { IntegrationKeyForm, IntegrationWebhookForm } from './IntegrationForms';
import { eventLabels, scopeLabels } from '../lib/integrationLabels';
import '../styles/integrations.css';
import { Bone, SkeletonRegion, TableBone, TextBone } from "./Skeleton";

interface Props {platformUrl:string;workspaceId:string;user:AuthenticatedUser|null}
type Tab='keys'|'webhooks'|'logs';
const date=(value:string|null)=>value ? new Date(value).toLocaleString('vi-VN') : 'Chưa có';
const statuses={pending:'Đang chờ',sending:'Đang gửi',delivered:'Đã giao',failed:'Thất bại',cancelled:'Đã hủy'};
const tones={pending:'',sending:'is-running',delivered:'is-success',failed:'is-failure',cancelled:''};
const errors:Record<string,string>={network_error:'Không kết nối được',http_error:'Bên nhận trả lỗi',unsafe_target:'Địa chỉ nhận không an toàn',
  delivery_timeout:'Quá thời gian gửi',worker_interrupted:'Worker bị gián đoạn',signing_key_unavailable:'Khóa ký chưa sẵn sàng',
  claim_inactive:'Lượt gửi đã hết hạn',webhook_disabled:'Webhook đã tắt',scope_denied:'Không đủ quyền',key_inactive:'Khóa hết hạn hoặc đã thu hồi',rate_limited:'Vượt hạn mức'};

function IntegrationWorkspace(props:Props) {
  const [tab,setTab]=useState<Tab>('keys'),[form,setForm]=useState<'key'|'webhook'|IntegrationWebhook|null>(null);
  const [secret,setSecret]=useState<string|null>(null),[message,setMessage]=useState(''),[copied,setCopied]=useState(false);
  const [pending,setPending]=useState<IntegrationAction|null>(null);
  const [confirm,setConfirm]=useState<{title:string;action:IntegrationAction}|null>(null);
  const [logKind,setLogKind]=useState(''),[cursor,setCursor]=useState(''),[history,setHistory]=useState<string[]>([]);
  const reader=useWorkspaceIntegrations({...props,logKind,cursor});
  const tabList=useRef<HTMLElement>(null),tabPanel=useRef<HTMLDivElement>(null);
  useTabMotion(tabList,['keys','webhooks','logs'].indexOf(tab),{panel:tabPanel,mounted:reader.access==='ready'});
  useEffect(()=>{
    if(reader.access!=='ready' || reader.stale || reader.error) {setSecret(null);setCopied(false);}
  },[reader.access,reader.stale,reader.error]);
  const data=reader.snapshot;
  const run=async(action:IntegrationAction)=>{
    setSecret(null);setMessage('');setPending(action);
    const result=await reader.mutate(action);
    if(result) {
      setPending(null);setForm(null);setConfirm(null);setCopied(false);
      if(result.secret) setSecret(result.secret);
      else if(action.path==='/keys' || action.path==='/webhooks' || action.path.endsWith('/rotate')) setMessage('Yêu cầu đã tồn tại. Khóa bí mật không được hiển thị lại; cần thu hồi hoặc đổi khóa.');
      else setMessage(action.path.endsWith('/test') ? 'Đã xếp lượt kiểm tra vào hàng chờ.' : 'Đã cập nhật.');
    }
  };
  const selectTab=(next:Tab)=>{setTab(next);setSecret(null);setForm(null);setConfirm(null);setMessage('');};
  const disabled=!reader.canMutate || pending!==null;
  return <section className="workspace-page integrations-page" aria-labelledby="workspace-page-title">
    <PageHero title={props.user?.role==='system_admin'?'Tích hợp & API':'Tích hợp'}>
      {reader.access==='ready' && <nav ref={tabList} className="integrations-tabs page-tabs" role="tablist" aria-label="Tích hợp">{([['keys','Khóa API'],['webhooks','Webhooks'],['logs','Nhật ký']] as const).map(([id,label])=>
        <button key={id} type="button" role="tab" id={`integration-tab-${id}`} aria-selected={tab===id} tabIndex={tab===id?0:-1} aria-controls="integration-panel" onClick={()=>selectTab(id)} onKeyDown={event=>{
          const tabs:Tab[]=['keys','webhooks','logs'];const i=tabs.indexOf(id);
          const next=event.key==='ArrowRight'?tabs[(i+1)%3]:event.key==='ArrowLeft'?tabs[(i+2)%3]:event.key==='Home'?'keys':event.key==='End'?'logs':null;
          if(next){event.preventDefault();selectTab(next);document.getElementById(`integration-tab-${next}`)?.focus();}
        }}>{label}</button>)}</nav>}
      <button type="button" className="page-icon-button" aria-label="Làm mới tích hợp" title="Làm mới tích hợp" disabled={reader.busy} data-busy={reader.busy || undefined} onClick={()=>void reader.refresh()}><RefreshCw size={18}/></button></PageHero>
    {reader.access!=='ready' ? <p role="status">{reader.access==='forbidden'?'Bạn không có quyền quản lý tích hợp.':'Chưa xác nhận quyền workspace.'}</p> : <>
      {reader.error && <p role="alert" className="integrations-warning">{reader.error}</p>}
      {reader.stale && <p role="status" className="integrations-muted">Dữ liệu đã cũ. Các thao tác tạm khóa.</p>}
      {message && <p role="status" className="integrations-muted">{message}</p>}
      {secret && !reader.stale && !reader.error && <section className="integrations-secret page-card" aria-label="Khóa bí mật">
        <div className="integrations-form-heading"><h2>Khóa bí mật · Chỉ hiển thị lần này</h2><button type="button" aria-label="Đóng khóa bí mật" title="Đóng khóa bí mật" onClick={()=>setSecret(null)}><X size={18}/></button></div>
        <code>{secret}</code><button type="button" aria-label="Sao chép khóa" title="Sao chép khóa" onClick={()=>void navigator.clipboard.writeText(secret).then(()=>setCopied(true)).catch(()=>setMessage('Không thể truy cập bộ nhớ sao chép.'))}>{copied?<Check size={18}/>:<Copy size={18}/>}</button>
      </section>}
      {pending && !reader.busy && <div className="integrations-retry" role="status"><span>Yêu cầu chưa được xác nhận.</span>
        <button type="button" disabled={!reader.canMutate} onClick={()=>void run(pending)}><RefreshCw size={16}/>Thử lại yêu cầu</button>
        <button type="button" onClick={()=>{setPending(null);setForm(null);setConfirm(null);}}>Đóng yêu cầu</button></div>}
      {confirm && <section className="integrations-confirm page-card" aria-label="Xác nhận thay đổi"><h2>{confirm.title}</h2>
        <button type="button" disabled={disabled} onClick={()=>void run(confirm.action)}><Check size={16}/>Xác nhận</button>
        <button type="button" disabled={reader.busy} onClick={()=>setConfirm(null)}>Hủy</button></section>}
      {!data ? reader.busy ? <SkeletonRegion label="Đang tải tích hợp...">
        <div className="integrations-toolbar"><TextBone w={300} size={12} line={19} style={{ margin: '8px 0' }} /><Bone w={112} h={40} r="var(--radius-12)" /></div>
        <div className="integrations-table page-card"><TableBone columns={['stack', '60%', '40%', '65%', '65%', 'pill', 0]} rows={3} /></div>
      </SkeletonRegion> : <p role="status" className="integrations-empty">Chưa có dữ liệu tích hợp.</p> : <div ref={tabPanel} id="integration-panel" role="tabpanel" aria-labelledby={`integration-tab-${tab}`} data-previewing={reader.previewing || undefined}>
        {tab==='keys' && <>
          <div className="integrations-toolbar"><p className="integrations-muted">Tối đa {data.limits.key_per_minute} lượt/khóa/phút · {data.limits.workspace_per_minute} lượt/workspace/phút</p>
            <button type="button" className="integrations-primary" disabled={disabled} onClick={()=>setForm('key')}><Plus size={16}/>Tạo khóa</button></div>
          {form==='key' && <IntegrationKeyForm disabled={disabled} scopes={data.available_scopes} onClose={()=>setForm(null)} onSubmit={a=>void run(a)}/>}
          {!data.keys.length ? <p className="integrations-empty page-card"><Key size={22} aria-hidden="true" />Chưa có khóa API.</p> : <div className="integrations-table page-card" tabIndex={0} role="region" aria-label="Danh sách khóa API"><table>
            <thead><tr><th>Tên khóa</th><th>Quyền</th><th>Lượt/phút</th><th>Hết hạn</th><th>Dùng gần nhất</th><th>Trạng thái</th><th><span className="sr-only">Thao tác</span></th></tr></thead>
            <tbody>{data.keys.map(key=><tr key={key.id}><th scope="row">{key.name}<small>{key.prefix}...</small></th><td>{key.scopes.map(s=><span className="integrations-line" key={s}>{scopeLabels[s]}</span>)}</td><td>{key.requests_per_minute}</td>
              <td>{date(key.expires_at)}</td><td>{date(key.last_used_at)}</td><td><span className={`page-status ${key.revoked_at || Date.parse(key.expires_at)<=Date.now() ? '' : 'is-success'}`}>{key.revoked_at?'Đã thu hồi':Date.parse(key.expires_at)<=Date.now()?'Hết hạn':'Đang hoạt động'}</span></td>
              <td><button type="button" title={`Thu hồi ${key.name}`} aria-label={`Thu hồi ${key.name}`} disabled={disabled || !!key.revoked_at} onClick={()=>setConfirm({title:`Thu hồi khóa ${key.name}?`,action:{path:`/keys/${encodeURIComponent(key.id)}/revoke`,body:{}}})}><Trash2 size={18}/></button></td></tr>)}</tbody>
          </table></div>}
        </>}
        {tab==='webhooks' && <>
          <div className="integrations-toolbar"><p className="integrations-muted">{reader.snapshot?.worker_online?'Worker đang kết nối':'Worker chưa kết nối'}</p>
            <button type="button" className="integrations-primary" disabled={disabled || !data.webhook_ready} onClick={()=>setForm('webhook')}><Plus size={16}/>Thêm webhook</button></div>
          {!data.webhook_ready && <p className="integrations-warning" role="status">Khóa mã hóa webhook của máy chủ chưa sẵn sàng.</p>}
          <p className="integrations-muted">Tối đa {data.limits.webhook_per_minute} lượt/địa chỉ/phút · {data.limits.webhook_workspace_per_minute} lượt/workspace/phút</p>
          {(form==='webhook' || (form && typeof form==='object')) && <IntegrationWebhookForm key={typeof form==='object'?form.id:'new'} disabled={disabled} events={data.available_events}
            hook={typeof form==='object'?form:undefined} onClose={()=>setForm(null)} onSubmit={a=>void run(a)}/>}
          {!data.webhooks.length ? <p className="integrations-empty page-card"><Inbox size={22} aria-hidden="true" />Chưa có webhook.</p> : <div className="integrations-webhooks">{data.webhooks.map(hook=><article className="integrations-webhook page-card" key={hook.id}>
            <div className="integrations-webhook-title"><h2>{hook.name}</h2><label><input type="checkbox" role="switch" aria-label={`Bật ${hook.name}`} checked={hook.enabled} disabled={disabled}
              onChange={e=>{const enabled=e.target.checked;setConfirm({title:`${enabled?'Bật':'Tắt'} webhook ${hook.name}?`,action:{path:`/webhooks/${encodeURIComponent(hook.id)}/configure`,body:{request_id:crypto.randomUUID(),enabled}}});}}/>Đang {hook.enabled?'bật':'tắt'}</label></div>
            <p className="integrations-webhook-url">{hook.url}</p><div className="integrations-subscriptions">{hook.events.map(event=><span key={event}>{eventLabels[event]}</span>)}</div>
            <div className="integrations-actions"><button type="button" disabled={disabled} onClick={()=>setForm(hook)}>Sự kiện đăng ký</button>
              <button type="button" disabled={disabled || !hook.enabled || !data.webhook_ready} onClick={()=>void run({path:`/webhooks/${encodeURIComponent(hook.id)}/test`,body:{request_id:crypto.randomUUID()}})}><Play size={16}/>Gửi thử</button>
              <button type="button" disabled={disabled || !data.webhook_ready} onClick={()=>setConfirm({title:`Đổi khóa ký cho ${hook.name}?`,action:{path:`/webhooks/${encodeURIComponent(hook.id)}/rotate`,body:{request_id:crypto.randomUUID()}}})}><RefreshCw size={16}/>Đổi khóa ký</button></div>
          </article>)}</div>}
          {!!data.deliveries.length && <section className="page-card" aria-labelledby="integration-deliveries-title"><CardHead icon={Inbox} id="integration-deliveries-title" title="Lượt giao gần đây" /><div className="integrations-table" tabIndex={0} role="region" aria-label="Lượt giao webhook"><table><thead><tr><th>Thời điểm</th><th>Kết nối</th><th>Sự kiện</th><th>Trạng thái</th><th>Số lần thử</th><th>Kết quả</th><th><span className="sr-only">Thao tác</span></th></tr></thead>
            <tbody>{data.deliveries.map(row=><tr key={row.id}><td>{date(row.created_at)}</td><td>{data.webhooks.find(h=>h.id===row.webhook_id)?.name ?? row.webhook_id}</td><td>{eventLabels[row.event_type] ?? row.event_type}</td>
              <td><span className={`page-status ${tones[row.status]}`}>{statuses[row.status]}</span>{row.status==='pending' && <small>{date(row.available_at)}</small>}</td><td>{row.attempts}</td><td>{row.status_code ?? ''}{row.error && <small>{errors[row.error] ?? 'Không thể hoàn tất'}</small>}</td>
              <td>{row.status==='failed' && <button type="button" title="Gửi lại" aria-label={`Gửi lại ${row.id}`} disabled={disabled || !data.webhooks.some(h=>h.id===row.webhook_id && h.enabled)} onClick={()=>void run({path:`/deliveries/${encodeURIComponent(row.id)}/retry`,body:{request_id:crypto.randomUUID()}})}><RefreshCw size={18}/></button>}</td></tr>)}</tbody></table></div></section>}
        </>}
        {tab==='logs' && <>
          <div className="integrations-toolbar"><label>Loại nhật ký<select aria-label="Loại nhật ký" value={logKind} onChange={e=>{setLogKind(e.target.value);setCursor('');setHistory([]);}}><option value="">Tất cả</option><option value="api">API</option><option value="webhook">Webhook</option></select></label>
            <div className="integrations-actions"><button type="button" title="Trang trước" aria-label="Trang nhật ký trước" disabled={!history.length || reader.busy} onClick={()=>{setCursor(history[history.length-1]);setHistory(old=>old.slice(0,-1));}}><ArrowLeft size={18}/></button>
              <button type="button" title="Trang tiếp" aria-label="Trang nhật ký tiếp" disabled={!reader.logs?.next_cursor || reader.busy} onClick={()=>{setHistory(old=>[...old,cursor]);setCursor(reader.logs!.next_cursor!);}}><ArrowRight size={18}/></button></div></div>
          {!reader.logs?.logs.length ? <p className="integrations-empty page-card"><Inbox size={22} aria-hidden="true" />Chưa có nhật ký tích hợp.</p> : <div className="integrations-table page-card" tabIndex={0} role="region" aria-label="Nhật ký tích hợp"><table><thead><tr><th>Thời điểm</th><th>Loại</th><th>Thao tác</th><th>Kết quả</th><th>Thời gian</th><th>Lần thử</th></tr></thead>
            <tbody>{reader.logs.logs.map(log=><tr key={log.id}><td>{date(log.created_at)}</td><td>{log.kind==='api'?'API':'Webhook'}<small>{log.resource_id.slice(0,8)}</small></td><td>{eventLabels[log.action] ?? ({models:'Đọc mô hình',snapshots:'Đọc bản dữ liệu',evaluations:'Đọc đánh giá'} as Record<string,string>)[log.action] ?? log.action}</td>
              <td>{log.status_code || 'Chưa nhận phản hồi'}{log.error && <small>{errors[log.error] ?? 'Không thể hoàn tất'}</small>}</td><td>{log.duration_ms} ms</td><td>{log.attempt || '-'}</td></tr>)}</tbody></table></div>}
        </>}
      </div>}
    </>}
  </section>;
}

export function WorkspaceIntegrations(props:Props) {
  return <IntegrationWorkspace key={`${props.platformUrl}:${props.workspaceId}:${props.user?.id}:${props.user?.role}`} {...props}/>;
}
