import type { AuthenticatedUser, WorkspaceAuditEvent } from "@workspace-contracts";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { workspaceRequest, WorkspaceApiError } from "../lib/workspaceApi";
import { forgetView, readViewCache, rememberView, viewCacheKey } from "../lib/viewCache";

export interface WorkspaceActivityFilters {
  group?: "" | "auth" | "permission" | "model" | "collection" | "data" | "deployment" | "evaluation" | "integration";
  outcome?: "" | "success" | "failure";
  from_at?: string;
  to_at?: string;
}

export interface WorkspaceActivityOptions {
  platformUrl: string;
  user: AuthenticatedUser | null;
  canRead: boolean;
  workspaceId?: string;
  filters?: WorkspaceActivityFilters;
}

type Access = "ready" | "login_required" | "forbidden";
type Operation = "refresh" | "more";
interface ActivityState {
  events: WorkspaceAuditEvent[];
  access: Access;
  loading: boolean;
  loadingMore: boolean;
  refreshing: boolean;
  loaded: boolean;
  error: string;
  stale: boolean;
  hasMore: boolean;
  nextCursor: string | null;
  cursors: string[];
  failedOperation: Operation | null;
}

function emptyState(access: Access, error = ""): ActivityState {
  return { events: [], access, loading: access === "ready" && !error,
    loadingMore: false, refreshing: false, loaded: false, error, stale: false,
    hasMore: false, nextCursor: null, cursors: [], failedOperation: null };
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
const nonempty = (value: unknown): value is string => typeof value === "string" && value.trim().length > 0;
const nullableString = (value: unknown) => value === null || typeof value === "string";
const timestamp = (value: unknown): value is string => typeof value === "string" &&
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));

function isEvent(value: unknown, workspaceId: string): value is WorkspaceAuditEvent {
  return record(value) && nonempty(value.event_id) && value.workspace_id === workspaceId &&
    nonempty(value.event_type) && (value.actor_type === "system" || value.actor_type === "user" || value.actor_type === "service") &&
    nullableString(value.actor_id) && timestamp(value.occurred_at) && nullableString(value.resource_type) &&
    nullableString(value.resource_id) && (value.outcome === "success" || value.outcome === "failure") && record(value.metadata);
}

function parsePage(body: unknown, workspaceId: string, cursors: string[]) {
  if (!record(body) || body.api_version !== "1" || body.workspace_id !== workspaceId || body.source !== "store" ||
      !Array.isArray(body.events) || !body.events.every(event => isEvent(event, workspaceId)) ||
      typeof body.has_more !== "boolean" ||
      (body.has_more ? !nonempty(body.next_cursor) || body.events.length === 0 || cursors.includes(body.next_cursor) : body.next_cursor !== null)) {
    throw new Error("Phản hồi nhật ký không hợp lệ.");
  }
  return { events: body.events as WorkspaceAuditEvent[], hasMore: body.has_more, nextCursor: body.next_cursor as string | null };
}

export function useWorkspaceActivity({ platformUrl, user, canRead, workspaceId = "local", filters = {} }: WorkspaceActivityOptions) {
  const { group = "", outcome = "", from_at = "", to_at = "" } = filters;
  const userId = user?.id;
  const userEmail = user?.email;
  const userRole = user?.role;
  // A new identity even on A -> B -> A keeps a previous request from re-entering the view.
  const scope = useMemo(() => ({ platformUrl, workspaceId, userId, userEmail, userRole, canRead, group, outcome, from_at, to_at }),
    [platformUrl, workspaceId, userId, userEmail, userRole, canRead, group, outcome, from_at, to_at]);
  const currentScope = useRef(scope);
  currentScope.current = scope;
  const access: Access = !userId ? "login_required" : !canRead ? "forbidden" : "ready";
  const filterError = (from_at && !timestamp(from_at)) || (to_at && !timestamp(to_at))
    ? "Thời điểm không hợp lệ."
    : from_at && to_at && Date.parse(from_at) > Date.parse(to_at)
      ? "Thời điểm bắt đầu phải trước hoặc bằng thời điểm kết thúc." : "";
  const cacheKey = useMemo(() => viewCacheKey("activity", scope), [scope]);
  // A tab revisit resumes from the last good read and refreshes it in place instead of showing the row skeleton.
  const resumed = useCallback((): ActivityState => {
    const cached = access === "ready" && !filterError ? readViewCache<ActivityState>(cacheKey) : undefined;
    return cached ? { ...cached, refreshing: true } : emptyState(access, filterError);
  }, [access, filterError, cacheKey]);
  const [stored, setStored] = useState<{ scope: typeof scope; value: ActivityState } | null>(null);
  // Last list shown, kept on screen (refreshing) while another filter loads.
  const identity = JSON.stringify([platformUrl, workspaceId, userId, userEmail, userRole, canRead]);
  const shown = useRef<{ identity: string; value: ActivityState } | null>(null);
  const stateRef = useRef(stored);
  const pending = useRef<{ controller: AbortController; timer: number } | null>(null);

  const cancel = useCallback(() => {
    const request = pending.current;
    pending.current = null;
    if (request) {
      window.clearTimeout(request.timer);
      request.controller.abort();
    }
  }, []);

  const read = useCallback(async (operation: Operation) => {
    if (currentScope.current !== scope || access !== "ready" || filterError) return;
    const previous = stateRef.current?.scope === scope ? stateRef.current.value : resumed();
    if (operation === "more" && (pending.current || !previous.hasMore || previous.access !== "ready")) return;
    cancel();
    const publish = (value: ActivityState) => {
      const next = { scope, value };
      stateRef.current = next;
      setStored(next);
    };
    const controller = new AbortController();
    const request = { controller, timer: 0 };
    pending.current = request;
    const isCurrent = () => currentScope.current === scope && pending.current === request;
    publish({ ...previous, access: "ready", error: "", failedOperation: null,
      loading: !previous.loaded, loadingMore: operation === "more", refreshing: operation === "refresh" && previous.loaded });
    const query = new URLSearchParams({ limit: "50" });
    for (const [key, value] of Object.entries({ group, outcome, from_at, to_at })) if (value) query.set(key, value);
    if (operation === "more" && previous.nextCursor) query.set("cursor", previous.nextCursor);
    let abortListener: () => void = () => undefined;
    try {
      const interrupted = new Promise<never>((_resolve, reject) => {
        abortListener = () => reject(new Error("Đã hủy tải nhật ký."));
        controller.signal.addEventListener("abort", abortListener, { once: true });
        request.timer = window.setTimeout(() => {
          reject(new Error("Không nhận được nhật ký sau 8 giây. Vui lòng thử lại."));
          controller.abort();
        }, 8000);
      });
      const { body } = await Promise.race([
        workspaceRequest<unknown>(platformUrl, `/api/v1/workspace/audit/events?${query}`, { method: "GET" }, controller.signal),
        interrupted,
      ]);
      if (!isCurrent()) return;
      const page = parsePage(body, workspaceId, operation === "more" ? previous.cursors : []);
      const rows = operation === "more" ? [...previous.events, ...page.events] : page.events;
      const seen = new Set<string>();
      const events = rows.filter(event => !seen.has(event.event_id) && !!seen.add(event.event_id));
      const fresh: ActivityState = { ...emptyState("ready"), ...page, events, loading: false, loaded: true,
        cursors: [...(operation === "more" ? previous.cursors : []), ...(page.nextCursor ? [page.nextCursor] : [])] };
      publish(fresh);
      rememberView(cacheKey, fresh);
    } catch (error) {
      if (!isCurrent()) return;
      if (error instanceof WorkspaceApiError && (error.status === 401 || error.status === 403)) {
        forgetView(cacheKey);
        shown.current = null;
        publish(emptyState(error.status === 401 ? "login_required" : "forbidden"));
      } else {
        publish({ ...previous, loading: false, refreshing: false, loadingMore: false,
          error: error instanceof WorkspaceApiError ? "Không thể tải nhật ký. Vui lòng thử lại."
            : error instanceof Error ? error.message : "Không thể tải nhật ký. Vui lòng thử lại.",
          stale: previous.loaded, failedOperation: operation });
      }
    } finally {
      window.clearTimeout(request.timer);
      controller.signal.removeEventListener("abort", abortListener);
      if (pending.current === request) pending.current = null;
    }
  }, [scope, access, filterError, cancel, group, outcome, from_at, to_at, platformUrl, workspaceId, resumed, cacheKey]);

  useEffect(() => {
    void read("refresh");
    return cancel;
  }, [read, cancel]);

  const refresh = useCallback(() => read("refresh"), [read]);
  const loadMore = useCallback(() => read("more"), [read]);
  // Mask old state during render, before effects have had a chance to clear it.
  const own = access === "ready" && !filterError && stored?.scope === scope ? stored.value : resumed();
  // A new filter keeps the previous rows (as a refresh) until its own first page lands or fails, instead of the row skeleton.
  const previewing = own.loading && !own.loaded && !own.error && own.access === "ready" && shown.current?.identity === identity;
  const visible: ActivityState = previewing
    ? { ...shown.current!.value, loading: false, refreshing: true, loadingMore: false, hasMore: false, error: "", stale: false, failedOperation: null }
    : own;
  if (own.loaded && own.access === "ready") shown.current = { identity, value: own };
  return { ...visible, previewing, refresh, loadMore };
}
