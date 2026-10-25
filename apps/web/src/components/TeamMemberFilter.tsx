import { useEffect, useState } from 'react';
import { useDismissibleDetails } from '../hooks/useDismissibleDetails';
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
  // Same as the member list: the choices follow the box once typing pauses.
  useEffect(()=>{const query=draft.trim();if(query===search) return;
    const timer=window.setTimeout(()=>{setSearch(query);setCursor('');setHistory([]);},300);return ()=>window.clearTimeout(timer);},[draft,search]);
  return <div className="team-member-choices">
    <form className="team-search" role="search" onSubmit={e=>{e.preventDefault();setSearch(draft.trim());setCursor('');setHistory([]);}}>
      <label>Tìm thành viên trong nhật ký<input type="search" maxLength={120} placeholder="Tên hoặc email" autoFocus value={draft} onChange={e=>setDraft(e.target.value)}/></label>
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
// The choices stay mounted through the popover's fade-out (see styles.css) before they unmount.
const FADE_MS=160;
export function TeamMemberFilter(props:Props) {
  const [open,setOpen]=useState(false);
  const ref=useDismissibleDetails();
  // The choices float under the field like the app's other menus, so opening them does not stretch the filter bar.
  const select=(id:string,name:string)=>{props.onSelect(id,name);if(ref.current) ref.current.open=false;};
  return <div className="team-member-filter"><span>Thành viên</span><details ref={ref} onToggle={e=>{if(e.currentTarget.open) setOpen(true); else window.setTimeout(()=>{if(!ref.current?.open) setOpen(false);},FADE_MS);}}><summary>{props.selectedName || 'Tất cả thành viên'}</summary>
    {open && <MemberChoices {...props} onSelect={select}/>}
  </details></div>;
}
