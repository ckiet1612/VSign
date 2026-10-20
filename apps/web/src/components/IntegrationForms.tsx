import { useState } from 'react';
import { Check, X } from '../icons';
import type { IntegrationScope, IntegrationEvent, IntegrationWebhook } from '../../../../contracts/v1/integrations';
import type { IntegrationAction } from '../hooks/useWorkspaceIntegrations';
import { eventLabels, scopeLabels } from '../lib/integrationLabels';
interface BaseProps {disabled:boolean;onSubmit:(action:IntegrationAction)=>void;onClose:()=>void}

export function IntegrationKeyForm({disabled,onSubmit,onClose,scopes}:BaseProps & {scopes:IntegrationScope[]}) {
  const [name,setName]=useState(''),[selected,setSelected]=useState<IntegrationScope[]>(['models:read']);
  const [expires,setExpires]=useState(new Date(Date.now()+7*86400000).toISOString().slice(0,10));
  const [limit,setLimit]=useState(60);
  return <form className="integrations-form page-card" aria-label="Tạo khóa API" onSubmit={event=>{
    event.preventDefault();onSubmit({path:'/keys',body:{request_id:crypto.randomUUID(),name:name.trim(),scopes:selected,
      expires_at:new Date(`${expires}T23:59:59`).toISOString(),requests_per_minute:limit}});
  }}>
    <div className="integrations-form-heading"><h2>Khóa API mới</h2><button type="button" title="Đóng" aria-label="Đóng tạo khóa" onClick={onClose}><X size={18}/></button></div>
    <div className="integrations-fields">
      <label>Tên khóa<input aria-label="Tên khóa" value={name} onChange={e=>setName(e.target.value)} required maxLength={120} disabled={disabled}/></label>
      <label>Hết hạn<input aria-label="Hết hạn" type="date" value={expires} min={new Date().toISOString().slice(0,10)}
        max={new Date(Date.now()+364*86400000).toISOString().slice(0,10)} onChange={e=>setExpires(e.target.value)} required disabled={disabled}/></label>
      <label>Lượt gọi / phút<input aria-label="Lượt gọi / phút" type="number" min={1} max={60} value={limit} onChange={e=>setLimit(Number(e.target.value))} required disabled={disabled}/></label>
    </div>
    <fieldset disabled={disabled}><legend>Quyền truy cập</legend><div className="integrations-checkboxes">{scopes.map(scope=><label key={scope}>
      <input type="checkbox" checked={selected.includes(scope)} onChange={e=>setSelected(old=>e.target.checked ? [...old,scope] : old.filter(s=>s!==scope))}/>{scopeLabels[scope]}</label>)}</div></fieldset>
    <button type="submit" className="integrations-primary" disabled={disabled || !name.trim() || !selected.length}><Check size={16}/>Lưu khóa</button>
  </form>;
}

export function IntegrationWebhookForm({disabled,onSubmit,onClose,events,hook}:BaseProps & {events:IntegrationEvent[];hook?:IntegrationWebhook}) {
  const [name,setName]=useState(hook?.name ?? ''),[url,setUrl]=useState(hook?.url ?? '');
  const [selected,setSelected]=useState<IntegrationEvent[]>(hook?.events ?? ['evaluation.completed']);
  return <form className="integrations-form page-card" aria-label={hook?'Sửa đăng ký sự kiện':'Thêm webhook'} onSubmit={event=>{
    event.preventDefault();onSubmit({path:hook ? `/webhooks/${encodeURIComponent(hook.id)}/configure` : '/webhooks',body:hook
      ? {request_id:crypto.randomUUID(),events:selected} : {request_id:crypto.randomUUID(),name:name.trim(),url:url.trim(),events:selected}});
  }}>
    <div className="integrations-form-heading"><h2>{hook ? 'Sự kiện đăng ký' : 'Webhook mới'}</h2><button type="button" title="Đóng" aria-label="Đóng cấu hình webhook" onClick={onClose}><X size={18}/></button></div>
    {!hook && <div className="integrations-fields"><label>Tên kết nối<input aria-label="Tên kết nối" required maxLength={120} value={name} disabled={disabled} onChange={e=>setName(e.target.value)}/></label>
      <label className="integrations-url-field">Địa chỉ nhận<input aria-label="Địa chỉ nhận" type="url" placeholder="https://" required maxLength={2048} value={url} disabled={disabled} onChange={e=>setUrl(e.target.value)}/></label></div>}
    <fieldset disabled={disabled}><legend>Sự kiện</legend><div className="integrations-checkboxes">{events.map(event=><label key={event}>
      <input type="checkbox" checked={selected.includes(event)} onChange={e=>setSelected(old=>e.target.checked ? [...old,event] : old.filter(s=>s!==event))}/>{eventLabels[event]}</label>)}</div></fieldset>
    <button type="submit" className="integrations-primary" disabled={disabled || !selected.length}><Check size={16}/>Lưu webhook</button>
  </form>;
}
