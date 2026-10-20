import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import type { AuthenticatedUser } from '../../../../contracts/v1/workspace';
import type { SettingsTab, WorkspaceSettingsSnapshot } from '../../../../contracts/v1/settings';
import { useWorkspaceSettings, type SettingsAction } from '../hooks/useWorkspaceSettings';
import { useTabMotion } from '../hooks/useTabMotion';
import { Archive, Check, RefreshCw, Save, Undo2 } from '../icons';
import { CardHead, PageHero } from './PageChrome';
import '../styles/workspace-settings.css';
import { Bone, FieldBone, SkeletonRegion } from "./Skeleton";

interface Props { platformUrl: string; workspaceId: string; user: AuthenticatedUser | null; onWorkspaceChanged?: () => void }
type Reader = ReturnType<typeof useWorkspaceSettings>;
const tabs: [SettingsTab, string][] = [['workspace', 'Workspace'], ['retention', 'Retention'], ['collection', 'Thu mẫu'], ['runtime', 'Runtime'], ['notifications', 'Thông báo']];
const time = (value: string) => new Date(value).toLocaleString('vi-VN');

function SettingsForm({ tab, reader, onSaved, onReset }: { tab: SettingsTab; reader: Reader; onSaved: (value: WorkspaceSettingsSnapshot) => void; onReset: () => void }) {
  const [draft, setDraft] = useState(reader.snapshot!);
  const [touched, setTouched] = useState(false);
  const [message, setMessage] = useState('');
  useEffect(() => { if (!touched && reader.snapshot) setDraft(reader.snapshot); }, [reader.snapshot, touched]);
  const personal = tab === 'notifications';
  const section = tab === 'collection' ? 'collection_policy' : tab === 'runtime' ? 'runtime_defaults' : tab;
  const revision = personal ? draft.notifications.revision : draft.revision;
  const latestRevision = personal ? reader.snapshot!.notifications.revision : reader.snapshot!.revision;
  const dirty = JSON.stringify(draft[section]) !== JSON.stringify(reader.snapshot![section]);
  const disabled = !reader.ready || !personal && !reader.snapshot!.permissions.manage;
  const set = <K extends keyof WorkspaceSettingsSnapshot>(key: K, value: WorkspaceSettingsSnapshot[K]) => {
    setDraft(old => ({ ...old, [key]: value })); setTouched(true); setMessage('');
  };
  const submit = async () => {
    const action: SettingsAction = { path: personal ? '/notifications' : '/update', body: {
      request_id: crypto.randomUUID(), expected_revision: revision,
      ...(personal ? { preferences: draft.notifications.preferences } : { [section]: draft[section] }),
    } };
    const result = await reader.mutate(action);
    if (result) { setDraft(result); setTouched(false); setMessage('Đã lưu cài đặt.'); onSaved(result); }
  };
  return <form className="settings-form page-card" aria-label={`Cài đặt ${tabs.find(([key]) => key === tab)![1]}`} onSubmit={event => { event.preventDefault(); void submit(); }}>
    {latestRevision !== revision && <p className="settings-warning" role="status">Có phiên bản mới hơn.</p>}
    <fieldset disabled={disabled}>
      {tab === 'workspace' && draft.workspace && <>
        <label>Tên workspace<input name="workspace-name" value={draft.workspace.name} required maxLength={120}
          onChange={event => set('workspace', { ...draft.workspace!, name: event.target.value })} /></label>
        <label>Múi giờ<input name="timezone" value={draft.workspace.timezone} required maxLength={64} list="settings-timezones"
          onChange={event => set('workspace', { ...draft.workspace!, timezone: event.target.value })} /></label>
        <datalist id="settings-timezones"><option value="UTC" /><option value="Asia/Ho_Chi_Minh" /><option value="Asia/Bangkok" /><option value="Asia/Tokyo" /></datalist>
      </>}
      {tab === 'retention' && draft.retention && <>
        <label>Mẫu nháp (ngày)<input type="number" min={1} max={3650} step={1} placeholder="Không giới hạn" value={draft.retention.draft_samples_days ?? ''}
          onChange={event => set('retention', { ...draft.retention!, draft_samples_days: event.target.value === '' ? null : Number(event.target.value) })} /></label>
        <label>Nhật ký hoạt động (ngày)<input type="number" min={1} max={3650} step={1} placeholder="Không giới hạn" value={draft.retention.audit_events_days ?? ''}
          onChange={event => set('retention', { ...draft.retention!, audit_events_days: event.target.value === '' ? null : Number(event.target.value) })} /></label>
        <label className="settings-toggle"><input type="checkbox" checked={false} disabled readOnly />Tự động xóa</label>
      </>}
      {tab === 'collection' && draft.collection_policy && <>
        <label className="settings-toggle"><input type="checkbox" checked={draft.collection_policy.enabled}
          onChange={event => set('collection_policy', { ...draft.collection_policy!, enabled: event.target.checked })} />Cho phép thu mẫu</label>
        <label className="settings-toggle"><input type="checkbox" checked={draft.collection_policy.require_consent}
          onChange={event => set('collection_policy', { ...draft.collection_policy!, require_consent: event.target.checked })} />Yêu cầu đồng ý lưu mẫu</label>
        <label>Hạn mức mặc định mỗi ký hiệu<input type="number" min={1} max={10000} step={1} required value={draft.collection_policy.default_quota_per_label}
          onChange={event => set('collection_policy', { ...draft.collection_policy!, default_quota_per_label: Number(event.target.value) })} /></label>
        <dl className="settings-facts"><div><dt>Thu mẫu trên máy chủ</dt><dd>{reader.snapshot!.process_collection_enabled ? 'Đã bật' : 'Chưa bật'}</dd></div></dl>
      </>}
      {tab === 'runtime' && <>
        <label>Chế độ thu nhận dạng mặc định<select value={draft.runtime_defaults.capture_mode}
          onChange={event => set('runtime_defaults', { capture_mode: event.target.value as 'manual' | 'automatic' })}>
          <option value="manual">Thủ công</option><option value="automatic">Tự động</option></select></label>
        <dl className="settings-facts"><div><dt>Phạm vi áp dụng</dt><dd>Phiên mới</dd></div><div><dt>Tự thêm từ vào câu</dt><dd>Thủ công</dd></div></dl>
      </>}
      {tab === 'notifications' && <>
        {([['collection_completed', 'Hoàn tất thu mẫu'], ['evaluation_finished', 'Hoàn tất đánh giá'], ['integration_failed', 'Lỗi tích hợp']] as const).map(([key, label]) =>
          <label className="settings-toggle" key={key}><input type="checkbox" checked={draft.notifications.preferences[key]}
            onChange={event => set('notifications', { ...draft.notifications, preferences: { ...draft.notifications.preferences, [key]: event.target.checked } })} />{label}</label>)}
        <dl className="settings-facts"><div><dt>Kênh gửi</dt><dd>Chưa kết nối kênh gửi</dd></div></dl>
      </>}
    </fieldset>
    <div className="settings-actions"><button type="submit" className="settings-primary" disabled={disabled || !dirty}><Save size={17} aria-hidden="true" />Lưu cài đặt</button>
      <button type="button" aria-label="Nạp phiên bản mới" title="Nạp phiên bản mới" disabled={reader.busy || !!reader.failed} onClick={onReset}><Undo2 size={18} aria-hidden="true" /></button>
      {message && <span role="status" className="settings-saved"><Check size={16} aria-hidden="true" />{message}</span>}</div>
  </form>;
}

function SettingsWorkspace(props: Props) {
  const reader = useWorkspaceSettings(props), data = reader.snapshot;
  const [selected, setSelected] = useState<SettingsTab>('workspace'), [seed, setSeed] = useState(0);
  const availableTabs = data?.permissions.manage ? tabs : tabs.filter(([key]) => key === 'notifications');
  const tab = availableTabs.some(([key]) => key === selected) ? selected : 'notifications';
  const tabList = useRef<HTMLDivElement>(null), tabPanel = useRef<HTMLDivElement>(null);
  useTabMotion(tabList, tabs.findIndex(([key]) => key === tab), { panel: tabPanel, mounted: !!data });
  const selectTab = (next: SettingsTab) => { setSelected(next); };
  const onKeys = (event: KeyboardEvent<HTMLButtonElement>) => {
    const index = availableTabs.findIndex(([key]) => key === tab);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? availableTabs.length - 1
      : ['ArrowRight', 'ArrowDown'].includes(event.key) ? (index + 1) % availableTabs.length
      : ['ArrowLeft', 'ArrowUp'].includes(event.key) ? (index - 1 + availableTabs.length) % availableTabs.length : null;
    if (next === null) return;
    event.preventDefault(); selectTab(availableTabs[next][0]); document.getElementById(`settings-tab-${availableTabs[next][0]}`)?.focus();
  };
  return <section className="workspace-page settings-page" aria-labelledby="workspace-page-title">
    <PageHero title={props.user?.role==='system_admin'?'Cấu hình hệ thống':'Cài đặt'}>
      {!data && reader.busy && <Bone className="skeleton-tabs" w={392} h={42} r="var(--page-control-radius)" />}
      {data && <div ref={tabList} className="settings-tabs page-tabs" role="tablist" aria-label="Cài đặt workspace">{availableTabs.map(([key, label]) =>
        <button type="button" role="tab" id={`settings-tab-${key}`} key={key} aria-controls="settings-panel" aria-selected={tab === key} tabIndex={tab === key ? 0 : -1}
          disabled={reader.busy || !!reader.failed} onKeyDown={onKeys} onClick={() => selectTab(key)}>{label}</button>)}</div>}
      <button type="button" className="page-icon-button" aria-label="Làm mới cài đặt" title="Làm mới cài đặt" disabled={reader.busy || !props.user} data-busy={reader.busy || undefined} onClick={() => void reader.refresh()}><RefreshCw size={18} aria-hidden="true" /></button></PageHero>
    {reader.busy && <p role="status" className="sr-only">Đang cập nhật cài đặt...</p>}
    {reader.error && <p role="alert" className="settings-error">{reader.error}</p>}
    {reader.stale && data && <p role="status" className="settings-warning">Đang hiển thị cài đặt lần đọc trước.</p>}
    {reader.failed && <button type="button" disabled={reader.busy} onClick={async () => {
      const result = await reader.retry(); if (result) { setSeed(old => old + 1); props.onWorkspaceChanged?.(); }
    }}>Thử lại thao tác lưu</button>}
    {!props.user && <p role="status">Đăng nhập để xem cài đặt.</p>}
    {!data && reader.busy && <SkeletonRegion>
      <div className="settings-form page-card"><div className="skeleton-fieldset">{[0, 1].map(index => <FieldBone key={index} label={110} w="min(100%, 400px)" />)}</div>
        <div className="settings-actions"><Bone w={132} h={40} r="var(--radius-12)" /><Bone w={40} h={40} r="var(--radius-12)" /></div></div>
    </SkeletonRegion>}
    {data && <>
      <div ref={tabPanel} id="settings-panel" role="tabpanel" aria-labelledby={`settings-tab-${tab}`} aria-busy={reader.busy}>
        <SettingsForm key={`${tab}:${seed}`} tab={tab} reader={reader} onReset={() => setSeed(old => old + 1)}
          onSaved={() => { if (tab === 'workspace') props.onWorkspaceChanged?.(); }} />
        {tab === 'retention' && <section className="settings-retention page-card" aria-label="Kiểm tra retention">
          <CardHead icon={Archive} title="Dữ liệu hết hạn"><button type="button" disabled={!reader.ready} onClick={() => void reader.loadPreview()}>Xem trước retention</button></CardHead>
          {reader.preview && <><dl className="settings-facts">
            <div><dt>Mẫu nháp hết hạn</dt><dd aria-label="Mẫu nháp hết hạn">{reader.preview.candidates.draft_samples}</dd></div>
            <div><dt>Nhật ký hết hạn</dt><dd>{reader.preview.candidates.audit_events}</dd></div>
            <div><dt>Mẫu được bảo vệ</dt><dd>{reader.preview.protected.samples}</dd></div>
            <div><dt>Snapshot được bảo vệ</dt><dd>{reader.preview.protected.snapshots}</dd></div>
          </dl><time className="settings-muted" dateTime={reader.preview.generated_at}>{time(reader.preview.generated_at)}</time></>}
        </section>}
      </div>
    </>}
  </section>;
}
export function WorkspaceSettings(props: Props) {
  return <SettingsWorkspace key={`${props.platformUrl}:${props.workspaceId}:${props.user?.id}:${props.user?.role}`} {...props} />;
}
