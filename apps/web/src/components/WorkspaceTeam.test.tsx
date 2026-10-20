import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {WorkspaceTeam} from './WorkspaceTeam';
import * as hook from '../hooks/useWorkspaceTeam';
import {teamOverview,teamUser} from '../test/teamFixture';
const props={platformUrl:'http://localhost:8000',workspaceId:'local',user:teamUser};
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();});
function reader(){const state={snapshot:{overview:teamOverview(),roles:[],invitations:[],events:[],next_cursor:null},
  busy:false,error:'',stale:false,access:'ready' as const,previewing:false,canMutate:true,refresh:vi.fn(async()=>null),
  mutate:vi.fn(async()=>({id:'invite',secret:'x'.repeat(43)}))};vi.spyOn(hook,'useWorkspaceTeam').mockReturnValue(state);return state;}
it('has four views, protects admin and does not invite on page load',()=>{
  const state=reader();render(<WorkspaceTeam {...props}/>);
  expect(screen.getAllByRole('tab')).toHaveLength(4);expect(screen.getByText('Admin')).toBeInTheDocument();
  expect(screen.queryByRole('button',{name:'Gỡ Admin'})).not.toBeInTheDocument();
  expect(state.mutate).not.toHaveBeenCalled();
});
it('shows a one-time link only after explicit submit and erases on stale/recovery',async()=>{
  const state=reader();const {rerender}=render(<WorkspaceTeam {...props}/>);
  fireEvent.click(screen.getByRole('tab',{name:'Lời mời'}));fireEvent.click(screen.getByRole('button',{name:'Mời thành viên'}));
  fireEvent.change(screen.getByLabelText('Email người nhận'),{target:{value:'new@example.com'}});
  fireEvent.click(screen.getByRole('button',{name:'Tạo lời mời'}));
  await waitFor(()=>expect(screen.getByRole('region',{name:'Liên kết mời một lần'})).toBeInTheDocument());
  expect(state.mutate).toHaveBeenCalledTimes(1);
  state.stale=true;state.canMutate=false;rerender(<WorkspaceTeam {...props}/>);
  expect(screen.queryByRole('region',{name:'Liên kết mời một lần'})).not.toBeInTheDocument();
  state.stale=false;state.canMutate=true;rerender(<WorkspaceTeam {...props}/>);
  expect(screen.queryByRole('region',{name:'Liên kết mời một lần'})).not.toBeInTheDocument();
});
it('ignores an old clipboard result after a new link is shown',async()=>{
  const state=reader();let finish!:()=>void;
  Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:vi.fn(()=>new Promise<void>(done=>{finish=done;}))}});
  state.mutate.mockResolvedValueOnce({id:'a',secret:'a'.repeat(43)}).mockResolvedValueOnce({id:'b',secret:'b'.repeat(43)});
  render(<WorkspaceTeam {...props}/>);fireEvent.click(screen.getByRole('tab',{name:'Lời mời'}));
  const create=async(email:string)=>{fireEvent.click(screen.getByRole('button',{name:'Mời thành viên'}));fireEvent.change(screen.getByLabelText('Email người nhận'),{target:{value:email}});
    fireEvent.click(screen.getByRole('button',{name:'Tạo lời mời'}));await screen.findByRole('region',{name:'Liên kết mời một lần'});};
  await create('a@example.com');fireEvent.click(screen.getByRole('button',{name:'Sao chép liên kết'}));fireEvent.click(screen.getByRole('button',{name:'Ẩn liên kết'}));
  await create('b@example.com');await act(async()=>finish());expect(screen.getByRole('button',{name:'Sao chép liên kết'})).toBeInTheDocument();
  expect(screen.queryByRole('button',{name:'Đã sao chép'})).not.toBeInTheDocument();
});
