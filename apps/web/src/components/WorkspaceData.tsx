import { useRef, useState, type ReactNode } from "react";
import { useTabMotion } from "../hooks/useTabMotion";
import { Check, Database, Folder, Plus, RefreshCw, Save, Tag, X } from "../icons";
import { PageHero } from "./PageChrome";
import type { DataLabel, DataSession, DataVersion } from "../../../../contracts/v1/data";
import type { useWorkspaceData } from "../hooks/useWorkspaceData";
import "../styles/workspace-data.css";
import { Bone, FactsBone, FieldBone, PillBone, SkeletonRegion, TextBone } from "./Skeleton";

export type DataTab = "collect" | "sessions" | "datasets" | "labels";
export type DataReader = ReturnType<typeof useWorkspaceData>;
const tabs: Array<[DataTab, string]> = [["collect", "Thu mẫu"], ["sessions", "Phiên thu"], ["datasets", "Bộ dữ liệu"], ["labels", "Danh mục ký hiệu"]];
const stateLabels = { running: "Đang thu", paused: "Tạm dừng", stopped: "Đã kết thúc", completed: "Hoàn tất" };
const stateTones = { running: "is-running", paused: "is-warning", stopped: "", completed: "is-success" };
const time = (value: string) => new Date(value).toLocaleString("vi-VN");

function DatasetItem({ dataset, reader, locked }: { dataset: DataVersion; reader: DataReader; locked: boolean }) {
  const [quota, setQuota] = useState(dataset.quota_per_label);
  const [confirm, setConfirm] = useState(false);
  const snapshot = reader.snapshot!.snapshots.find(row => row.dataset_version_id === dataset.id);
  const canSeal = dataset.sample_count > 0 && !reader.snapshot!.sessions.some(row => row.dataset_version_id === dataset.id && ["running", "paused"].includes(row.state));
  return <article className="data-item page-card">
    <div className="data-item-heading"><span className="data-avatar" aria-hidden="true"><Database size={18} /></span><h2>{dataset.name}</h2><span className={`page-status ${dataset.status === "sealed" ? "is-success" : ""}`}>{dataset.status === "sealed" ? "Đã chốt" : "Bản nháp"}</span></div>
    <dl className="data-facts"><div><dt>Mẫu đã lưu</dt><dd>{dataset.sample_count}</dd></div>
      <div><dt>Hạn mức mỗi ký hiệu</dt><dd>{dataset.quota_per_label}</dd></div>
      <div><dt>Danh mục</dt><dd>{reader.snapshot!.labels.find(row => row.id === dataset.label_version_id)?.name}</dd></div>
      <div><dt>Tạo lúc</dt><dd>{time(dataset.created_at)}</dd></div></dl>
    <details><summary>Phân bố ký hiệu</summary><ul className="data-counts">{Object.entries(dataset.counts).map(([name, counts]) =>
      <li key={name}><span>{name}</span><span>{counts.right + counts.left}/{dataset.quota_per_label}</span><span>Phải {counts.right} · Trái {counts.left}</span></li>)}</ul></details>
    {snapshot && <p className="data-sealed"><Check size={16} aria-hidden="true" />Bản dữ liệu bất biến<span>{time(snapshot.created_at)}</span></p>}
    {reader.snapshot!.permissions.manage && dataset.status === "draft" && <div className="data-inline-actions">
      <label>Hạn mức<input type="number" min={1} max={10000} aria-label={`Hạn mức ${dataset.name}`} value={quota}
        disabled={locked || !reader.ready} onChange={event => setQuota(Number(event.target.value))} /></label>
      <button type="button" aria-label={`Lưu hạn mức ${dataset.name}`} title="Lưu hạn mức" disabled={locked || !reader.ready || !Number.isInteger(quota) || quota < 1 || quota > 10000 || quota === dataset.quota_per_label}
        onClick={() => void reader.mutate(`/datasets/${dataset.id}/quota`, { quota_per_label: quota })}><Save size={18} aria-hidden="true" /></button>
      <button type="button" disabled={locked || !reader.ready || !canSeal} onClick={() => setConfirm(true)}><Check size={16} aria-hidden="true" />Chốt phiên bản</button>
    </div>}
    {confirm && <div className="data-confirm" role="group" aria-label="Xác nhận chốt phiên bản"><p>Chốt “{dataset.name}” với {dataset.sample_count} mẫu? Phiên bản này sẽ không thể thu thêm hoặc sửa đổi.</p>
      <button type="button" disabled={locked || !reader.ready || !canSeal} onClick={async () => {
        setConfirm(false); await reader.mutate(`/datasets/${dataset.id}/snapshot`, { request_id: crypto.randomUUID() });
      }}><Check size={16} aria-hidden="true" />Xác nhận chốt</button>
      <button type="button" onClick={() => setConfirm(false)}><X size={16} aria-hidden="true" />Hủy</button></div>}
  </article>;
}

function DatasetForm({ reader, locked }: { reader: DataReader; locked: boolean }) {
  const [name, setName] = useState("");
  const [labels, setLabels] = useState(reader.snapshot!.labels[0]?.id ?? "");
  const selected = labels || reader.snapshot!.labels[0]?.id || "";
  return <form className="data-form page-card" onSubmit={async event => {
    event.preventDefault();
    if (await reader.mutate("/datasets", { request_id: crypto.randomUUID(), name: name.trim(), label_version_id: selected })) setName("");
  }}><label>Tên bộ dữ liệu<input value={name} maxLength={120} required disabled={locked || !reader.ready} onChange={event => setName(event.target.value)} /></label>
    <label>Danh mục ký hiệu<select aria-label="Danh mục ký hiệu" value={selected} required disabled={locked || !reader.ready} onChange={event => setLabels(event.target.value)}>
      {!reader.snapshot!.labels.length && <option value="">Chưa có danh mục</option>}
      {reader.snapshot!.labels.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
    <button type="submit" disabled={locked || !reader.ready || !name.trim() || !selected}><Plus size={16} aria-hidden="true" />Tạo bộ dữ liệu</button>
  </form>;
}

function LabelForm({ reader, locked }: { reader: DataReader; locked: boolean }) {
  const [name, setName] = useState("");
  const [parent, setParent] = useState("");
  const [entries, setEntries] = useState<DataLabel[]>(() => reader.snapshot!.default_labels.map(name => ({
    id: crypto.randomUUID(), name, kind: name === "Không ký hiệu" ? "negative" : "sign",
  })));
  const update = (id: string, value: Partial<DataLabel>) => setEntries(rows => rows.map(row => row.id === id ? { ...row, ...value } : row));
  return <form className="data-label-form page-card" onSubmit={async event => {
    event.preventDefault();
    if (await reader.mutate("/labels", { request_id: crypto.randomUUID(), name: name.trim(), parent_id: parent || null, entries })) setName("");
  }}><div className="data-form"><label>Tên phiên bản danh mục<input value={name} required maxLength={120} disabled={locked || !reader.ready} onChange={event => setName(event.target.value)} /></label>
    <label>Dựa trên<select aria-label="Dựa trên" value={parent} disabled={locked || !reader.ready} onChange={event => {
      const version = reader.snapshot!.labels.find(row => row.id === event.target.value);
      setParent(event.target.value); setEntries(version ? version.entries.map(row => ({ ...row })) : reader.snapshot!.default_labels.map(name => ({
        id: crypto.randomUUID(), name, kind: name === "Không ký hiệu" ? "negative" : "sign",
      })));
    }}><option value="">Danh mục mặc định</option>{reader.snapshot!.labels.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label></div>
    <div className="data-label-editor">{entries.map((row, index) => <div key={row.id}>
      <input aria-label={`Ký hiệu ${index + 1}`} value={row.name} maxLength={80} required disabled={locked || !reader.ready} onChange={event => update(row.id, { name: event.target.value })} />
      <select aria-label={`Loại ký hiệu ${index + 1}`} value={row.kind} disabled={locked || !reader.ready || !!parent && reader.snapshot!.labels.find(item => item.id === parent)!.entries.some(item => item.id === row.id)}
        onChange={event => update(row.id, { kind: event.target.value as DataLabel["kind"] })}><option value="sign">Ký hiệu</option><option value="negative">Không ký hiệu</option></select>
      <button type="button" title="Bỏ khỏi phiên bản mới" aria-label={`Bỏ ký hiệu ${index + 1}`} disabled={locked || !reader.ready} onClick={() => setEntries(rows => rows.filter(item => item.id !== row.id))}><X size={16} aria-hidden="true" /></button>
    </div>)}</div><div className="data-inline-actions">
      <button type="button" disabled={locked || !reader.ready || entries.length >= 256} onClick={() => setEntries(rows => [...rows, { id: crypto.randomUUID(), name: "", kind: "sign" }])}><Plus size={16} aria-hidden="true" />Thêm ký hiệu</button>
      <button type="submit" disabled={locked || !reader.ready || !name.trim() || !entries.length || entries.some(row => !row.name.trim())}><Save size={16} aria-hidden="true" />Lưu phiên bản danh mục</button>
    </div></form>;
}

export function WorkspaceData({ reader, tab, onTabChange, datasetId, onDatasetChange, userId, locked, onUseSession, consent = false, onConsentChange, collectAside }: {
  reader: DataReader; tab: DataTab; onTabChange: (tab: DataTab) => void;
  datasetId: string; onDatasetChange: (id: string) => void; userId?: string; locked: boolean;
  onUseSession?: (session: DataSession) => void;
  consent?: boolean; onConsentChange?: (accepted: boolean) => void;
  /** Collect tab: shown beside the dataset card (the word picker), filling the header row's empty right side. */
  collectAside?: ReactNode;
}) {
  const data = reader.snapshot;
  const tabList = useRef<HTMLDivElement>(null), tabPanel = useRef<HTMLDivElement>(null);
  useTabMotion(tabList, tabs.findIndex(([key]) => key === tab), { panel: tabPanel });
  return <section className={`workspace-page workspace-data ${tab === "collect" ? "data-collect-header" : ""}`} aria-label="Quản lý dữ liệu">
    <PageHero title="Dữ liệu" titleId="workspace-data-title">
      <div ref={tabList} className="data-tabs page-tabs" role="tablist" aria-label="Dữ liệu workspace">{tabs.map(([key, name]) =>
      <button key={key} type="button" role="tab" id={`data-tab-${key}`} aria-controls="data-tab-panel" aria-selected={tab === key} disabled={locked && key !== tab} onClick={() => onTabChange(key)}>{name}</button>)}</div>
      <button type="button" className="data-refresh page-icon-button" title="Làm mới dữ liệu" aria-label="Làm mới dữ liệu" disabled={reader.busy} data-busy={reader.busy || undefined} onClick={() => void reader.refresh()}><RefreshCw size={18} aria-hidden="true" /></button></PageHero>
    {reader.busy && <p role="status" className="sr-only">Đang cập nhật dữ liệu...</p>}
    {reader.error && <div className="data-error" role="alert"><p>{reader.error}{reader.stale && " Đang hiển thị dữ liệu lần đọc trước."}</p></div>}
    {reader.failed && <button type="button" disabled={reader.busy} onClick={() => void reader.retry()}>Thử lại thao tác</button>}
    {!data && !reader.busy && !reader.error && <p>Chưa xác nhận được quyền truy cập dữ liệu.</p>}
    {!data && reader.busy && <SkeletonRegion>{tab === "collect"
      ? <div className="data-collection-selection page-card"><FieldBone label={130} w="min(100%, 360px)" /><TextBone w="70%" line={22} style={{ marginTop: 14 }} /></div>
      : [0, 1, 2].map(index => <div key={index} className="data-item page-card">
        <div className="data-item-heading"><Bone w={40} h={40} r="var(--radius-12)" /><TextBone w="30%" size={16} line={22} style={{ flex: "1 1 160px" }} /><PillBone w={84} /></div>
        <FactsBone className="data-facts" count={4} label="50%" value="40%" /></div>)}</SkeletonRegion>}
    {data && <div ref={tabPanel} role="tabpanel" id="data-tab-panel" aria-labelledby={`data-tab-${tab}`}>
      {tab === "collect" && <div className={`data-collect-top${collectAside ? " has-aside" : ""}`}><div className="data-collection-selection page-card"><label>Bộ dữ liệu đang thu<select aria-label="Bộ dữ liệu đang thu" value={datasetId} disabled={locked || !reader.ready || !data.permissions.collect || !data.collection_enabled} onChange={event => onDatasetChange(event.target.value)}>
        <option value="">Chọn bản nháp</option>{data.datasets.filter(row => row.status === "draft").map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
        {!data.collection_enabled && <p role="status">Thu dữ liệu chưa được bật.</p>}
        {data.collection_policy?.require_consent && <label className="data-consent"><input type="checkbox" checked={consent}
          disabled={locked || !reader.ready || !datasetId || !data.permissions.collect} onChange={event => onConsentChange?.(event.target.checked)} />
          Tôi đồng ý lưu video và dữ liệu mẫu cho workspace này.</label>}
        {!data.datasets.length && <p>Chưa có bộ dữ liệu.</p>}
        {!datasetId && <p role="status">Chưa chọn bộ dữ liệu nháp. Chỉ xem mẫu, chưa thể thu hoặc lưu.</p>}
        {!data.datasets.some(row => row.status === "draft") && data.permissions.manage &&
          <button type="button" disabled={locked || !reader.ready} onClick={() => onTabChange(data.labels.length ? "datasets" : "labels")}>
            <Plus size={16} aria-hidden="true" />{data.labels.length ? "Tạo bộ dữ liệu" : "Tạo danh mục ký hiệu"}
          </button>}
      </div>{collectAside && <div className="data-collect-aside">{collectAside}</div>}</div>}
      {tab === "datasets" && <>
        {data.permissions.manage && <DatasetForm reader={reader} locked={locked} />}
        {!data.datasets.length && <p>Chưa có bộ dữ liệu.</p>}
        {data.datasets.map(row => <DatasetItem key={row.id} dataset={row} reader={reader} locked={locked} />)}
      </>}
      {tab === "sessions" && <>
        {!data.sessions.length && <p>Chưa có phiên thu.</p>}
        {data.sessions.map(row => <article key={row.id} className="data-item page-card"><div className="data-item-heading"><span className="data-avatar" aria-hidden="true"><Folder size={18} /></span><h2>{data.datasets.find(dataset => dataset.id === row.dataset_version_id)?.name}</h2><span className={`page-status ${stateTones[row.state]}`}>{stateLabels[row.state]}</span></div>
          <dl className="data-facts"><div><dt>Mẫu đã lưu</dt><dd>{row.sample_count}</dd></div><div><dt>Bắt đầu</dt><dd>{time(row.created_at)}</dd></div>
            <div><dt>Cập nhật</dt><dd>{time(row.updated_at)}</dd></div><div><dt>Người thu</dt><dd>{row.created_by === userId ? "Bạn" : "Thành viên workspace"}</dd></div></dl>
          {data.permissions.collect && ["running", "paused"].includes(row.state) && (data.permissions.manage || row.created_by === userId) && <div className="data-inline-actions">
            {onUseSession && data.collection_enabled && row.created_by === userId && <button type="button" disabled={locked || !reader.ready} onClick={() => onUseSession(row)}>Thu tiếp</button>}
            <button type="button" disabled={locked || !reader.ready} onClick={() => void reader.mutate(`/sessions/${row.id}/state`, { state: "stopped" })}>Kết thúc phiên</button>
          </div>}
        </article>)}
      </>}
      {tab === "labels" && <>
        {data.labels.map(row => <article key={row.id} className="data-item page-card"><div className="data-item-heading"><span className="data-avatar" aria-hidden="true"><Tag size={18} /></span><h2>{row.name}</h2><span className="page-status">{row.entries.length} ký hiệu</span></div>
          <p>{time(row.created_at)}</p><details><summary>Xem danh mục</summary><ul className="data-counts">{row.entries.map(entry => <li key={entry.id}><span>{entry.name}</span><span>{entry.kind === "negative" ? "Không ký hiệu" : "Ký hiệu"}</span></li>)}</ul></details></article>)}
        {!data.labels.length && <p>Chưa có phiên bản danh mục.</p>}
        {data.permissions.manage && <><h2 className="data-section-title">Phiên bản danh mục mới</h2><LabelForm reader={reader} locked={locked} /></>}
      </>}
    </div>}
  </section>;
}
