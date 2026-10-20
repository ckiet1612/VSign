import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { AuthenticatedUser } from "@workspace-contracts";
import type { WorkspaceDataResponse } from "../../../../contracts/v1/data";
import { workspaceRequest, WorkspaceApiError } from "../lib/workspaceApi";

const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === "string" && value.length > 0 && value.length <= 256;
const count = (value: unknown) => Number.isSafeInteger(value) && Number(value) >= 0;
const date = (value: unknown) => typeof value === "string" && Number.isFinite(Date.parse(value));
const uuid = (value: unknown): value is string => typeof value === "string" && /^[a-f\d]{8}(?:-[a-f\d]{4}){3}-[a-f\d]{12}$/i.test(value);
function parse(body: unknown, workspaceId: string): WorkspaceDataResponse {
  const invalid = () => { throw new Error("invalid_data"); };
  if (!object(body) || body.api_version !== "1" || body.workspace_id !== workspaceId || typeof body.collection_enabled !== "boolean" ||
    !Array.isArray(body.default_labels) || !body.default_labels.every(text) || !object(body.permissions) ||
    typeof body.permissions.manage !== "boolean" || typeof body.permissions.collect !== "boolean") return invalid();
  for (const key of ["labels", "datasets", "sessions", "snapshots"]) {
    const items = body[key];
    if (!Array.isArray(items) || !items.every(item => object(item) && uuid(item.id) && date(item.created_at)) ||
      new Set(items.map(item => item.id)).size !== items.length) return invalid();
  }
  const data = body as unknown as WorkspaceDataResponse;
  if (data.collection_policy !== undefined && (!object(data.collection_policy) ||
    data.collection_policy.enabled !== data.collection_enabled || typeof data.collection_policy.require_consent !== 'boolean' ||
    typeof data.collection_policy.process_enabled !== 'boolean' || data.collection_policy.enabled && !data.collection_policy.process_enabled ||
    !count(data.collection_policy.revision) || !count(data.collection_policy.default_quota_per_label) ||
    data.collection_policy.default_quota_per_label < 1 || data.collection_policy.default_quota_per_label > 10000)) return invalid();
  if (!data.labels.every(row => text(row.name) && (row.parent_id === null || uuid(row.parent_id)) && Array.isArray(row.entries) && row.entries.length > 0 &&
    row.entries.every(entry => object(entry) && uuid(entry.id) && text(entry.name) && ["sign", "negative"].includes(entry.kind)) &&
    new Set(row.entries.map(entry => entry.id)).size === row.entries.length && new Set(row.entries.map(entry => entry.name)).size === row.entries.length) ||
    !data.datasets.every(row => text(row.name) && data.labels.some(labels => labels.id === row.label_version_id) && count(row.sample_count) &&
      count(row.quota_per_label) && row.quota_per_label >= 1 && row.quota_per_label <= 10000 && ["draft", "sealed"].includes(row.status) && object(row.counts) &&
      Object.values(row.counts).every(value => object(value) && count(value.right) && count(value.left)) &&
      Object.values(row.counts).reduce((sum, value) => sum + value.right + value.left, 0) === row.sample_count) ||
    !data.sessions.every(row => data.datasets.some(dataset => dataset.id === row.dataset_version_id) && text(row.created_by) && date(row.updated_at) &&
      count(row.sample_count) && ["running", "paused", "stopped", "completed"].includes(row.state)) ||
    !data.snapshots.every(row => data.datasets.some(dataset => dataset.id === row.dataset_version_id && dataset.status === "sealed") &&
      data.labels.some(labels => labels.id === row.label_version_id) && count(row.sample_count) && row.sample_count > 0 &&
      typeof row.sha256 === "string" && /^[a-f\d]{64}$/i.test(row.sha256))) return invalid();
  return data;
}

type PendingAction = { path: string; payload: unknown };
interface State { snapshot: WorkspaceDataResponse | null; busy: boolean; error: string; stale: boolean; failed: PendingAction | null; updatedAt: number }
const empty = (): State => ({ snapshot: null, busy: false, error: "", stale: false, failed: null, updatedAt: 0 });

export function useWorkspaceData({ platformUrl, workspaceId, user, enabled }: {
  platformUrl: string; workspaceId: string; user: AuthenticatedUser | null; enabled: boolean;
}) {
  const scope = useMemo(() => ({ platformUrl, workspaceId, userId: user?.id, role: user?.role, enabled }),
    [platformUrl, workspaceId, user?.id, user?.role, enabled]);
  const current = useRef(scope); current.current = scope;
  const [stored, setStored] = useState<{ scope: typeof scope; value: State } | null>(null);
  const latest = useRef(stored);
  const pending = useRef<{ controller: AbortController; action?: PendingAction } | null>(null);
  const readsHeld = useRef<typeof scope | null>(null);
  const mounted = useRef(false);
  const perform = useCallback(async (action?: PendingAction, retryAction = false): Promise<WorkspaceDataResponse | null> => {
    if (!mounted.current || current.current !== scope || !scope.userId || !enabled) return null;
    if (!action && readsHeld.current === scope) return null;
    if (pending.current?.action || (!action && pending.current)) return null;
    const previous = latest.current?.scope === scope ? latest.current.value : empty();
    const publish = (value: State) => { latest.current = { scope, value }; setStored({ scope, value }); };
    if (action && !retryAction) {
      if (previous.failed) return null;
      if (!previous.snapshot || previous.stale || Date.now() - previous.updatedAt > 15000) {
        publish({ ...previous, stale: !!previous.snapshot, error: "Dữ liệu đã cũ. Hãy làm mới trước khi tiếp tục." });
        return null;
      }
    }
    pending.current?.controller.abort();
    const operation = { controller: new AbortController(), action };
    pending.current = operation;
    const isCurrent = () => mounted.current && current.current === scope && pending.current === operation;
    publish({ ...previous, busy: true, error: "" });
    let timer = 0;
    try {
      const { body } = await Promise.race([workspaceRequest<unknown>(platformUrl, `/api/v1/workspace/data${action?.path ?? ""}`, {
        method: action ? "POST" : "GET", cache: "no-store",
        ...(action ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(action.payload) } : {}),
      }, operation.controller.signal), new Promise<never>((_resolve, reject) => {
        timer = window.setTimeout(() => { operation.controller.abort(); reject(new Error("timeout")); }, action ? 60000 : 8000);
      })]);
      if (!isCurrent()) return null;
      const snapshot = parse(body, workspaceId);
      publish({ snapshot, busy: false, error: "", stale: false, failed: action ? null : previous.failed, updatedAt: Date.now() });
      return snapshot;
    } catch (error) {
      if (!isCurrent()) return null;
      const denied = error instanceof WorkspaceApiError && [401, 403].includes(error.status);
      const message = denied ? "Không có quyền truy cập dữ liệu này." : error instanceof Error && error.message === "invalid_data"
        ? "Phản hồi dữ liệu không hợp lệ. Hãy làm mới workspace." : error instanceof WorkspaceApiError && error.status === 409
        ? "Dữ liệu hoặc phiên thu đã thay đổi. Hãy làm mới trước khi tiếp tục." : error instanceof WorkspaceApiError && error.status === 422
        ? "Nội dung chưa hợp lệ. Kiểm tra tên, danh mục và hạn mức." : action
        ? "Chưa xác nhận được thao tác. Hãy thử lại cùng yêu cầu." : "Chưa tải được dữ liệu. Hãy thử lại.";
      const retryable = !(error instanceof WorkspaceApiError && [401, 403, 404, 409, 422].includes(error.status));
      publish({ ...previous, snapshot: denied ? null : previous.snapshot, busy: false, stale: !!previous.snapshot,
        error: message, failed: action && retryable ? action : action ? null : previous.failed });
      return null;
    } finally {
      window.clearTimeout(timer);
      if (pending.current === operation) pending.current = null;
    }
  }, [scope, platformUrl, workspaceId, enabled]);
  useEffect(() => {
    mounted.current = true;
    void perform();
    const timer = window.setInterval(() => { if (document.visibilityState === "visible") void perform(); }, 10000);
    return () => { mounted.current = false; window.clearInterval(timer); pending.current?.controller.abort(); pending.current = null; };
  }, [perform]);
  const visible = stored?.scope === scope && user && enabled ? stored.value : empty();
  const mutate = useCallback((path: string, payload: unknown) => perform({ path, payload }), [perform]);
  const refresh = useCallback(() => perform(), [perform]);
  const retry = useCallback(() => visible.failed ? perform(visible.failed, true) : perform(), [perform, visible.failed]);
  const holdReads = useCallback((held: boolean) => {
    if (current.current !== scope) return;
    readsHeld.current = held ? scope : null;
    if (held && pending.current && !pending.current.action) {
      pending.current.controller.abort(); pending.current = null;
      if (latest.current?.scope === scope) {
        const value = { ...latest.current.value, busy: false };
        latest.current = { scope, value }; setStored({ scope, value });
      }
    }
  }, [scope]);
  return { ...visible, ready: !!visible.snapshot && !visible.busy && !visible.stale && !visible.error && !visible.failed,
    mutate, refresh, retry, holdReads };
}
