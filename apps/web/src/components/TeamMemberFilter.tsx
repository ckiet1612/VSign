import { useState } from 'react';
import type { AuthenticatedUser } from '../../../../contracts/v1/workspace';
import { useWorkspaceTeam } from '../hooks/useWorkspaceTeam';
import { ArrowLeft, ArrowRight, Check } from '../icons';

interface Props {
  platformUrl:string; workspaceId:string; user:AuthenticatedUser|null; selectedId:string; selectedName:string;
  onSelect:(id:string,name:string)=>void;
}
function MemberChoices(props:Props) {
  const [draft,setDraft]=useState(''),[search,setSearch]=useState(''),[cursor,setCursor]=useState(''),[history,setHistory]=useState<string[]>([]);
  const reader=useWorkspaceTeam({...props,tab:'members',search,cursor});
  const data=reader.snapshot?.overview;
  return <div className="team-member-choices">
    <form className="team-search" onSubmit={e=>{e.preventDefault();setSearch(draft.trim());setCursor('');setHistory([]);}}>
      <label>Tìm thành viên trong nhật ký<input type="search" maxLength={120} value={draft} onChange={e=>setDraft(e.target.value)}/></label><button type="submit" disabled={reader.busy}>Tìm</button>
    </form>
    {reader.error && <p className="team-warning" role="alert">{reader.error}</p>}
    <div className="team-member-results" aria-busy={reader.busy}>
      <button type="button" onClick={()=>props.onSelect('','')}>Tất cả{!props.selectedId && <Check size={16}/>}</button>
      {data?.members.map(member=><button type="button" key={member.id} disabled={reader.busy || reader.stale} onClick={()=>props.onSelect(member.id,member.display_name)}><span>{member.display_name}<small>{member.email}</small></span>{props.selectedId===member.id && <Check size={16}/>}</button>)}
      {!reader.busy && !data?.members.length && <p className="team-muted">Không tìm thấy thành viên.</p>}
    </div>
    <div className="team-actions"><button type="button" title="Trang thành viên trước" aria-label="Trang thành viên trước" disabled={!history.length || reader.busy} onClick={()=>{setCursor(history[history.length-1]);setHistory(old=>old.slice(0,-1));}}><ArrowLeft size={18}/></button>
      <button type="button" title="Trang thành viên tiếp" aria-label="Trang thành viên tiếp" disabled={!data?.next_cursor || reader.busy} onClick={()=>{setHistory(old=>[...old,cursor]);setCursor(data!.next_cursor!);}}><ArrowRight size={18}/></button></div>
  </div>;
}
export function TeamMemberFilter(props:Props) {
  const [open,setOpen]=useState(false);
  return <div className="team-member-filter"><span>Thành viên</span><details onToggle={e=>setOpen(e.currentTarget.open)}><summary>{props.selectedName || 'Tất cả thành viên'}</summary>
    {open && <MemberChoices {...props}/>}
  </details></div>;
}
