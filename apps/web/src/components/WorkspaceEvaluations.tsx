import { useState } from 'react';
import type { AuthenticatedUser } from '../../../../contracts/v1/workspace';
import type { EvaluationRun, EvaluationMetrics } from '../../../../contracts/v1/evaluations';
import { useWorkspaceEvaluations, type EvaluationAction } from '../hooks/useWorkspaceEvaluations';
import { BarChart3, Check, Play, RefreshCw, ShieldCheck, Stack, X } from '../icons';
import { CardHead, PageHero } from './PageChrome';
import '../styles/evaluations.css';
import { Bone, CardHeadBone, FactsBone, FieldBone, PillBone, SkeletonRegion, TableBone, TextBone } from "./Skeleton";

interface Props { platformUrl:string;workspaceId:string;user:AuthenticatedUser | null }
type Reader=ReturnType<typeof useWorkspaceEvaluations>;
const statuses={queued:'Đang chờ',running:'Đang đánh giá',completed:'Hoàn tất',failed:'Thất bại',cancelled:'Đã hủy'};
const tones={queued:'',running:'is-running',completed:'is-success',failed:'is-failure',cancelled:''};
const checks:Record<string,string>={identity:'Đúng model và cấu hình',dataset_snapshot:'Bản dữ liệu bất biến',held_out:'Dữ liệu ngoài huấn luyện',
  independent_negatives:'Mẫu không ký hiệu độc lập',macro_f1:'Chất lượng tổng hợp',false_accept_rate:'Tỷ lệ nhận nhầm',
  latency_p95:'Thời gian suy luận',per_class_recall:'Chất lượng từng ký hiệu',trusted_provenance:'Nguồn dữ liệu đã xác minh'};
const percent=(n:number | null) => n === null ? 'Chưa có' : `${(n*100).toLocaleString('vi-VN',{maximumFractionDigits:1})}%`;
const date=(value:string) => new Date(value).toLocaleString('vi-VN');

function Comparison({run}:{run:EvaluationRun}) {
  if (!run.report) return null;
  const {baseline,candidate}=run.report;
  const rows:[string,keyof Pick<EvaluationMetrics,'accuracy'|'macro_f1'|'false_accept_rate'|'latency_p95_ms'>][]=[
    ['Độ chính xác','accuracy'],['F1 trung bình các ký hiệu','macro_f1'],['Nhận nhầm mẫu không ký hiệu','false_accept_rate'],['P95 suy luận (ms)','latency_p95_ms']];
  return <>
    <h3>So sánh trên cùng bản dữ liệu</h3>
    <div className="evaluations-table" tabIndex={0} role="region" aria-label="So sánh model">
      <table><thead><tr><th scope="col">Chỉ số</th><th scope="col">Production đối chiếu</th><th scope="col">Model đánh giá</th></tr></thead>
        <tbody>{rows.map(([title,key]) => <tr key={key}><th scope="row">{title}</th>
          {[baseline,candidate].map((m,i) => <td key={i}>{key === 'latency_p95_ms' ? m[key].toLocaleString('vi-VN',{maximumFractionDigits:2}) : percent(m[key])}</td>)}</tr>)}</tbody></table>
    </div>
    <p className="evaluations-muted">{run.report.positive_count} mẫu ký hiệu · {run.report.negative_count} mẫu không ký hiệu. Thời gian chỉ tính suy luận, không gồm thu và đọc video.</p>
    <h3>Kết quả từng ký hiệu</h3>
    <div className="evaluations-table" tabIndex={0} role="region" aria-label="Kết quả từng ký hiệu">
      <table><thead><tr><th scope="col">Ký hiệu</th><th scope="col">Số mẫu</th><th scope="col">Nhận đúng trước</th><th scope="col">Nhận đúng sau</th><th scope="col">Lỗi sau</th></tr></thead>
        <tbody>{candidate.per_class.map(row => <tr key={row.label}><th scope="row">{row.label}</th><td>{row.support}</td>
          <td>{percent(baseline.per_class.find(item => item.label === row.label)?.recall ?? null)}</td><td>{percent(row.recall)}</td><td>{row.errors}</td></tr>)}</tbody></table>
    </div>
  </>;
}

function RunDetails({run,reader}:{run:EvaluationRun;reader:Reader}) {
  return <section className="evaluations-detail page-card" aria-label="Chi tiết đánh giá">
    <div className="evaluations-detail-header"><h2>{run.model_version}</h2><span className={`evaluations-status page-status ${tones[run.status]}`}>{statuses[run.status]}</span></div>
    <dl className="evaluations-facts">
      <div><dt>Production đối chiếu</dt><dd>{run.baseline_model_version}</dd></div>
      <div><dt>Bản dữ liệu</dt><dd>{reader.snapshot?.snapshots.find(s => s.id === run.snapshot_id)?.dataset_name ?? run.dataset_version}</dd></div>
      <div><dt>Tạo lúc</dt><dd><time dateTime={run.created_at}>{date(run.created_at)}</time></dd></div>
      <div><dt>Tiến độ</dt><dd>{run.progress} / {run.sample_count*2} lượt suy luận</dd></div>
    </dl>
    {!run.baseline_current && <p className="evaluations-warning" role="status">Production đã thay đổi. Kết quả này không còn đủ để triển khai với baseline hiện tại.</p>}
    {run.status === 'queued' && <p className="evaluations-muted">{reader.snapshot?.workers[run.backend] ? 'Đang chờ worker nhận lượt đánh giá.' : 'Đang chờ worker đánh giá kết nối.'}</p>}
    {run.status === 'running' && <progress max={run.sample_count*2} value={run.progress} aria-label="Tiến độ đánh giá" />}
    {run.error && <p className="evaluations-warning" role="status">{run.error}</p>}
    {['queued','running'].includes(run.status) && reader.snapshot?.permissions.cancel &&
      <button type="button" disabled={!reader.canMutate} onClick={() => void reader.mutate({type:'cancel',id:run.id})}><X size={16} aria-hidden="true" />Hủy lượt đánh giá</button>}
    <Comparison run={run} />
    {run.gate && <section className="evaluations-gate" aria-label="Chốt chất lượng">
      <h3><ShieldCheck size={18} aria-hidden="true" />{run.gate.passed && run.baseline_current ? 'Đạt chốt chất lượng' : run.gate.passed ? 'Đã đạt ở baseline cũ' : 'Chưa đạt chốt chất lượng'}</h3>
      <ul>{run.gate.checks.map(check => <li key={check.name}>
        <span className={check.passed ? 'evaluations-pass' : 'evaluations-fail'}>{check.passed ? <Check size={16} aria-hidden="true" /> : <X size={16} aria-hidden="true" />}{check.passed ? 'Đạt' : 'Chưa đạt'}</span>
        <div><strong>{checks[check.name] ?? check.name}</strong><p>{check.detail}</p></div>
      </li>)}</ul>
    </section>}
    <details className="evaluations-evidence"><summary>Định danh bản đánh giá</summary><dl>
      <dt>Phiên bản dữ liệu</dt><dd><code>{run.dataset_version}</code></dd>
      <dt>SHA256 snapshot</dt><dd><code>{run.snapshot_sha256}</code></dd>
      <dt>Mã lượt đánh giá</dt><dd><code>{run.id}</code></dd>
    </dl></details>
  </section>;
}

// First read: create form, run list and the selected run's detail card at their loaded size.
function EvaluationsSkeleton() {
  return <SkeletonRegion label="Đang tải đánh giá...">
    <div className="evaluations-create page-card">{[0, 1].map(index => <FieldBone key={index} className="skeleton-eval-field" label={140} />)}<Bone w={176} h={40} r="var(--radius-12)" /></div>
    <div className="evaluations-layout">
      <div className="evaluations-runs page-card"><CardHeadBone title={100} />{[0, 1, 2].map(index => <span key={index} className="skeleton-eval-run">
        <TextBone w={150} /><PillBone w={84} /><TextBone w={96} size={11} line={14} /></span>)}</div>
      <div className="evaluations-detail page-card"><div className="evaluations-detail-header"><TextBone w={220} size={18} line={24} /><PillBone w={92} /></div>
        <FactsBone className="evaluations-facts" count={4} />
        <div className="evaluations-table"><TableBone columns={['55%', '50%', '50%', '50%']} rows={4} /></div></div>
    </div>
  </SkeletonRegion>;
}

function EvaluationContent({reader}:{reader:Reader}) {
  const [modelId,setModelId]=useState(''),[snapshotId,setSnapshotId]=useState(''),[selectedId,setSelectedId]=useState('');
  const [retry,setRetry]=useState<Extract<EvaluationAction,{type:'create'}> | null>(null);
  const snapshot=reader.snapshot;
  if (!snapshot) return reader.busy ? <EvaluationsSkeleton /> : <p role="status" className="evaluations-muted">Chưa có dữ liệu đánh giá.</p>;
  const selected=snapshot.runs.find(r => r.id === selectedId) ?? snapshot.runs[0];
  const retryKnown=retry && snapshot.runs.some(r => r.id === retry.request_id);
  const waiting=retry !== null && !retryKnown;
  const chosenModel=snapshot.models.find(m => m.id === modelId);
  const create=async () => {
    if (retryKnown && retry) {setSelectedId(retry.request_id);setRetry(null);return;}
    const action=retry ?? {type:'create' as const,request_id:crypto.randomUUID(),model_id:modelId,snapshot_id:snapshotId};
    setRetry(action);
    if (await reader.mutate(action)) {setSelectedId(action.request_id);setRetry(null);}
  };
  return <>
    {snapshot.permissions.create && <form className="evaluations-create page-card" onSubmit={event => {event.preventDefault();void create();}}>
      <label>Model cần đánh giá<select aria-label="Model cần đánh giá" value={modelId} disabled={!reader.canMutate || waiting} onChange={event => setModelId(event.target.value)}>
        <option value="">Chọn model</option>{snapshot.models.map(m => <option key={m.id} value={m.id}>{m.model_version}{m.active ? ' · Production' : ''}</option>)}</select></label>
      <label>Bản dữ liệu đã chốt<select aria-label="Bản dữ liệu đã chốt" value={snapshotId} disabled={!reader.canMutate || waiting} onChange={event => setSnapshotId(event.target.value)}>
        <option value="">Chọn bản dữ liệu</option>{snapshot.snapshots.map(s => <option key={s.id} value={s.id}>{s.dataset_name} · {s.sample_count} mẫu · {s.id.slice(0,8)}</option>)}</select></label>
      <button type="submit" className="evaluations-primary" disabled={!reader.canMutate || (!retry && (!chosenModel || !snapshotId || !snapshot.active_model_id || snapshot.runs.some(r => ['queued','running'].includes(r.status))))}>
        <Play size={16} aria-hidden="true" />{retryKnown ? 'Xem lượt đã tạo' : retry ? 'Thử lại yêu cầu' : 'Tạo lượt đánh giá'}</button>
      {waiting && !reader.busy && <button type="button" onClick={() => setRetry(null)}>Đóng yêu cầu đang thử lại</button>}
    </form>}
    {snapshot.permissions.create && (!snapshot.models.length || !snapshot.snapshots.length || !snapshot.active_model_id) &&
      <p className="evaluations-muted">{!snapshot.active_model_id ? 'Chưa có model production để đối chiếu.' : !snapshot.snapshots.length ? 'Chưa có bản dữ liệu đã chốt.' : 'Chưa có model trong danh mục.'}</p>}
    {chosenModel && snapshot.workers[chosenModel.backend] !== true && <p className="evaluations-warning" role="status">Worker {chosenModel.backend} chưa kết nối. Yêu cầu mới sẽ ở trạng thái chờ.</p>}
    {!snapshot.runs.length ? <p className="evaluations-empty page-card"><BarChart3 size={22} aria-hidden="true" />Chưa có lượt đánh giá.</p> : <div className="evaluations-layout">
      <nav className="evaluations-runs page-card" aria-label="Các lượt đánh giá"><CardHead icon={Stack} title="Lượt đánh giá" />{snapshot.runs.map(run =>
        <button type="button" key={run.id} aria-current={selected?.id === run.id ? 'true' : undefined} onClick={() => setSelectedId(run.id)}>
          <strong>{run.model_version}</strong><span className={`evaluations-status page-status ${tones[run.status]}`}>{statuses[run.status]}</span><time dateTime={run.created_at}>{date(run.created_at)}</time>
        </button>)}</nav>
      {selected && <RunDetails run={selected} reader={reader} />}
    </div>}
  </>;
}

export function WorkspaceEvaluations(props:Props) {
  const reader=useWorkspaceEvaluations(props);
  return <section className="workspace-page evaluations-page" aria-labelledby="workspace-page-title">
    <PageHero title={props.user?.role==='system_admin'?'Đánh giá mô hình':'Đánh giá'}>
      <button type="button" className="page-icon-button" title="Làm mới đánh giá" aria-label="Làm mới đánh giá" disabled={reader.busy} onClick={() => void reader.refresh()}><RefreshCw size={18} aria-hidden="true" /></button></PageHero>
    {reader.access !== 'ready' ? <p role="status">{reader.access === 'forbidden' ? 'Bạn không có quyền xem đánh giá.' : 'Chưa xác nhận được quyền workspace.'}</p> : <>
      {reader.error && <p className="evaluations-warning" role="alert">{reader.error}</p>}
      {reader.stale && <p className="evaluations-muted" role="status">Đang hiển thị dữ liệu cũ. Các thao tác tạm khóa.</p>}
      <EvaluationContent key={`${props.platformUrl}:${props.workspaceId}:${props.user?.id}:${props.user?.role}`} reader={reader} />
    </>}
  </section>;
}
