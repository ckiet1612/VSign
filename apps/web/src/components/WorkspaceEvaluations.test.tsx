import { render, screen, fireEvent } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { WorkspaceEvaluationsResponse, EvaluationRun } from '../../../../contracts/v1/evaluations';
import type { AuthenticatedUser } from '../../../../contracts/v1/workspace';
import * as hook from '../hooks/useWorkspaceEvaluations';
import { WorkspaceEvaluations } from './WorkspaceEvaluations';

const user:AuthenticatedUser={id:'admin',email:'admin@example.com',display_name:'Admin',role:'admin'};
const props={platformUrl:'http://localhost:8000',workspaceId:'local',user};
const snapshot=():WorkspaceEvaluationsResponse => ({api_version:'1',workspace_id:'local',active_model_id:'base',
  permissions:{create:true,cancel:true},workers:{onnx:true},models:[{id:'base',model_version:'production-v1',backend:'onnx',active:true},
    {id:'candidate',model_version:'candidate-v2',backend:'onnx',active:false}],
  snapshots:[{id:'snapshot',dataset_version:'dataset',dataset_name:'Dữ liệu kiểm thử',sample_count:2,sha256:'a'.repeat(64)}],runs:[]});
function mockReader(body:WorkspaceEvaluationsResponse) {
  const reader={snapshot:body,access:'ready' as const,error:'',busy:false,stale:false,updatedAt:Date.now(),canMutate:true,
    refresh:vi.fn(async () => true),mutate:vi.fn(async () => true)};
  vi.spyOn(hook,'useWorkspaceEvaluations').mockReturnValue(reader);
  return reader;
}
afterEach(() => vi.restoreAllMocks());

it('offers real model and sealed dataset choices without internal deployment controls', () => {
  const reader=mockReader(snapshot());
  render(<WorkspaceEvaluations {...props} />);
  expect(screen.getByRole('combobox',{name:/^Model cần đánh giá$/})).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Model cần đánh giá'),{target:{value:'candidate'}});
  fireEvent.change(screen.getByLabelText('Bản dữ liệu đã chốt'),{target:{value:'snapshot'}});
  fireEvent.click(screen.getByRole('button',{name:'Tạo lượt đánh giá'}));
  expect(reader.mutate).toHaveBeenCalledWith(expect.objectContaining({type:'create',model_id:'candidate',snapshot_id:'snapshot',request_id:expect.any(String)}));
  expect(screen.queryByText('Deploy production')).not.toBeInTheDocument();
  expect(screen.queryByText('Đăng ký ứng viên')).not.toBeInTheDocument();
  expect(document.querySelector('input[type=password]')).toBeNull();
});

it('keeps reviewer read-only and has no fabricated metrics in an empty workspace', () => {
  const body=snapshot();body.permissions={create:false,cancel:false};body.models=[];body.snapshots=[];
  mockReader(body);
  render(<WorkspaceEvaluations {...props} user={{...user,role:'reviewer'}} />);
  expect(screen.queryByRole('button',{name:'Tạo lượt đánh giá'})).not.toBeInTheDocument();
  expect(screen.getByText('Chưa có lượt đánh giá.')).toBeInTheDocument();
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
});

it('shows cancellation and frozen model identities for an in-progress run', () => {
  const body=snapshot();
  body.runs=[{id:'run',model_id:'candidate',baseline_model_id:'base',model_version:'candidate-v2',baseline_model_version:'production-v1',
    snapshot_id:'snapshot',dataset_version:'dataset',snapshot_sha256:'a'.repeat(64),backend:'onnx',sample_count:2,status:'running',progress:1,
    requested_by:'admin',created_at:'2026-10-16T00:00:00Z',started_at:'2026-10-16T00:00:01Z',finished_at:null,
    error:null,report:null,gate:null,baseline_current:true} satisfies EvaluationRun];
  const reader=mockReader(body);
  render(<WorkspaceEvaluations {...props} />);
  expect(screen.getByText('1 / 4 lượt suy luận')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Hủy lượt đánh giá'}));
  expect(reader.mutate).toHaveBeenCalledWith({type:'cancel',id:'run'});
});
