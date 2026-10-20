import { useCallback, useEffect, useState } from "react";
import type { AuthenticatedUser } from "@workspace-contracts";
import type { DashboardResponse } from "../../../../contracts/v1/dashboard";
import { workspaceRequest, WorkspaceApiError } from "../lib/workspaceApi";
import { forgetView, readViewCache, rememberView, viewCacheKey } from "../lib/viewCache";

const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const count = (value: unknown) => Number.isSafeInteger(value) && Number(value) >= 0;
const text = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const timestamp = (value: unknown) => text(value) && Number.isFinite(Date.parse(value));
const date = (value: unknown) => text(value) && /^\d{4}-\d{2}-\d{2}$/.test(value) && timestamp(value);

function parse(value: unknown, workspaceId: string, days: number): DashboardResponse {
  const invalid = () => { throw new Error("Phản hồi thống kê không hợp lệ."); };
  if (!object(value) || value.api_version !== "1" || value.workspace_id !== workspaceId || value.days !== days ||
    value.timezone !== "UTC" || !timestamp(value.generated_at) || !date(value.start_date) ||
    !object(value.totals) || !["samples", "datasets_draft", "datasets_sealed", "models", "evaluations"].every(key => count((value.totals as Record<string, unknown>)[key])) ||
    !object(value.period) || !["samples", "evaluations", "events"].every(key => count((value.period as Record<string, unknown>)[key])) ||
    !object(value.workers) || !["deployment", "evaluation", "integration"].every(key =>
      ["online", "offline", "not_configured"].includes(String((value.workers as Record<string, unknown>)[key]))) ||
    !Array.isArray(value.daily_samples) || value.daily_samples.length !== days || !value.daily_samples.every(row => object(row) && date(row.date) && count(row.count)) ||
    !Array.isArray(value.label_progress) || !value.label_progress.every(row => object(row) && text(row.label) && count(row.count) && count(row.target)) ||
    !Array.isArray(value.recent_activity) || !value.recent_activity.every(row => object(row) && text(row.id) && text(row.event_type) &&
      ["success", "failure"].includes(String(row.outcome)) && timestamp(row.occurred_at)) ||
    !Array.isArray(value.recent_evaluations) || !value.recent_evaluations.every(row => object(row) && text(row.id) && text(row.model_version) &&
      ["queued", "running", "completed", "failed", "cancelled"].includes(String(row.status)) && count(row.progress) && Number(row.progress) <= 100 && timestamp(row.created_at))) return invalid();
  const data = value as unknown as DashboardResponse;
  if (data.daily_samples.some((row, i) => row.date !== new Date(Date.parse(data.start_date) + i * 86400000).toISOString().slice(0, 10)) ||
    data.daily_samples.reduce((sum, row) => sum + row.count, 0) !== data.period.samples ||
    new Set(data.label_progress.map(row => row.label)).size !== data.label_progress.length) return invalid();
  return data;
}

export function useSystemDashboard(platformUrl: string, workspaceId: string, user: AuthenticatedUser | null, days: 7 | 30 | 90) {
  // Identity scope: statistics never carry across users or workspaces. Within one scope the previous
  // range stays visible while another range loads, so switching 7/30/90 days does not blank the page.
  const scope = JSON.stringify([platformUrl, workspaceId, user?.id, user?.role]);
  const key = JSON.stringify([scope, days]);
  const enabled = user?.role === "system_admin";
  // Returning to the overview paints the last statistics for this range at once and revalidates them in place.
  const cacheKey = viewCacheKey("dashboard", [scope, days]);
  const [revision, setRevision] = useState(0);
  const [stored, setStored] = useState<{ scope: string; key: string; data: DashboardResponse | null; error: string; loading: boolean } | null>(null);
  const refresh = useCallback(() => setRevision(value => value + 1), []);
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    const controller = new AbortController();
    const load = async () => {
      setStored(current => ({ scope, key, data: current?.scope === scope && current.data ? current.data : readViewCache<DashboardResponse>(cacheKey) ?? null,
        error: "", loading: true }));
      let timeout = 0;
      try {
        const { body } = await Promise.race([
          workspaceRequest<unknown>(platformUrl, `/api/v1/workspace/dashboard?days=${days}`, { cache: "no-store" }, controller.signal),
          new Promise<never>((_resolve, reject) => { timeout = window.setTimeout(() => {
            controller.abort(); reject(new Error("timeout"));
          }, 8000); }),
        ]);
        const data = parse(body, workspaceId, days);
        if (active) { setStored({ scope, key, data, error: "", loading: false }); rememberView(cacheKey, data); }
      } catch (cause) {
        if (!active) return;
        const denied = cause instanceof WorkspaceApiError && [401, 403].includes(cause.status);
        if (denied) forgetView(cacheKey);
        const error = denied ? "Không có quyền xem thống kê hệ thống." : cause instanceof Error && cause.message.startsWith("Phản hồi thống kê")
          ? cause.message : "Không thể tải thống kê. Vui lòng thử lại.";
        setStored(current => ({ scope, key, data: !denied && current?.scope === scope && current.data?.days === days ? current.data : null, error, loading: false }));
      } finally { window.clearTimeout(timeout); }
    };
    void load();
    return () => { active = false; controller.abort(); };
  }, [key, scope, enabled, platformUrl, workspaceId, days, revision, cacheKey]);
  const current = stored?.scope === scope ? stored : null;
  const loading = enabled && (current?.key !== key || current.loading);
  const data = enabled ? current?.data ?? (current ? null : readViewCache<DashboardResponse>(cacheKey) ?? null) : null;
  // Only another range's numbers count as stale; this range's cached copy is simply being revalidated.
  return { data, error: enabled ? current?.key === key ? current.error : "" : "Không có quyền xem thống kê hệ thống.",
    loading, stale: loading && !!data && data.days !== days, refresh };
}
