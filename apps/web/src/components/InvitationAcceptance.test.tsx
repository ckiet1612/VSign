import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {InvitationAcceptance} from './InvitationAcceptance';
afterEach(()=>{vi.unstubAllGlobals();history.replaceState(null,'','/');});
it('removes token from URL, inspects it but never accepts without submit',async()=>{
  history.replaceState(null,'','/invite#token='+'x'.repeat(43));
  const fetcher=vi.fn<(url:string)=>Promise<Response>>(async()=>new Response(JSON.stringify({api_version:'1',workspace_id:'local',workspace_name:'VSign',
    email:'new@example.com',role:'operator',expires_at:'2026-12-01T00:00:00Z',existing_account:false,auth_mode:'session'})));
  vi.stubGlobal('fetch',fetcher);render(<InvitationAcceptance platformUrl="http://localhost:8000"/>);
  await screen.findByText('new@example.com');expect(location.hash).toBe('');
  expect(fetcher.mock.calls.every(call=>!String(call[0]).endsWith('/accept'))).toBe(true);
});
it('submits explicit credentials and does not display a success before acknowledgement',async()=>{
  history.replaceState(null,'','/invite#token='+'x'.repeat(43));let finish!:(v:Response)=>void;
  vi.stubGlobal('fetch',vi.fn((url:string)=>url.endsWith('/accept') ? new Promise<Response>(done=>{finish=done;})
    : Promise.resolve(new Response(JSON.stringify({api_version:'1',workspace_id:'local',workspace_name:'VSign',email:'new@example.com',
      role:'viewer',expires_at:'2026-12-01T00:00:00Z',existing_account:false,auth_mode:'session'})))));
  render(<InvitationAcceptance platformUrl="http://localhost:8000"/>);await screen.findByText('new@example.com');
  fireEvent.change(screen.getByLabelText(/Tên hiển thị/),{target:{value:'New'}});
  fireEvent.change(screen.getByLabelText('Mật khẩu'),{target:{value:'password-12345'}});
  fireEvent.click(screen.getByRole('button',{name:'Chấp nhận lời mời'}));
  expect(screen.queryByText('Đã tham gia workspace.')).not.toBeInTheDocument();
  await waitFor(()=>expect(finish).toBeDefined());finish(new Response(JSON.stringify({api_version:'1',workspace_id:'local',accepted:true})));
  expect(await screen.findByText('Đã tham gia workspace.')).toBeInTheDocument();
  // The new member signs in with the invited email, not the display name.
  expect(screen.getByText('new@example.com')).toBeInTheDocument();
  expect(screen.getByRole('link',{name:'Đăng nhập'})).toHaveAttribute('href','/workspace?login=new%40example.com');
});
