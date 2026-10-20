import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { AuthenticatedUser } from '../../../../contracts/v1/workspace';
import type { WorkspaceIntegrations as Snapshot } from '../../../../contracts/v1/integrations';
import * as hook from '../hooks/useWorkspaceIntegrations';
import { WorkspaceIntegrations } from './WorkspaceIntegrations';

const user:AuthenticatedUser={id:'admin',email:'a@example.com',display_name:'Admin',role:'admin'};
const props={platformUrl:'http://localhost:8000',workspaceId:'local',user};
const snapshot=():Snapshot=>({api_version:'1',workspace_id:'local',permissions:{manage:true},webhook_ready:true,worker_online:false,
  available_scopes:['models:read','snapshots:read','evaluations:read'],available_events:['evaluation.completed'],
  limits:{key_per_minute:60,workspace_per_minute:300,webhook_per_minute:30,webhook_workspace_per_minute:60},keys:[],webhooks:[],deliveries:[]});
function reader(body=snapshot()) {
  const result={snapshot:body,logs:{api_version:'1' as const,workspace_id:'local',logs:[],next_cursor:null},busy:false,stale:false,
    error:'',access:'ready' as const,updatedAt:Date.now(),previewing:false,canMutate:true,refresh:vi.fn(async()=>({secret:null,id:null})),
    mutate:vi.fn(async(action:hook.IntegrationAction)=>({secret:'show-once',id:action.path}))};
  vi.spyOn(hook,'useWorkspaceIntegrations').mockReturnValue(result);return result;
}
afterEach(()=>vi.restoreAllMocks());

it('creates only scoped read keys and never exposes developer controls or login',async()=>{
  const r=reader();render(<WorkspaceIntegrations {...props}/>);
  fireEvent.click(screen.getByRole('button',{name:'Tạo khóa'}));
  fireEvent.change(screen.getByLabelText('Tên khóa'),{target:{value:'CRM'}});
  fireEvent.click(screen.getByRole('button',{name:'Lưu khóa'}));
  await waitFor(()=>expect(r.mutate).toHaveBeenCalledWith(expect.objectContaining({path:'/keys',body:expect.objectContaining({name:'CRM',scopes:['models:read']})})));
  expect(await screen.findByText('show-once')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Đóng khóa bí mật'}));
  expect(screen.queryByText('show-once')).not.toBeInTheDocument();
  expect(screen.queryByText('Đăng ký ứng viên')).not.toBeInTheDocument();
  expect(document.querySelector('input[type=password]')).toBeNull();
});

it('does not send a test webhook on page or tab load',()=>{
  const r=reader();render(<WorkspaceIntegrations {...props}/>);
  fireEvent.click(screen.getByRole('tab',{name:'Webhooks'}));
  expect(screen.getByText('Chưa có webhook.')).toBeInTheDocument();
  expect(screen.getByText('Worker chưa kết nối')).toBeInTheDocument();
  expect(r.mutate).not.toHaveBeenCalled();
});

it('clears one-time secrets after workspace switches and blocks stale controls',async()=>{
  const r=reader();const {rerender}=render(<WorkspaceIntegrations {...props}/>);
  fireEvent.click(screen.getByRole('button',{name:'Tạo khóa'}));
  fireEvent.change(screen.getByLabelText('Tên khóa'),{target:{value:'CRM'}});
  fireEvent.click(screen.getByRole('button',{name:'Lưu khóa'}));
  expect(await screen.findByText('show-once')).toBeInTheDocument();
  r.stale=true;r.canMutate=false;
  rerender(<WorkspaceIntegrations {...props} workspaceId="other"/>);
  expect(screen.queryByText('show-once')).not.toBeInTheDocument();
  expect(screen.getByRole('button',{name:'Tạo khóa'})).toBeDisabled();
});

it('erases one-time secrets after stale or denied reads rather than redisplaying on recovery',async()=>{
  const r=reader();const {rerender}=render(<WorkspaceIntegrations {...props}/>);
  fireEvent.click(screen.getByRole('button',{name:'Tạo khóa'}));
  fireEvent.change(screen.getByLabelText('Tên khóa'),{target:{value:'CRM'}});
  fireEvent.click(screen.getByRole('button',{name:'Lưu khóa'}));
  expect(await screen.findByText('show-once')).toBeInTheDocument();
  r.stale=true;r.error='Offline';r.canMutate=false;rerender(<WorkspaceIntegrations {...props}/>);
  expect(screen.queryByText('show-once')).not.toBeInTheDocument();
  r.stale=false;r.error='';r.canMutate=true;rerender(<WorkspaceIntegrations {...props}/>);
  expect(screen.queryByText('show-once')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Tạo khóa'}));
  fireEvent.change(screen.getByLabelText('Tên khóa'),{target:{value:'CRM2'}});
  fireEvent.click(screen.getByRole('button',{name:'Lưu khóa'}));
  expect(await screen.findByText('show-once')).toBeInTheDocument();
  vi.mocked(hook.useWorkspaceIntegrations).mockReturnValue({...r,access:'forbidden',snapshot:null,canMutate:false});
  rerender(<WorkspaceIntegrations {...props}/>);
  vi.mocked(hook.useWorkspaceIntegrations).mockReturnValue(r);rerender(<WorkspaceIntegrations {...props}/>);
  expect(screen.queryByText('show-once')).not.toBeInTheDocument();
});

it('saves only subscription fields even after a hook is disabled elsewhere',async()=>{
  const data=snapshot();data.webhooks=[{id:'hook',name:'ERP',url:'https://example.com/events',events:['evaluation.completed'],
    enabled:true,secret_version:1,created_at:'2026-10-16T00:00:00Z'}];
  const r=reader(data);const {rerender}=render(<WorkspaceIntegrations {...props}/>);
  fireEvent.click(screen.getByRole('tab',{name:'Webhooks'}));
  fireEvent.click(screen.getByRole('button',{name:'Sự kiện đăng ký'}));
  r.snapshot={...data,webhooks:[{...data.webhooks[0],enabled:false}]};rerender(<WorkspaceIntegrations {...props}/>);
  fireEvent.click(screen.getByRole('button',{name:'Lưu webhook'}));
  await waitFor(()=>expect(r.mutate).toHaveBeenCalled());
  expect(r.mutate.mock.calls[0][0].body).not.toHaveProperty('enabled');
});
