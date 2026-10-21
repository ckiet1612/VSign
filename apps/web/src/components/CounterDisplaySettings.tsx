import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import qrcode from 'qrcode-generator';
import type { CreatedEnrollment, DisplayOverview } from '../../../../contracts/v1/display';
import { Check, Clock, Copy, LayoutGrid, Plus, Trash2, Video, X } from '../icons';
import { copyText } from '../lib/copy';
import { WorkspaceApiError, workspaceRequest } from '../lib/workspaceApi';
import { CardHead } from './PageChrome';
import '../styles/counter-display.css';

const BASE = '/api/v1/displays';
const IDLE_REFRESH_MS = 10000;
// While a code is out, the claim and its verification code should show up without a manual refresh.
const ENROLLING_REFRESH_MS = 2000;
const time = (value: string | null) => value ? new Date(value).toLocaleString('vi-VN') : 'Chưa từng';

function QrCode({ value, label }: { value: string; label: string }) {
  const path = useMemo(() => {
    const code = qrcode(0, 'M');
    code.addData(value);
    code.make();
    const size = code.getModuleCount();
    let d = '';
    for (let row = 0; row < size; row += 1) {
      for (let col = 0; col < size; col += 1) if (code.isDark(row, col)) d += `M${col + 4} ${row + 4}h1v1h-1z`;
    }
    return { d, size: size + 8 };
  }, [value]);
  return <svg className="display-qr" viewBox={`0 0 ${path.size} ${path.size}`} role="img" aria-label={label} shapeRendering="crispEdges">
    <rect width={path.size} height={path.size} fill="#fff" /><path d={path.d} fill="#000" />
  </svg>;
}

function useCountdown(until: string | null) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!until) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [until]);
  if (!until) return null;
  const left = Math.max(0, Math.round((Date.parse(until) - now) / 1000));
  return `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`;
}

type Confirm = { title: string; action: () => Promise<unknown> };

/** Settings → Màn hình khách: enroll counter laptops once with a code, rename them, revoke them. */
export function CounterDisplaySettings({ platformUrl }: { platformUrl: string }) {
  const [overview, setOverview] = useState<DisplayOverview | null>(null);
  const [created, setCreated] = useState<CreatedEnrollment | null>(null);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      const { body } = await workspaceRequest<DisplayOverview>(platformUrl, BASE, { cache: 'no-store' }, signal);
      if (body) { setOverview(body); setError(''); }
    } catch (cause) {
      if (!(cause instanceof DOMException && cause.name === 'AbortError')) {
        setError(cause instanceof WorkspaceApiError ? cause.message : 'Chưa tải được danh sách màn hình quầy.');
      }
    }
  }, [platformUrl]);

  const pending = overview?.enrollments ?? [];
  const enrolling = !!created || pending.length > 0;
  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void refresh(); },
      enrolling ? ENROLLING_REFRESH_MS : IDLE_REFRESH_MS);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [refresh, enrolling]);

  const post = async (path: string, body?: unknown) => {
    setBusy(true); setError(''); setMessage('');
    try {
      const { body: result } = await workspaceRequest<unknown>(platformUrl, BASE + path, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body ?? {}),
      });
      return result;
    } catch (cause) {
      setError(cause instanceof WorkspaceApiError ? cause.message : 'Chưa lưu được thay đổi. Hãy thử lại.');
      return null;
    } finally {
      setBusy(false);
    }
  };
  const apply = (result: unknown) => { if (result && typeof result === 'object' && 'displays' in result) setOverview(result as DisplayOverview); };

  const create = async (event: FormEvent) => {
    event.preventDefault();
    const result = await post('/enrollments', { name: name.trim() });
    if (result) { setCreated(result as CreatedEnrollment); setName(''); void refresh(); }
  };

  const claimed = created ? pending.find(row => row.id === created.id) : undefined;
  // The code card closes once its enrollment is decided or gone (confirmed, rejected, expired).
  const codeOpen = created && (!overview || pending.some(row => row.id === created.id));
  const countdown = useCountdown(codeOpen ? claimed?.expires_at ?? created.expires_at : null);
  const link = created ? `${window.location.origin}/display#token=${created.link_token}` : '';

  const decide = async (id: string, accept: boolean) => {
    apply(await post(`/enrollments/${id}/${accept ? 'confirm' : 'reject'}`));
    if (created?.id === id) setCreated(null);
    if (accept) setMessage('Đã xác nhận màn hình quầy.');
  };
  const run = async (action: () => Promise<unknown>) => { await action(); setConfirm(null); };

  if (overview && !overview.permissions.manage) {
    return <p role="status" className="settings-muted">Chỉ quản trị viên được thêm hoặc huỷ màn hình quầy.</p>;
  }
  const host = window.location.host;
  const displays = overview?.displays ?? [];
  const others = pending.filter(row => row.id !== created?.id);
  return <div className="display-settings">
    <section className="page-card" aria-labelledby="display-settings-title">
      <CardHead icon={Video} id="display-settings-title" title="Màn hình khách" />
      {error && <p role="alert" className="settings-error">{error}</p>}
      {message && <p role="status" className="settings-saved"><Check size={16} aria-hidden="true" />{message}</p>}
      <form className="display-add-form" onSubmit={event => void create(event)}>
        <label><span className="sr-only">Tên quầy</span><input value={name} maxLength={60} required placeholder="Tên quầy, ví dụ Quầy 1" disabled={busy}
          onChange={event => setName(event.target.value)} /></label>
        <button type="submit" className="settings-primary" disabled={busy || !name.trim()}><Plus size={16} aria-hidden="true" />Thêm màn hình quầy</button>
      </form>
    </section>

    {created && codeOpen && <section className="page-card display-enrollment" aria-label={`Đăng ký ${created.name}`}>
      {claimed?.status === 'awaiting_confirmation' && claimed.verification ? <div className="display-enrollment-main">
        <h2>{created.name}: xác nhận nếu laptop khách hiện cùng mã</h2>
        <strong className="display-code-box is-verification" aria-label={`Mã đối chiếu ${claimed.verification.split('').join(' ')}`}>{claimed.verification}</strong>
        <div className="settings-actions">
          <button type="button" className="settings-primary" disabled={busy} onClick={() => void decide(created.id, true)}><Check size={16} aria-hidden="true" />Xác nhận</button>
          <button type="button" disabled={busy} onClick={() => void decide(created.id, false)}><X size={16} aria-hidden="true" />Từ chối</button>
        </div>
      </div> : <>
        <div className="display-enrollment-main">
          <h2>{created.name}: nhập mã tại <code>{host}/display</code></h2>
          <strong className="display-code-box" aria-label={`Mã ${created.code.split('').join(' ')}`}>
            <span>{created.code.slice(0, 3)}</span> <span>{created.code.slice(3)}</span>
          </strong>
          <span className="page-status">Còn {countdown ?? '—'}</span>
          <div className="settings-actions">
            <button type="button" onClick={() => void copyText(link).then(() => setMessage('Đã sao chép liên kết.'))}>
              <Copy size={16} aria-hidden="true" />Sao chép liên kết
            </button>
            <button type="button" disabled={busy} onClick={() => void decide(created.id, false)}><X size={16} aria-hidden="true" />Huỷ mã</button>
          </div>
        </div>
        <div className="display-qr-box"><QrCode value={link} label="Mã QR mở màn hình quầy" /></div>
      </>}
    </section>}

    {others.length > 0 && <section className="page-card" aria-labelledby="display-pending-title">
      <CardHead icon={Clock} id="display-pending-title" title="Mã đang chờ" />
      <ul className="display-pending">{others.map(row => <li key={row.id} aria-label={`Đăng ký ${row.name}`}>
        <span><strong>{row.name}</strong>{row.status === 'awaiting_confirmation' && <> · mã <strong>{row.verification}</strong></>}</span>
        <div className="settings-actions">
          {row.status === 'awaiting_confirmation' && <button type="button" className="settings-primary" disabled={busy} onClick={() => void decide(row.id, true)}><Check size={16} aria-hidden="true" />Xác nhận</button>}
          <button type="button" disabled={busy} onClick={() => void decide(row.id, false)}><X size={16} aria-hidden="true" />{row.status === 'awaiting_confirmation' ? 'Từ chối' : 'Huỷ mã'}</button>
        </div>
      </li>)}</ul>
    </section>}

    {confirm && <section className="page-card display-confirm" aria-label="Xác nhận thay đổi"><h2>{confirm.title}</h2>
      <div className="settings-actions">
        <button type="button" className="settings-primary" disabled={busy} onClick={() => void run(confirm.action)}>Xác nhận</button>
        <button type="button" disabled={busy} onClick={() => setConfirm(null)}>Hủy</button>
      </div>
    </section>}

    <section className="page-card" aria-label="Danh sách màn hình quầy">
      <CardHead icon={LayoutGrid} title="Quầy đã đăng ký" />
      {!overview ? <p role="status" className="settings-muted">Đang tải…</p> : !displays.length ? (
        <p className="settings-muted">Chưa có màn hình quầy nào.</p>
      ) : <ul className="display-list">{displays.map(row => <li key={row.id}>
        {renaming?.id === row.id ? (
          <form className="display-rename" onSubmit={event => { event.preventDefault();
            void post(`/${row.id}/rename`, { name: renaming.name.trim() }).then(result => { apply(result); if (result) setRenaming(null); }); }}>
            <label className="sr-only" htmlFor={`display-rename-${row.id}`}>Tên mới</label>
            <input id={`display-rename-${row.id}`} value={renaming.name} maxLength={60} required autoFocus disabled={busy}
              onChange={event => setRenaming({ id: row.id, name: event.target.value })} />
            <button type="submit" className="settings-primary" disabled={busy || !renaming.name.trim()}>Lưu</button>
            <button type="button" onClick={() => setRenaming(null)}>Hủy</button>
          </form>
        ) : <>
          <span className={`display-list-icon${row.online ? ' is-online' : ''}`} aria-hidden="true"><Video size={18} /></span>
          <div className="display-list-main" title={`Lần thấy cuối: ${time(row.last_seen_at)}`}>
            <strong>{row.name}</strong>
            <span className="display-list-meta">
              <span className={`counter-display-status tone-${row.online ? 'ok' : 'off'}`}><i aria-hidden="true" />{row.online ? 'Đang mở' : 'Chưa mở'}</span>
              {row.staff && <span>· {row.staff} đang phục vụ</span>}
            </span>
          </div>
          <div className="settings-actions">
            <button type="button" disabled={busy} onClick={() => setRenaming({ id: row.id, name: row.name })}>Đổi tên</button>
            <button type="button" className="display-danger" disabled={busy} onClick={() => setConfirm({
              title: `Huỷ “${row.name}”? Laptop này sẽ thoát ngay và cần mã mới để đăng ký lại.`,
              action: async () => apply(await post(`/${row.id}/revoke`)),
            })}><Trash2 size={16} aria-hidden="true" />Huỷ</button>
          </div>
        </>}
      </li>)}</ul>}
    </section>
  </div>;
}
