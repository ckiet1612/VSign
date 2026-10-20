import { useEffect, useRef, useState } from 'react';
import type { AuthenticatedUser } from '../../../../contracts/v1/workspace';
import type { GrantableRole, TeamChange, TeamMember, TeamTab } from '../../../../contracts/v1/team';
import { useWorkspaceTeam, type TeamAction } from '../hooks/useWorkspaceTeam';
import { useTabMotion } from '../hooks/useTabMotion';
import { ArrowLeft, ArrowRight, Check, Copy, Mail, Pause, Play, Plus, RefreshCw, ShieldCheck, Trash2, UsersRound, X } from '../icons';
import { PageHero } from './PageChrome';
import { memberStatusLabels, permissionLabels, teamActionLabels, teamRoleLabels } from '../lib/teamLabels';
import { TeamMemberFilter } from './TeamMemberFilter';
import '../styles/team.css';
import { Bone, SkeletonRegion, TableBone, TextBone } from "./Skeleton";

interface Props {platformUrl:string; workspaceId:string; user:AuthenticatedUser|null}
const tabs:[TeamTab,string][]=[['members','Thành viên'],['roles','Vai trò'],['invitations','Lời mời'],['audit','Nhật ký quyền']];
const invitationStatuses={pending:'Đang chờ',accepted:'Đã chấp nhận',expired:'Hết hạn',revoked:'Đã thu hồi'};
const date=(value:string)=>new Date(value).toLocaleString('vi-VN');
function describe(value:TeamChange|null) {
  return value ? [value.role && teamRoleLabels[value.role],value.status && memberStatusLabels[value.status],value.email].filter(Boolean).join(' · ') || 'Không có' : 'Không có';
}

function TeamWorkspace(props:Props) {
  const [tab,setTab]=useState<TeamTab>('members'),[search,setSearch]=useState(''),[draftSearch,setDraftSearch]=useState('');
  const [cursor,setCursor]=useState(''),[history,setHistory]=useState<string[]>([]);
  const [actionFilter,setActionFilter]=useState(''),[memberId,setMemberId]=useState(''),[memberName,setMemberName]=useState(''),[fromAt,setFromAt]=useState(''),[toAt,setToAt]=useState('');
  const [form,setForm]=useState(false),[email,setEmail]=useState(''),[inviteRole,setInviteRole]=useState<GrantableRole>('operator'),[days,setDays]=useState(7);
  const [secret,setSecret]=useState<string|null>(null),[copied,setCopied]=useState(false),[message,setMessage]=useState('');
  const [pending,setPending]=useState<TeamAction|null>(null),[confirm,setConfirm]=useState<{title:string;action:TeamAction}|null>(null);
  const selection=useRef(0),mounted=useRef(true);
  const currentSecret=useRef(secret);currentSecret.current=secret;
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
  const reader=useWorkspaceTeam({...props,tab,search,cursor,action:actionFilter,memberId,
    fromAt:fromAt?new Date(fromAt).toISOString():'',toAt:toAt?new Date(toAt).toISOString():''});
  const data=reader.snapshot,overview=data?.overview;
  const tabList=useRef<HTMLElement>(null),tabPanel=useRef<HTMLDivElement>(null);
  useTabMotion(tabList,tabs.findIndex(([id])=>id===tab),{panel:tabPanel,mounted:reader.access==='ready'});
  useEffect(()=>{if(reader.stale || reader.error || reader.access!=='ready') {setSecret(null);setCopied(false);}},[reader.stale,reader.error,reader.access]);
  const resetPage=()=>{setCursor('');setHistory([]);};
  const selectTab=(next:TeamTab)=>{selection.current++;setTab(next);resetPage();setSecret(null);setCopied(false);setForm(false);setConfirm(null);setPending(null);setMessage('');};
  const run=async(action:TeamAction)=>{
    const version=selection.current;setPending(action);setSecret(null);setMessage('');
    const result=await reader.mutate(action);
    if(!mounted.current || version!==selection.current || !result) return;
    setPending(null);setConfirm(null);setForm(false);setCopied(false);resetPage();
    if(action.path.startsWith('/members/')) {setSearch('');setDraftSearch('');}
    if(result.secret) setSecret(`${window.location.origin}/invite#token=${encodeURIComponent(result.secret)}`);
    else setMessage(action.path==='/invitations'?'Yêu cầu đã được xử lý. Liên kết mời không được hiển thị lại.':'Đã cập nhật.');
  };
  const memberAction=(member:TeamMember,fields:Record<string,string>,title:string)=>setConfirm({title,action:{path:`/members/${encodeURIComponent(member.id)}/update`,body:{request_id:crypto.randomUUID(),expected_revision:member.revision,...fields}}});
  const disabled=!reader.canMutate || pending!==null;
  const paginate=<div className="team-actions"><button type="button" title="Trang trước" aria-label="Trang trước" disabled={!history.length || reader.busy} onClick={()=>{setCursor(history[history.length-1]);setHistory(old=>old.slice(0,-1));}}><ArrowLeft size={18}/></button>
    <button type="button" title="Trang tiếp" aria-label="Trang tiếp" disabled={!data?.next_cursor || reader.busy} onClick={()=>{setHistory(old=>[...old,cursor]);setCursor(data!.next_cursor!);}}><ArrowRight size={18}/></button></div>;
  return <section className="workspace-page team-page" aria-labelledby="workspace-page-title">
    <PageHero title={props.user?.role==='system_admin'?'Tài khoản & quyền':'Thành viên & quyền'}>
      {reader.access==='ready' && <nav ref={tabList} className="team-tabs page-tabs" role="tablist" aria-label="Thành viên và quyền">{tabs.map(([id,label],i)=><button type="button" key={id} role="tab" id={`team-tab-${id}`} aria-selected={tab===id} tabIndex={tab===id?0:-1} aria-controls="team-panel" onClick={()=>selectTab(id)} onKeyDown={e=>{
        const next=e.key==='ArrowRight'?tabs[(i+1)%4][0]:e.key==='ArrowLeft'?tabs[(i+3)%4][0]:e.key==='Home'?'members':e.key==='End'?'audit':null;
        if(next){e.preventDefault();selectTab(next);document.getElementById(`team-tab-${next}`)?.focus();}
      }}>{label}</button>)}</nav>}
      <button type="button" className="page-icon-button" title="Làm mới thành viên" aria-label="Làm mới thành viên" disabled={reader.busy} data-busy={reader.busy || undefined} onClick={()=>void reader.refresh()}><RefreshCw size={18}/></button></PageHero>
    {reader.access!=='ready'?<p role="status">{reader.access==='forbidden'?'Bạn không có quyền quản lý thành viên.':'Chưa xác nhận quyền workspace.'}</p>:<>
      {reader.error && <p role="alert" className="team-warning">{reader.error}</p>}
      {reader.stale && <p role="status" className="team-muted">Dữ liệu đã cũ. Các thao tác tạm khóa.</p>}
      {message && <p role="status" className="team-muted">{message}</p>}
      {pending && !reader.busy && <div className="team-confirm" role="region" aria-label="Thao tác chưa xác nhận"><p>Chưa xác nhận thao tác.</p><button type="button" disabled={!reader.canMutate} onClick={()=>void run(pending)}>Thử lại cùng yêu cầu</button><button type="button" onClick={()=>{setPending(null);setConfirm(null);setForm(false);}}>Đóng</button></div>}
      {secret && !reader.stale && !reader.error && <section className="team-secret page-card" aria-label="Liên kết mời một lần">
        <div className="team-header"><h2>Liên kết mời · Chỉ hiển thị lần này</h2><button type="button" title="Ẩn liên kết" aria-label="Ẩn liên kết" onClick={()=>setSecret(null)}><X size={18}/></button></div>
        <code>{secret}</code><button type="button" onClick={()=>{const copiedSecret=secret;void navigator.clipboard.writeText(copiedSecret).then(()=>{
          if(mounted.current && currentSecret.current===copiedSecret) setCopied(true);
        }).catch(()=>{if(mounted.current && currentSecret.current===copiedSecret) setMessage('Không thể sao chép liên kết.');});}}>{copied?<Check size={16}/>:<Copy size={16}/>} {copied?'Đã sao chép':'Sao chép liên kết'}</button>
      </section>}
      {confirm && <section className="team-confirm page-card" aria-label="Xác nhận thay đổi"><h2>{confirm.title}</h2><button type="button" className="team-primary" disabled={disabled} onClick={()=>void run(confirm.action)}>Xác nhận</button><button type="button" disabled={!!pending} onClick={()=>setConfirm(null)}>Hủy</button></section>}
      {!data && reader.busy && <SkeletonRegion label="Đang tải thành viên...">
        <div className="team-toolbar"><div className="team-search"><TextBone w={104} /><div><Bone h={40} r="var(--radius-12)" /><Bone w={56} h={40} r="var(--radius-12)" /></div></div>
          <TextBone w={220} size={12} line={19} style={{ margin: '8px 0' }} /><div className="team-actions"><Bone w={40} h={40} r="var(--radius-12)" /><Bone w={40} h={40} r="var(--radius-12)" /></div></div>
        <div className="team-table page-card"><TableBone lead columns={['100%', '55%', 'pill', '60%', 0]} rows={4} /></div>
      </SkeletonRegion>}
      {data && overview && <div ref={tabPanel} role="tabpanel" id="team-panel" aria-labelledby={`team-tab-${tab}`} aria-busy={reader.busy} data-previewing={reader.previewing || undefined}>
        {tab==='members' && <>
          <div className="team-toolbar"><form className="team-search" onSubmit={e=>{e.preventDefault();setSearch(draftSearch.trim());resetPage();}}><label htmlFor="team-search">Tìm thành viên</label><div><input id="team-search" type="search" maxLength={120} value={draftSearch} onChange={e=>setDraftSearch(e.target.value)}/><button type="submit" disabled={reader.busy}>Tìm</button></div></form>
            <p className="team-muted">{overview.counts.active} hoạt động · {overview.counts.suspended} tạm khóa · {overview.counts.removed} đã gỡ</p>{paginate}</div>
          {!overview.members.length?<p className="team-empty page-card"><UsersRound size={22} aria-hidden="true" />Không tìm thấy thành viên.</p>:<div className="team-table page-card" role="region" aria-label="Danh sách thành viên" tabIndex={0}><table><thead><tr><th>Thành viên</th><th>Vai trò</th><th>Trạng thái</th><th>Tham gia</th><th><span className="sr-only">Thao tác</span></th></tr></thead><tbody>{overview.members.map(member=><tr key={member.id}>
            <td><div className="team-person"><span className="team-avatar" aria-hidden="true">{member.display_name.trim().charAt(0).toUpperCase() || "?"}</span><div><strong>{member.display_name}</strong><small>{member.email}</small></div></div></td><td>{member.protected || member.status==='removed'?teamRoleLabels[member.role]:<select aria-label={`Vai trò của ${member.display_name}`} value={member.role} disabled={disabled} onChange={e=>memberAction(member,{role:e.target.value},`Đổi vai trò của ${member.display_name} thành ${teamRoleLabels[e.target.value as GrantableRole]}?`)}>{overview.grantable_roles.map(role=><option key={role} value={role}>{teamRoleLabels[role]}</option>)}</select>}</td>
            <td><span className={`page-status ${member.status==='active' && member.active ? 'is-success' : member.status==='suspended' ? 'is-warning' : ''}`}>{memberStatusLabels[member.status]}</span>{!member.active && member.status==='active' && <small>Tài khoản đã vô hiệu hóa</small>}</td><td>{date(member.created_at)}</td><td>{member.protected?<span className="team-protected" title="Thành viên được bảo vệ"><ShieldCheck size={16}/><span className="sr-only">Được bảo vệ</span></span>:member.status!=='removed' && <div className="team-actions">
              <button type="button" title={member.status==='suspended'?'Khôi phục':'Tạm khóa'} aria-label={`${member.status==='suspended'?'Khôi phục':'Tạm khóa'} ${member.display_name}`} disabled={disabled} onClick={()=>memberAction(member,{status:member.status==='suspended'?'active':'suspended'},`${member.status==='suspended'?'Khôi phục':'Tạm khóa'} ${member.display_name}?`)}>{member.status==='suspended'?<Play size={18}/>:<Pause size={18}/>}</button>
              <button type="button" title="Gỡ thành viên" aria-label={`Gỡ ${member.display_name}`} disabled={disabled} onClick={()=>memberAction(member,{status:'removed'},`Gỡ ${member.display_name} khỏi workspace?`)}><Trash2 size={18}/></button></div>}</td></tr>)}</tbody></table></div>}
        </>}
        {tab==='roles' && <div className="team-table page-card" role="region" aria-label="Quyền theo vai trò" tabIndex={0}><table><thead><tr><th>Quyền</th>{data.roles.map(role=><th key={role.id}>{teamRoleLabels[role.id]}</th>)}</tr></thead><tbody>{Array.from(new Set(data.roles.flatMap(role=>role.permissions))).map(permission=><tr key={permission}><th scope="row">{permissionLabels[permission]}</th>{data.roles.map(role=><td key={role.id}>{role.permissions.includes(permission)?<><Check size={17}/><span className="sr-only">Có quyền</span></>:<span aria-label="Không có quyền">-</span>}</td>)}</tr>)}</tbody></table></div>}
        {tab==='invitations' && <>
          <div className="team-toolbar"><button type="button" className="team-primary" disabled={disabled} onClick={()=>{setForm(true);setInviteRole(overview.grantable_roles.includes('operator')?'operator':overview.grantable_roles[0]);setSecret(null);}}><Plus size={16}/>Mời thành viên</button>{paginate}</div>
          {form && <form className="team-form page-card" aria-label="Mời thành viên" onSubmit={e=>{e.preventDefault();void run({path:'/invitations',body:{request_id:crypto.randomUUID(),email:email.trim(),role:inviteRole,expires_in_days:days}});}}>
            <div className="team-fields"><label>Email người nhận<input type="email" required maxLength={320} value={email} disabled={disabled} onChange={e=>setEmail(e.target.value)}/></label><label>Vai trò<select value={inviteRole} disabled={disabled} onChange={e=>setInviteRole(e.target.value as GrantableRole)}>{overview.grantable_roles.map(role=><option key={role} value={role}>{teamRoleLabels[role]}</option>)}</select></label><label>Hết hạn sau (ngày)<input type="number" min={1} max={14} required value={days} disabled={disabled} onChange={e=>setDays(Number(e.target.value))}/></label></div>
            <div className="team-actions"><button type="submit" className="team-primary" disabled={disabled}>Tạo lời mời</button><button type="button" disabled={!!pending} onClick={()=>setForm(false)}>Hủy</button></div></form>}
          {!data.invitations.length?<p className="team-empty page-card"><Mail size={22} aria-hidden="true" />Chưa có lời mời.</p>:<div className="team-table page-card" role="region" aria-label="Danh sách lời mời" tabIndex={0}><table><thead><tr><th>Email</th><th>Vai trò</th><th>Trạng thái</th><th>Hết hạn</th><th><span className="sr-only">Thao tác</span></th></tr></thead><tbody>{data.invitations.map(invite=><tr key={invite.id}><td>{invite.email}<small>{date(invite.created_at)}</small></td><td>{teamRoleLabels[invite.role]}</td><td><span className={`page-status ${invite.status==='accepted' ? 'is-success' : invite.status==='pending' ? 'is-running' : ''}`}>{invitationStatuses[invite.status]}</span></td><td>{date(invite.expires_at)}</td><td>{invite.status==='pending' && overview.grantable_roles.includes(invite.role) && <button type="button" title="Thu hồi lời mời" aria-label={`Thu hồi lời mời ${invite.email}`} disabled={disabled} onClick={()=>setConfirm({title:`Thu hồi lời mời cho ${invite.email}?`,action:{path:`/invitations/${encodeURIComponent(invite.id)}/revoke`,body:{request_id:crypto.randomUUID()}}})}><Trash2 size={18}/></button>}</td></tr>)}</tbody></table></div>}
        </>}
        {tab==='audit' && <>
          <div className="team-toolbar team-filters page-card"><label>Thao tác<select value={actionFilter} onChange={e=>{setActionFilter(e.target.value);resetPage();}}><option value="">Tất cả</option>{Object.entries(teamActionLabels).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
            <TeamMemberFilter {...props} selectedId={memberId} selectedName={memberName} onSelect={(id,name)=>{setMemberId(id);setMemberName(name);resetPage();}}/>
            <label>Từ ngày<input type="datetime-local" value={fromAt} onChange={e=>{setFromAt(e.target.value);resetPage();}}/></label><label>Đến ngày<input type="datetime-local" value={toAt} onChange={e=>{setToAt(e.target.value);resetPage();}}/></label>{paginate}</div>
          {!data.events.length?<p className="team-empty page-card"><ShieldCheck size={22} aria-hidden="true" />Chưa có nhật ký quyền phù hợp.</p>:<div className="team-table page-card" role="region" aria-label="Nhật ký quyền" tabIndex={0}><table><thead><tr><th>Thời điểm</th><th>Thao tác</th><th>Người thực hiện</th><th>Đối tượng</th><th>Trước</th><th>Sau</th></tr></thead><tbody>{data.events.map(event=><tr key={event.id}><td>{date(event.created_at)}</td><td>{teamActionLabels[event.action]}<small>{event.outcome==='success'?'Thành công':'Bị từ chối'}</small></td><td>{overview.members.find(m=>m.id===event.actor_id)?.display_name ?? event.actor_id ?? 'Hệ thống'}</td><td>{overview.members.find(m=>m.id===event.member_id)?.display_name ?? event.member_id ?? event.resource_id ?? '-'}</td><td>{describe(event.before)}</td><td>{describe(event.after)}</td></tr>)}</tbody></table></div>}
        </>}
      </div>}
    </>}
  </section>;
}
export function WorkspaceTeam(props:Props) {
  return <TeamWorkspace key={`${props.platformUrl}:${props.workspaceId}:${props.user?.id}:${props.user?.role}`} {...props}/>;
}
