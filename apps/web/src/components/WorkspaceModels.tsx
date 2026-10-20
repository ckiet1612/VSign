import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import type { AuthenticatedUser } from "../../../../contracts/v1/workspace";
import type { RegisteredModelSummary, WorkspaceModelsResponse } from "../../../../contracts/v1/models";
import type { RuntimeSnapshot } from "../hooks/useRuntimeStatus";
import { modelActionBlock, useWorkspaceModels, type ModelAction } from "../hooks/useWorkspaceModels";
import { Boxes, Check, Clock, FileCheck, RefreshCw, Rocket, Server, X } from "../icons";
import { LoginGate } from "./LoginGate";
import { WorkspaceRuntime } from "./WorkspaceRuntime";
import { CardHead, PageHero } from "./PageChrome";
import { Bone, CardHeadBone, FactsBone, FieldBone, PillBone, SkeletonRegion, TableBone, TextBone } from "./Skeleton";
import "../styles/models.css";

interface WorkspaceModelsProps {
  platformUrl: string;
  workspaceId: string;
  user: AuthenticatedUser | null;
  onLogin: (email: string, password: string) => Promise<void>;
  loginBusy?: boolean;
  sessionLoading?: boolean;
  authMode?: "session" | "local_admin";
  workspaceName?: string;
  runtime: RuntimeSnapshot;
  modelSelector?: ReactNode;
}

const statuses = { candidate: "Ứng viên", validated: "Đã đánh giá", approved: "Đã phê duyệt", active: "Đang hoạt động", baseline: "Baseline quan sát" };
const jobStatuses = { queued: "Đang chờ", loading: "Đang nạp", succeeded: "Thành công", failed: "Thất bại" };
const jobTone = { queued: "", loading: "is-running", succeeded: "is-success", failed: "is-failure" };
const modelTone = { candidate: "", validated: "", approved: "is-success", active: "is-running", baseline: "" };

// Gate metrics remain readable, but server-local paths and secret-shaped details never enter the page.
function safeText(value: string): string {
  if (/^\s*[{[]/.test(value)) return "Chi tiết không hiển thị.";
  return value.replace(/(?:https?:\/\/|[a-z]:[\\/]|~?\/)[^\s;,)]*/gi, "[đã ẩn đường dẫn]")
    .replace(/\b(token|password|secret|authorization|api[_-]?key)\s*[:=]\s*\S+/gi, "$1=[đã ẩn]").slice(0, 2000);
}
function endpointOrigin(value: string) {
  try { return new URL(value).origin; } catch { return "Chưa đọc endpoint"; }
}
const dateText = (value: string) => new Date(value).toLocaleString("vi-VN");
const modelName = (snapshot: WorkspaceModelsResponse, id: string | null) => id === null ? "Chưa có" :
  safeText(snapshot.models.find(model => model.id === id)?.model_version ?? id);
const confirmationSignature = (snapshot: WorkspaceModelsResponse) => JSON.stringify({
  target: snapshot.target, permissions: snapshot.permissions, models: snapshot.models,
});

function ConfirmAction({ title, children, onConfirm, onCancel, restoreFocusTo, disabled }: {
  title: string; children: ReactNode; onConfirm: () => void; onCancel: () => void; restoreFocusTo: HTMLElement | null; disabled: boolean;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog) {
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    }
    return () => { if (restoreFocusTo?.isConnected) restoreFocusTo.focus(); };
  }, [restoreFocusTo]);
  return <dialog ref={dialogRef} className="models-confirm" aria-labelledby={titleId} onCancel={event => { event.preventDefault(); onCancel(); }}>
    <h2 id={titleId}>{title}</h2>
    {children}
    <div className="models-actions">
      <button type="button" onClick={onCancel} autoFocus>Hủy</button>
      <button type="button" className="models-primary" disabled={disabled} onClick={onConfirm}>Xác nhận</button>
    </div>
  </dialog>;
}

function ValidationDetails({ model, snapshot }: { model: RegisteredModelSummary; snapshot: WorkspaceModelsResponse }) {
  const validation = model.validation;
  return <>
    <dl className="models-details">
      <div><dt>ID mô hình</dt><dd>{safeText(model.id)}</dd></div>
      <div><dt>Source run</dt><dd>{safeText(model.source_run_id)}</dd></div>
      <div><dt>Đăng ký lúc</dt><dd><time dateTime={model.created_at}>{dateText(model.created_at)}</time></dd></div>
      <div><dt>SHA256 artifact</dt><dd><code>{model.artifact_sha256}</code></dd></div>
      <div><dt>SHA256 bộ nhãn</dt><dd><code>{model.labels_sha256}</code></dd></div>
      <div><dt>Phê duyệt bởi</dt><dd>{model.approved_by ? safeText(model.approved_by) : "Chưa phê duyệt"}</dd></div>
      {model.approved_at && <div><dt>Phê duyệt lúc</dt><dd><time dateTime={model.approved_at}>{dateText(model.approved_at)}</time></dd></div>}
    </dl>
    {!validation ? <p className="models-note">Chưa có báo cáo đánh giá.</p> : <>
      <dl className="models-details">
        <div><dt>Đánh giá</dt><dd>{validation.passed ? "Đạt" : "Không đạt"}</dd></div>
        <div><dt>ID đánh giá</dt><dd>{safeText(validation.id)}</dd></div>
        <div><dt>Baseline đánh giá</dt><dd>{modelName(snapshot, validation.baseline_model_id)}</dd></div>
        <div><dt>SHA256 báo cáo</dt><dd><code>{validation.report_sha256}</code></dd></div>
        <div><dt>Đánh giá lúc</dt><dd><time dateTime={validation.created_at}>{dateText(validation.created_at)}</time></dd></div>
      </dl>
      {validation.baseline_model_id !== snapshot.target?.active_model_id &&
        <p className="models-warning" role="status">Báo cáo không khớp baseline hiện tại.</p>}
      {validation.checks.length === 0 ? <p className="models-note">Chưa có kiểm tra trong báo cáo.</p> :
        <ul className="models-checks" aria-label="Kiểm tra đánh giá">{validation.checks.map((check, index) => <li key={index}>
          <span className={`models-check-result ${check.passed ? "is-success" : "is-failure"}`}>
            {check.passed ? <Check size={16} aria-hidden="true" /> : <X size={16} aria-hidden="true" />}{check.passed ? "Đạt" : "Không đạt"}
          </span>
          <div><strong>{safeText(check.name)}</strong><p>{safeText(check.detail)}</p></div>
        </li>)}</ul>}
    </>}
  </>;
}

type ModelsReader = ReturnType<typeof useWorkspaceModels>;
function PrivateModels({ reader }: { reader: ModelsReader }) {
  const [manifestPath, setManifestPath] = useState("");
  const [artifactPath, setArtifactPath] = useState("");
  const [labelsPath, setLabelsPath] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [report, setReport] = useState({ modelId: "", path: "" });
  const [confirmation, setConfirmation] = useState<{ action: ModelAction; signature: string; name: string; trigger: HTMLElement | null } | null>(null);
  const [notice, setNotice] = useState("");
  const snapshot = reader.snapshot;
  const signature = snapshot ? confirmationSignature(snapshot) : "";
  const confirmationInvalid = !!confirmation && (!snapshot || reader.access !== "ready" || reader.stale || !!reader.error ||
    confirmation.signature !== signature || !!modelActionBlock(snapshot, confirmation.action));
  useEffect(() => {
    if (confirmationInvalid) setConfirmation(null);
  }, [confirmationInvalid]);
  if (!snapshot) return null;
  const { target } = snapshot;
  const selected = snapshot.models.find(model => model.id === selectedId);
  const revision = target?.revision ?? -1;
  const reportPath = report.modelId === selectedId ? report.path : "";
  const registerAction: ModelAction = { type: "register", manifest_path: manifestPath, artifact_path: artifactPath, labels_path: labelsPath };
  const rollbackAction: ModelAction = { type: "rollback", expected_revision: revision };
  const blocked = (action: ModelAction) => !reader.canMutate ? "Dữ liệu chưa sẵn sàng để thay đổi." : modelActionBlock(snapshot, action);
  const confirm = (action: ModelAction, name: string) => {
    if (!blocked(action)) {
      setNotice("");
      setConfirmation({ action, name, signature: confirmationSignature(snapshot), trigger: document.activeElement instanceof HTMLElement ? document.activeElement : null });
    }
  };
  const submit = async (action: ModelAction) => {
    setNotice("");
    const accepted = await reader.mutate(action);
    if (accepted) {
      setNotice(action.type === "deploy" || action.type === "rollback" ? "Đã gửi yêu cầu. Kết quả theo trạng thái tác vụ." : "Đã cập nhật sổ mô hình.");
      if (action.type === "register") { setManifestPath(""); setArtifactPath(""); setLabelsPath(""); }
      if (action.type === "validate") setReport({ modelId: action.model_id, path: "" });
    }
  };
  const validConfirmation = confirmation && !confirmationInvalid;
  return <>
    <section className="models-section page-card" aria-label="Production">
      <CardHead icon={Rocket} title="Production">{target && <span className="page-status">Revision {target.revision}</span>}</CardHead>
      {!target ? <p className="models-note">Chưa cấu hình production target.</p> : <>
        <dl className="models-details">
          <div><dt>Target</dt><dd>{safeText(target.target_id)}</dd></div>
          <div><dt>Runtime production</dt><dd>{endpointOrigin(target.runtime_url)}</dd></div>
          <div><dt>Backend</dt><dd>{safeText(target.backend)}</dd></div>
          <div><dt>Đang phục vụ (pointer)</dt><dd>{modelName(snapshot, target.active_model_id)}</dd></div>
          <div><dt>Mô hình trước</dt><dd>{modelName(snapshot, target.previous_model_id)}</dd></div>
          <div><dt>Baseline quan sát</dt><dd>{modelName(snapshot, target.observed_model_id)}</dd></div>
          <div><dt>Worker</dt><dd>{target.worker_online ? "Trực tuyến" : "Ngoại tuyến"}</dd></div>
          <div><dt>Tác vụ đang chờ</dt><dd>{target.pending_job_id ? safeText(target.pending_job_id) : "Không có"}</dd></div>
        </dl>
        {!target.worker_online && <p className="models-warning" role="status">Runtime production ngoại tuyến.</p>}
        <div className="models-actions"><button type="button" disabled={!!blocked(rollbackAction)} title={blocked(rollbackAction) || undefined}
          onClick={() => confirm(rollbackAction, modelName(snapshot, target.previous_model_id))}>Hoàn tác</button>
          {blocked(rollbackAction) && <span className="models-note">{blocked(rollbackAction)}</span>}</div>
      </>}
    </section>

    <section className="models-section page-card" aria-labelledby="models-registry-title">
      <CardHead icon={Boxes} id="models-registry-title" title="Sổ mô hình" />
      {snapshot.models.length === 0 ? <p className="models-note">Chưa có mô hình đăng ký.</p> : <div className="models-table-scroll">
        <table className="models-table" aria-label="Sổ mô hình"><thead><tr>
          <th scope="col">Mô hình</th><th scope="col">Backend</th><th scope="col">Bộ nhãn</th><th scope="col">Trạng thái</th><th scope="col">Thao tác</th>
        </tr></thead><tbody>{snapshot.models.map(model => {
          const name = safeText(model.model_version);
          const deploy: ModelAction = { type: "deploy", model_id: model.id, expected_revision: revision };
          const reason = blocked(deploy);
          return <tr key={model.id} aria-selected={selectedId === model.id}>
            <th scope="row">{name}<small>{model.origin === "baseline" ? "Baseline quan sát" : "Ứng viên"}</small></th>
            <td>{safeText(model.backend)}</td><td>{model.labels_count} nhãn</td>
            <td><span className={`page-status ${modelTone[model.status]}`}>{statuses[model.status]}</span></td><td><div className="models-actions">
              <button type="button" aria-label={`Chi tiết ${name}`} aria-expanded={selectedId === model.id} aria-controls="models-selected"
                onClick={() => { setSelectedId(selectedId === model.id ? null : model.id); setNotice(""); }}>{selectedId === model.id ? "Đóng chi tiết" : "Chi tiết"}</button>
              {model.origin === "candidate" && <button type="button" aria-label={`Triển khai ${name}`} disabled={!!reason} title={reason || undefined}
                onClick={() => confirm(deploy, name)}>Triển khai</button>}
            </div></td>
          </tr>;
        })}</tbody></table>
      </div>}
      {selected && <section id="models-selected" className="models-selected" aria-label={`Chi tiết ${safeText(selected.model_version)}`}>
        <h3>{safeText(selected.model_version)}</h3>
        <ValidationDetails model={selected} snapshot={snapshot} />
        {selected.origin === "candidate" && <>
          <form className="models-report-form" onSubmit={event => { event.preventDefault(); void submit({ type: "validate", model_id: selected.id, report_path: reportPath }); }}>
            <label>Báo cáo đánh giá<input type="text" required autoComplete="off" spellCheck={false} disabled={!reader.canMutate || !snapshot.permissions.validate}
              value={reportPath} onChange={event => setReport({ modelId: selected.id, path: event.target.value })} /></label>
            <button type="submit" disabled={!!blocked({ type: "validate", model_id: selected.id, report_path: reportPath })}>Nhập báo cáo</button>
          </form>
          {(() => {
            const approve: ModelAction = { type: "approve", model_id: selected.id, validation_id: selected.validation?.id ?? "" };
            const reason = blocked(approve);
            return <div className="models-actions"><button type="button" disabled={!!reason} title={reason || undefined}
              onClick={() => confirm(approve, safeText(selected.model_version))}>Phê duyệt</button>{reason && <span className="models-note">{reason}</span>}</div>;
          })()}
        </>}
      </section>}
    </section>

    {snapshot.permissions.register && <section className="models-section page-card" aria-labelledby="models-register-title">
      <CardHead icon={FileCheck} id="models-register-title" title="Đăng ký ứng viên" />
      <form className="models-register-form" onSubmit={event => { event.preventDefault(); void submit(registerAction); }}>
        <label>Manifest<input type="text" required autoComplete="off" spellCheck={false} disabled={!reader.canMutate} value={manifestPath} onChange={event => setManifestPath(event.target.value)} /></label>
        <label>Artifact<input type="text" required autoComplete="off" spellCheck={false} disabled={!reader.canMutate} value={artifactPath} onChange={event => setArtifactPath(event.target.value)} /></label>
        <label>Bộ nhãn<input type="text" required autoComplete="off" spellCheck={false} disabled={!reader.canMutate} value={labelsPath} onChange={event => setLabelsPath(event.target.value)} /></label>
        <button type="submit" className="models-primary" disabled={!!blocked(registerAction)}>Đăng ký ứng viên</button>
      </form>
    </section>}

    <section className="models-section page-card" aria-label="Lịch sử triển khai">
      <CardHead icon={Clock} title="Lịch sử triển khai" />
      {snapshot.deployments.length === 0 ? <p className="models-note">Chưa có tác vụ triển khai.</p> : <ol className="models-jobs">{snapshot.deployments.map(job => <li key={job.id}>
        <div className="models-section-heading"><h3>{job.operation === "deploy" ? "Triển khai" : "Hoàn tác"} · {modelName(snapshot, job.to_model_id)}</h3>
          <span className={`models-job-status page-status ${jobTone[job.status]}`} role="status">{jobStatuses[job.status]}</span></div>
        <dl className="models-details">
          <div><dt>ID tác vụ</dt><dd>{safeText(job.id)}</dd></div>
          <div><dt>Từ mô hình</dt><dd>{modelName(snapshot, job.from_model_id)}</dd></div>
          <div><dt>Revision yêu cầu</dt><dd>{job.expected_revision}</dd></div>
          <div><dt>Người yêu cầu</dt><dd>{safeText(job.requested_by)}</dd></div>
          <div><dt>Tạo lúc</dt><dd><time dateTime={job.created_at}>{dateText(job.created_at)}</time></dd></div>
          {job.finished_at && <div><dt>Kết thúc lúc</dt><dd><time dateTime={job.finished_at}>{dateText(job.finished_at)}</time></dd></div>}
        </dl>
        {job.status === "failed" && <p className="models-warning">Không thể hoàn tất tác vụ. Kiểm tra nhật ký máy chủ; production pointer không được suy ra từ yêu cầu này.</p>}
      </li>)}</ol>}
    </section>
    {notice && !reader.error && <p className="models-notice" role="status">{notice}</p>}
    {validConfirmation && <ConfirmAction title={confirmation.action.type === "approve" ? "Phê duyệt mô hình?" : confirmation.action.type === "deploy" ? "Triển khai production?" : "Hoàn tác production?"}
      restoreFocusTo={confirmation.trigger}
      disabled={!reader.canMutate}
      onCancel={() => setConfirmation(null)} onConfirm={() => { if (blocked(confirmation.action)) return; const action = confirmation.action; setConfirmation(null); void submit(action); }}>
      <p>{confirmation.name}</p>
      {confirmation.action.type === "approve" ? <p>Đánh giá {"validation_id" in confirmation.action ? safeText(confirmation.action.validation_id) : ""} · Baseline {modelName(snapshot, target?.active_model_id ?? null)}</p>
        : <p>{safeText(target?.target_id ?? "")} · {safeText(target?.backend ?? "")} · Revision {revision}</p>}
    </ConfirmAction>}
  </>;
}

// First read of the registry: Production, registry table, register form and history cards at their loaded size.
function RegistrySkeleton() {
  return <>
    <div className="models-section page-card"><CardHeadBone title={84} pill={90} /><FactsBone className="models-details" count={9} />
      <div className="models-actions"><Bone w={94} h={40} r="var(--radius-12)" /><TextBone w={180} /></div></div>
    <div className="models-section page-card"><CardHeadBone title={84} />
      <div className="models-table-scroll"><TableBone className="models-table" rows={2} columns={["75%", "50%", "60%", "pill", "70%"]} /></div></div>
    <div className="models-section page-card"><CardHeadBone title={120} />
      <div className="models-register-form">{[0, 1, 2].map(index => <FieldBone key={index} label={112} />)}<Bone w={145} h={40} r="var(--radius-12)" /></div></div>
    <div className="models-section page-card"><CardHeadBone title={120} /><TextBone w={180} /></div>
  </>;
}

function CustomerModelsSkeleton() {
  return <>
    <div className="models-section page-card"><CardHeadBone title={130} pill={110} /><FactsBone className="models-details" count={2} /></div>
    <div className="models-section page-card"><CardHeadBone title={110} />
      <ul className="models-jobs">{[0, 1].map(index => <li key={index}><div className="models-section-heading"><TextBone w={140} /><PillBone w={90} /></div>
        <FactsBone className="models-details" count={3} /></li>)}</ul></div>
  </>;
}

export function InternalModelRegistry({ platformUrl, workspaceId, user, onLogin, loginBusy = false, sessionLoading = false, authMode = "session", workspaceName = "VSign workspace", runtime, modelSelector }: WorkspaceModelsProps) {
  const reader = useWorkspaceModels({ platformUrl, workspaceId, user });
  const sessionKey = JSON.stringify([platformUrl, workspaceId, user?.id, user?.email, user?.role]);
  return <div className="workspace-page models-page">
    <PageHero title="Mô hình & triển khai">{!sessionLoading && reader.access !== "login_required" && reader.access !== "forbidden" &&
      <button type="button" className="models-refresh page-icon-button" aria-label="Làm mới mô hình" title="Làm mới mô hình"
        disabled={reader.busy} data-busy={reader.busy || undefined} onClick={() => void reader.refresh()}><RefreshCw size={18} aria-hidden="true" /></button>}</PageHero>
    <section className="models-observed page-card" aria-labelledby="models-observed-title">
      <CardHead icon={Server} id="models-observed-title" title="Runtime đang chọn · Dev/Test" />
      <p className="models-note">{endpointOrigin(runtime.endpoint)}</p>
      {modelSelector && <div className="models-selector">{modelSelector}</div>}
      <WorkspaceRuntime runtime={runtime} />
    </section>
    {sessionLoading ? <SkeletonRegion label="Đang tải workspace..."><RegistrySkeleton /></SkeletonRegion> : reader.access === "login_required" ? authMode === "local_admin"
      ? <p role="alert">Chưa xác nhận được quyền admin local. Hãy làm mới workspace.</p>
      : <LoginGate key={sessionKey} workspaceName={workspaceName} busy={loginBusy} embedded onLogin={async (email, password) => {
      await onLogin(email, password);
      await reader.refresh();
    }} />
      : reader.access === "forbidden" ? <p className="models-warning" role="alert">Bạn không có quyền truy cập sổ mô hình.</p> : <>
        <div className="models-toolbar"><span role="status">{!reader.snapshot && reader.busy ? <><span className="sr-only">Đang tải mô hình...</span><TextBone w={180} size={12} line={20} /></>
          : reader.busy ? "Đang cập nhật mô hình..." : reader.stale ? "Dữ liệu cũ" : reader.updatedAt ? `Cập nhật: ${new Date(reader.updatedAt).toLocaleString("vi-VN")}` : ""}</span></div>
        {reader.error && <div className="models-error" role="alert"><p>{reader.error}{reader.stale ? " Đang hiển thị dữ liệu cũ; mọi thay đổi đã tạm khóa." : ""}</p>
          <button type="button" disabled={reader.busy} onClick={() => void reader.refresh()}>Thử lại</button></div>}
        {!reader.snapshot && reader.busy && <SkeletonRegion><RegistrySkeleton /></SkeletonRegion>}
        <div aria-busy={reader.busy}><PrivateModels key={sessionKey} reader={reader} /></div>
      </>}
  </div>;
}

export function WorkspaceModels(props: WorkspaceModelsProps) {
  return props.user?.role === "system_admin" || props.user?.role === "model_admin"
    ? <InternalModelRegistry {...props} /> : <CustomerWorkspaceModels {...props} />;
}

function CustomerWorkspaceModels({ platformUrl, workspaceId, user, onLogin, loginBusy = false,
  sessionLoading = false, authMode = "session", workspaceName = "VSign workspace" }: WorkspaceModelsProps) {
  const reader = useWorkspaceModels({ platformUrl, workspaceId, user });
  const snapshot = reader.snapshot;
  const target = snapshot?.target;
  const active = snapshot?.models.find(model => model.id === target?.active_model_id);
  const live = !!active && !!target?.worker_online && target.observed_model_id === active.id;
  const state = reader.stale ? "Dữ liệu lần đọc trước" : !target ? "Chưa kết nối dịch vụ" : target.pending_job_id
    ? "Đang cập nhật phiên bản" : live ? "Đang hoạt động" : "Chưa xác nhận hoạt động";
  return <div className="workspace-page models-page">
    <PageHero title="Mô hình nhận dạng">{!sessionLoading && reader.access !== "login_required" && reader.access !== "forbidden" &&
      <button type="button" className="models-refresh page-icon-button" aria-label="Làm mới mô hình" title="Làm mới mô hình"
        disabled={reader.busy} data-busy={reader.busy || undefined} onClick={() => void reader.refresh()}><RefreshCw size={18} aria-hidden="true" /></button>}</PageHero>
    {sessionLoading ? <SkeletonRegion label="Đang tải workspace..."><CustomerModelsSkeleton /></SkeletonRegion> : reader.access === "login_required" ? authMode === "local_admin"
      ? <p role="alert">Chưa xác nhận được quyền quản trị doanh nghiệp. Hãy làm mới workspace.</p>
      : <LoginGate workspaceName={workspaceName} busy={loginBusy} embedded onLogin={async (email, password) => {
        await onLogin(email, password); await reader.refresh();
      }} /> : reader.access === "forbidden" ? <p role="alert">Bạn không có quyền xem thông tin mô hình.</p> : <>
      <div className="models-toolbar">
        <span role="status">{!snapshot && reader.busy ? <><span className="sr-only">Đang tải thông tin...</span><TextBone w={180} size={12} line={20} /></>
          : reader.busy ? "Đang cập nhật thông tin..." : reader.updatedAt ? `Kiểm tra gần nhất: ${dateText(new Date(reader.updatedAt).toISOString())}` : ""}</span>
      </div>
      {reader.error && <div className="models-error" role="alert"><p>{reader.error}{reader.stale && " Đang hiển thị dữ liệu lần đọc trước."}</p>
        <button type="button" disabled={reader.busy} onClick={() => void reader.refresh()}>Thử lại</button></div>}
      {!snapshot && reader.busy && <SkeletonRegion><CustomerModelsSkeleton /></SkeletonRegion>}
      {snapshot && <>
        <section className="models-section page-card" aria-labelledby="business-model-title">
          <CardHead icon={Boxes} id="business-model-title" title="Phiên bản đang dùng">
            <span className={`page-status ${!reader.stale && live && !target?.pending_job_id ? "models-notice is-success" : "models-note"}`}>{state}</span></CardHead>
          {active ? <dl className="models-details">
            <div><dt>Phiên bản</dt><dd>{safeText(active.model_version)}</dd></div>
            <div><dt>Ký hiệu hỗ trợ</dt><dd>{active.labels_count} ký hiệu</dd></div>
          </dl> : <p className="models-note">Chưa có phiên bản được xác nhận cho workspace này.</p>}
        </section>
        <section className="models-section page-card" aria-labelledby="business-model-history-title">
          <CardHead icon={Clock} id="business-model-history-title" title="Lịch sử cập nhật" />
          {snapshot.deployments.length === 0 ? <p className="models-note">Chưa có lần cập nhật nào được ghi nhận.</p>
            : <ul className="models-jobs">{snapshot.deployments.map(job => <li key={job.id}>
              <div className="models-section-heading"><h3>{job.operation === "rollback" ? "Khôi phục phiên bản" : "Cập nhật phiên bản"}</h3>
                <span className={`models-job-status page-status ${jobTone[job.status]}`}>{jobStatuses[job.status]}</span></div>
              <dl className="models-details">
                <div><dt>Phiên bản trước</dt><dd>{modelName(snapshot, job.from_model_id) === job.from_model_id ? "Chưa có thông tin" : modelName(snapshot, job.from_model_id)}</dd></div>
                <div><dt>Phiên bản cập nhật</dt><dd>{modelName(snapshot, job.to_model_id) === job.to_model_id ? "Chưa có thông tin" : modelName(snapshot, job.to_model_id)}</dd></div>
                <div><dt>Thời gian</dt><dd><time dateTime={job.finished_at ?? job.created_at}>{dateText(job.finished_at ?? job.created_at)}</time></dd></div>
              </dl>
              {job.status === "failed" && <p className="models-warning">Cập nhật không thành công.</p>}
            </li>)}</ul>}
        </section>
      </>}
    </>}
  </div>;
}
