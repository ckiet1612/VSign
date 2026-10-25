import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {TeamMemberFilter} from './TeamMemberFilter';
import {teamOverview,teamUser} from '../test/teamFixture';
afterEach(()=>vi.unstubAllGlobals());
it('searches and paginates members independently from permission audit pagination',async()=>{
  const next='00000000-0000-4000-8000-000000000051';
  const fetcher=vi.fn(async(url:string)=>{
    const data={...teamOverview(),next_cursor:next as string|null};const query=new URL(url).searchParams;
    if(query.get('cursor')===next || query.get('search')==='member51') data.members=[{...data.members[0],id:next,display_name:'Member 51'}];
    return new Response(JSON.stringify(data));
  });vi.stubGlobal('fetch',fetcher);const select=vi.fn();
  render(<TeamMemberFilter platformUrl="http://localhost:8000" workspaceId="local" user={teamUser} selectedId="" selectedName="" onSelect={select}/>);
  expect(fetcher).not.toHaveBeenCalled();fireEvent.click(screen.getByText('Tất cả thành viên'));
  await screen.findByText('Admin');await waitFor(()=>expect(screen.getByRole('button',{name:'Trang thành viên tiếp'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button',{name:'Trang thành viên tiếp'}));await screen.findByText('Member 51');
  // The box searches as you type, with no search button.
  expect(screen.queryByRole('button',{name:'Tìm'})).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Tìm thành viên trong nhật ký'),{target:{value:'member51'}});
  await waitFor(()=>expect(fetcher.mock.calls.some(([url])=>new URL(url).searchParams.get('search')==='member51')).toBe(true));
  // Picking a member closes the floating list instead of leaving it open in the filter bar.
  const details=screen.getByText('Tất cả thành viên').closest('details')!;expect(details.open).toBe(true);
  fireEvent.click(await screen.findByRole('button',{name:/Member 51/}));expect(select).toHaveBeenCalledWith(next,'Member 51');
  expect(details.open).toBe(false);
  expect(fetcher.mock.calls.every(([url])=>!url.includes('/audit'))).toBe(true);
});
