import type { AuthenticatedUser } from "../../../../contracts/v1/workspace";
import type { WorkspaceModelsResponse } from "../../../../contracts/v1/models";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { workspaceRequest, WorkspaceApiError } from "../lib/workspaceApi";
import { forgetView, readViewCache, rememberView, viewCacheKey } from "../lib/viewCache";

export interface WorkspaceModelsOptions {
  platformUrl: string;
  workspaceId: string;
  user: AuthenticatedUser | null;
}

export type ModelAction =
  | { type: "register"; manifest_path: string; artifact_path: string; labels_path: string }
  | { type: "validate"; model_id: string; report_path: string }
  | { type: "approve"; model_id: string; validation_id: string }
  | { type: "deploy"; model_id: string; expected_revision: number }
  | { type: "rollback"; expected_revision: number };

type Access = "ready" | "login_required" | "forbidden";
interface ModelsState {
  snapshot: WorkspaceModelsResponse | null;
  access: Access;
  error: string;
  stale: boolean;
  busy: boolean;
  updatedAt: number | null;
}
const initial = (access: Access): ModelsState => ({ snapshot: null, access, error: "", stale: false, busy: access === "ready", updatedAt: null });
const record = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === "string" && value.trim().length > 0 && value.length <= 8192;
const nullableText = (value: unknown) => value === null || text(value);
const integer = (value: unknown) => Number.isSafeInteger(value) && Number(value) >= 0;
const hash = (value: unknown) => typeof value === "string" && /^[a-f\d]{64}$/i.test(value);
const timestamp = (value: unknown) => typeof value === "string" &&
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const oneOf = (value: unknown, choices: string[]) => typeof value === "string" && choices.includes(value);

function isValidation(value: unknown) {
  return record(value) && text(value.id) && typeof value.passed === "boolean" && text(value.baseline_model_id) &&
    hash(value.report_sha256) && timestamp(value.created_at) && Array.isArray(value.checks) && value.checks.every(check =>
      record(check) && text(check.name) && typeof check.passed === "boolean" && typeof check.detail === "string" && check.detail.length <= 8192);
}
function isModel(value: unknown) {
  return record(value) && ["id", "model_version", "backend", "source_run_id"].every(key => text(value[key])) &&
    hash(value.artifact_sha256) && hash(value.labels_sha256) && integer(value.labels_count) && Number(value.labels_count) > 0 &&
    timestamp(value.created_at) && oneOf(value.origin, ["candidate", "baseline"]) &&
    oneOf(value.status, ["candidate", "validated", "approved", "active", "baseline"]) &&
    (value.validation === null || isValidation(value.validation)) && nullableText(value.approved_validation_id) &&
    nullableText(value.approved_by) && (value.approved_at === null || timestamp(value.approved_at));
}
function isTarget(value: unknown) {
  if (!record(value) || !["target_id", "runtime_url", "backend"].every(key => text(value[key])) ||
    !["active_model_id", "previous_model_id", "pending_job_id", "observed_model_id"].every(key => nullableText(value[key])) ||
    !integer(value.revision) || typeof value.worker_online !== "boolean") return false;
  try {
    const url = new URL(value.runtime_url as string);
    return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password;
  } catch { return false; }
}
function isJob(value: unknown) {
  return record(value) && ["id", "from_model_id", "to_model_id", "requested_by"].every(key => text(value[key])) &&
    oneOf(value.operation, ["deploy", "rollback"]) && integer(value.expected_revision) &&
    oneOf(value.status, ["queued", "loading", "succeeded", "failed"]) && timestamp(value.created_at) &&
    (value.finished_at === null || timestamp(value.finished_at)) &&
    (value.error === null || (typeof value.error === "string" && value.error.length <= 8192));
}
function parseSnapshot(body: unknown, workspaceId: string): WorkspaceModelsResponse {
  if (!record(body) || body.api_version !== "1" || body.workspace_id !== workspaceId ||
    !(body.target === null || isTarget(body.target)) || !record(body.permissions) ||
    !["register", "validate", "approve", "deploy"].every(key => typeof (body.permissions as Record<string, unknown>)[key] === "boolean") ||
    !Array.isArray(body.models) || !body.models.every(isModel) || !Array.isArray(body.deployments) || !body.deployments.every(isJob) ||
    new Set(body.models.map(model => model.id)).size !== body.models.length ||
    new Set(body.deployments.map(job => job.id)).size !== body.deployments.length) {
    throw new Error("invalid_snapshot");
  }
  return body as unknown as WorkspaceModelsResponse;
}

export function modelActionBlock(snapshot: WorkspaceModelsResponse | null, action: ModelAction): string {
  if (!snapshot) return "Chưa có dữ liệu mô hình.";
  const permission = action.type === "rollback" ? "deploy" : action.type;
  if (!snapshot.permissions[permission]) return "Bạn không có quyền thực hiện thao tác này.";
  if (action.type === "register") return [action.manifest_path, action.artifact_path, action.labels_path].every(value => value.trim())
    ? "" : "Cần đủ ba đường dẫn.";
  const target = snapshot.target;
  const model = action.type === "rollback" ? snapshot.models.find(row => row.id === target?.previous_model_id)
    : snapshot.models.find(row => row.id === action.model_id);
  if (!model) return "Không tìm thấy mô hình.";
  if (action.type === "validate") return model.origin !== "candidate" ? "Baseline không phải ứng viên." :
    action.report_path.trim() ? "" : "Chưa chọn báo cáo đánh giá.";
  if (action.type === "approve" || action.type === "deploy") {
    const validation = model.validation;
    const baseline = target?.active_model_id;
    if (model.origin !== "candidate" || !baseline || !validation?.passed || !validation.checks.length ||
      !validation.checks.every(check => check.passed) || validation.baseline_model_id !== baseline) return "Đánh giá chưa đạt hoặc không khớp baseline hiện tại.";
    if (action.type === "approve") return validation.id === action.validation_id ? "" : "Báo cáo đánh giá đã thay đổi.";
    if (model.status !== "approved" || model.approved_validation_id !== validation.id || !model.approved_by || !model.approved_at)
      return "Chưa phê duyệt báo cáo hiện tại.";
  }
  if (!target) return "Chưa cấu hình production target.";
  if (!target.worker_online) return "Runtime production ngoại tuyến.";
  if (target.observed_model_id !== target.active_model_id) return "Runtime chưa xác nhận active pointer.";
  if (target.pending_job_id || snapshot.deployments.some(job => job.status === "queued" || job.status === "loading")) return "Đang có tác vụ triển khai.";
  if (model.backend !== target.backend) return "Backend ứng viên không khớp production target.";
  if (action.type === "deploy" || action.type === "rollback") {
    if (target.revision !== action.expected_revision) return "Revision đã thay đổi. Hãy làm mới dữ liệu.";
    if (action.type === "deploy" && model.id === target.active_model_id) return "Mô hình đã hoạt động.";
    if (action.type === "rollback" && (!target.active_model_id || !target.previous_model_id || target.active_model_id === target.previous_model_id))
      return "Chưa có mô hình trước để hoàn tác.";
  }
  return "";
}

function actionRequest(action: ModelAction): { path: string; payload: object } {
  if (action.type === "register") return { path: "", payload: { manifest_path: action.manifest_path.trim(), artifact_path: action.artifact_path.trim(), labels_path: action.labels_path.trim() } };
  if (action.type === "validate") return { path: `/${encodeURIComponent(action.model_id)}/validate`, payload: { report_path: action.report_path.trim() } };
  if (action.type === "approve") return { path: `/${encodeURIComponent(action.model_id)}/approve`, payload: { validation_id: action.validation_id } };
  return { path: action.type === "deploy" ? "/deployments" : "/rollback", payload: {
    request_id: crypto.randomUUID(), expected_revision: action.expected_revision,
    ...(action.type === "deploy" ? { model_id: action.model_id } : {}),
  } };
}

export function useWorkspaceModels({ platformUrl, workspaceId, user }: WorkspaceModelsOptions) {
  const userId = user?.id, email = user?.email, role = user?.role;
  const scope = useMemo(() => ({ platformUrl, workspaceId, userId, email, role }), [platformUrl, workspaceId, userId, email, role]);
  const currentScope = useRef(scope);
  currentScope.current = scope;
  const cacheKey = useMemo(() => viewCacheKey("models", scope), [scope]);
  // A tab revisit resumes from the last good read; it stays busy (so actions stay locked) until revalidated.
  const resumed = useCallback((): ModelsState => {
    const cached = userId ? readViewCache<ModelsState>(cacheKey) : undefined;
    return cached ? { ...cached, busy: true } : initial(userId ? "ready" : "login_required");
  }, [userId, cacheKey]);
  const [stored, setStored] = useState<{ scope: typeof scope; value: ModelsState } | null>(null);
  const stateRef = useRef(stored);
  const pending = useRef<{ controller: AbortController; timer: number } | null>(null);
  const mounted = useRef(false);
  const cancel = useCallback(() => {
    const request = pending.current;
    pending.current = null;
    if (request) { window.clearTimeout(request.timer); request.controller.abort(); }
  }, []);

  const perform = useCallback(async (action?: ModelAction, recoverAccess = false): Promise<boolean> => {
    if (!mounted.current || currentScope.current !== scope || !userId || pending.current) return false;
    let previous = stateRef.current?.scope === scope ? stateRef.current.value : resumed();
    if (recoverAccess && !action && previous.access === "login_required") previous = initial("ready");
    if (previous.access !== "ready") return false;
    if (action && (!previous.snapshot || previous.stale || previous.error || previous.busy || previous.updatedAt === null ||
      Date.now() - previous.updatedAt > 15000 || modelActionBlock(previous.snapshot, action))) return false;
    const publish = (value: ModelsState) => {
      const next = { scope, value };
      stateRef.current = next;
      setStored(next);
    };
    const request = { controller: new AbortController(), timer: 0 };
    pending.current = request;
    const isCurrent = () => mounted.current && currentScope.current === scope && pending.current === request;
    publish({ ...previous, busy: true });
    let abortListener = () => {};
    try {
      const interrupted = new Promise<never>((_resolve, reject) => {
        abortListener = () => reject(new Error("cancelled"));
        request.controller.signal.addEventListener("abort", abortListener, { once: true });
        request.timer = window.setTimeout(() => { reject(new Error("timeout")); request.controller.abort(); }, 8000);
      });
      const mutation = action ? actionRequest(action) : null;
      const { body } = await Promise.race([
        workspaceRequest<unknown>(platformUrl, `/api/v1/workspace/models${mutation?.path ?? ""}`, {
          method: mutation ? "POST" : "GET", cache: "no-store",
          ...(mutation ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(mutation.payload) } : {}),
        }, request.controller.signal), interrupted,
      ]);
      if (!isCurrent()) return false;
      const snapshot = parseSnapshot(body, workspaceId);
      const fresh: ModelsState = { snapshot, access: "ready", error: "", stale: false, busy: false, updatedAt: Date.now() };
      publish(fresh);
      rememberView(cacheKey, fresh);
      return true;
    } catch (error) {
      if (!isCurrent()) return false;
      if (error instanceof WorkspaceApiError && (error.status === 401 || error.status === 403)) {
        forgetView(cacheKey);
        publish({ ...initial(error.status === 401 ? "login_required" : "forbidden"), busy: false });
      } else {
        const message = error instanceof Error && error.message === "timeout" ? "Hết thời gian chờ sau 8 giây. Hãy làm mới dữ liệu."
          : error instanceof Error && error.message === "invalid_snapshot" ? "Phản hồi mô hình không hợp lệ. Hãy làm mới dữ liệu."
          : error instanceof WorkspaceApiError && error.status === 409 ? "Trạng thái triển khai đã thay đổi. Hãy làm mới dữ liệu."
          : action ? "Không thể xác nhận thao tác. Hãy làm mới dữ liệu trước khi thử lại." : "Không thể tải mô hình. Vui lòng thử lại.";
        publish({ ...previous, busy: false, stale: !!previous.snapshot, error: message });
      }
      return false;
    } finally {
      window.clearTimeout(request.timer);
      request.controller.signal.removeEventListener("abort", abortListener);
      if (pending.current === request) pending.current = null;
    }
  }, [scope, userId, platformUrl, workspaceId, resumed, cacheKey]);

  useEffect(() => {
    mounted.current = true;
    void perform();
    const interval = window.setInterval(() => { void perform(); }, 5000);
    return () => { mounted.current = false; window.clearInterval(interval); cancel(); };
  }, [perform, cancel]);

  const visible = stored?.scope === scope && userId ? stored.value : resumed();
  // Age only counts once a read has settled: a resumed copy is revalidating, not stale.
  const stale = visible.stale || (!visible.busy && !!visible.snapshot && visible.updatedAt !== null && Date.now() - visible.updatedAt > 15000);
  const refresh = useCallback(async () => { await perform(undefined, true); }, [perform]);
  const mutate = useCallback((action: ModelAction) => perform(action), [perform]);
  return { ...visible, stale, canMutate: visible.access === "ready" && !!visible.snapshot && !visible.busy && !visible.error && !stale,
    refresh, mutate };
}
