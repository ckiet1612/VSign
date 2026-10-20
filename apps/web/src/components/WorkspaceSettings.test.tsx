import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { WorkspaceSettings } from './WorkspaceSettings';
import { savedSettings, settingsSnapshot, settingsUser } from '../test/settingsFixture';

const props = { platformUrl: 'http://localhost:8000', workspaceId: 'local', user: settingsUser };
afterEach(() => vi.unstubAllGlobals());

it('renders five groups and persists only the explicitly submitted section', async () => {
  const fetcher = vi.fn(async (_url: string, init: RequestInit) => {
    const payload = init.method === 'POST' ? JSON.parse(String(init.body)) : null;
    return new Response(JSON.stringify(payload ? savedSettings(payload.request_id, { workspace: payload.workspace }) : settingsSnapshot()));
  });
  vi.stubGlobal('fetch', fetcher);
  render(<WorkspaceSettings {...props} />);
  await screen.findByLabelText('Tên workspace');
  expect(screen.getAllByRole('tab')).toHaveLength(5);
  fireEvent.change(screen.getByLabelText('Tên workspace'), { target: { value: 'Tên mới' } });
  fireEvent.click(screen.getByRole('button', { name: 'Lưu cài đặt' }));
  await screen.findByText('Đã lưu cài đặt.');
  const writes = fetcher.mock.calls.filter(([, init]) => init.method === 'POST');
  expect(writes).toHaveLength(1);
  expect(JSON.parse(String(writes[0][1].body))).toEqual({ request_id: expect.any(String), expected_revision: 0,
    workspace: { name: 'Tên mới', timezone: 'UTC' } });
});

it('refresh does not overwrite a dirty draft and uses its original revision', async () => {
  let revision = 0;
  const fetcher = vi.fn(async (_url: string, init: RequestInit) => init.method === 'POST'
    ? new Response(JSON.stringify({ detail: 'Cài đặt đã thay đổi.' }), { status: 409 })
    : new Response(JSON.stringify({ ...settingsSnapshot(), revision, updated_at: revision ? '2026-10-16T00:00:00Z' : null })));
  vi.stubGlobal('fetch', fetcher);
  render(<WorkspaceSettings {...props} />); await screen.findByLabelText('Tên workspace');
  fireEvent.change(screen.getByLabelText('Tên workspace'), { target: { value: 'Bản đang sửa' } }); revision = 1;
  fireEvent.click(screen.getByRole('button', { name: 'Làm mới cài đặt' }));
  await screen.findByText('Có phiên bản mới hơn.');
  expect(screen.getByLabelText('Tên workspace')).toHaveValue('Bản đang sửa');
  fireEvent.click(screen.getByRole('button', { name: 'Lưu cài đặt' }));
  await screen.findByRole('alert');
  const write = fetcher.mock.calls.find(([, init]) => init.method === 'POST')!;
  expect(JSON.parse(String(write[1].body)).expected_revision).toBe(0);
});

it('shows notifications only for non-managers without a fake delivery action', async () => {
  const restricted = { ...settingsSnapshot(), permissions: { manage: false }, workspace: null, retention: null, collection_policy: null };
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(restricted))));
  render(<WorkspaceSettings {...props} user={{ ...settingsUser, role: 'viewer' }} />);
  await screen.findByLabelText('Hoàn tất thu mẫu');
  expect(screen.getAllByRole('tab')).toHaveLength(1);
  expect(screen.queryByLabelText('Tên workspace')).not.toBeInTheDocument();
  expect(screen.getByText('Chưa kết nối kênh gửi')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Gửi/ })).not.toBeInTheDocument();
});

it('offers retention preview without deletion controls', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify(url.endsWith('/preview')
    ? { api_version: '1', workspace_id: 'local', revision: 0, generated_at: '2026-10-16T00:00:00Z', automatic_deletion: false,
      candidates: { draft_samples: 3, audit_events: 8 }, protected: { samples: 9, snapshots: 2 }, cutoffs: { draft_samples: null, audit_events: null } }
    : settingsSnapshot()))));
  render(<WorkspaceSettings {...props} />); await screen.findByLabelText('Tên workspace');
  fireEvent.click(screen.getByRole('tab', { name: 'Retention' }));
  expect(screen.getByLabelText('Tự động xóa')).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Xem trước retention' }));
  await waitFor(() => expect(screen.getByLabelText('Mẫu nháp hết hạn')).toHaveTextContent('3'));
  expect(screen.queryByRole('button', { name: /Xóa/ })).not.toBeInTheDocument();
});

it('updates an untouched form on refresh but does not mark it as an unsaved change', async () => {
  let name = 'Workspace Việt';
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ ...settingsSnapshot(), workspace: { name, timezone: 'UTC' } }))));
  render(<WorkspaceSettings {...props} />); await screen.findByLabelText('Tên workspace');
  name = 'Tên từ máy chủ'; fireEvent.click(screen.getByRole('button', { name: 'Làm mới cài đặt' }));
  await waitFor(() => expect(screen.getByLabelText('Tên workspace')).toHaveValue('Tên từ máy chủ'));
  expect(screen.getByRole('button', { name: 'Lưu cài đặt' })).toBeDisabled();
});
