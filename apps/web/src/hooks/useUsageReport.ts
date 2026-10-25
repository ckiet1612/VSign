import { useCallback, useEffect, useState } from "react";
import type { UsageReportResponse } from "../../../../contracts/v1/usage";
import { forgetView, readViewCache, rememberView, viewCacheKey } from "../lib/viewCache";
import { WorkspaceApiError, workspaceRequest } from "../lib/workspaceApi";

const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const count = (value: unknown) => typeof value === "number" && Number.isFinite(value) && value >= 0;
const text = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const labelCounts = (value: unknown) => Array.isArray(value) && value.every(row => object(row) && text(row.label) && count(row.count));
const TOTALS = ["conversations", "counter_conversations", "words", "avg_words", "avg_duration_seconds", "replies",
  "voice_replies", "uncertain", "failed", "undos", "customer_undos", "unhandled_conversations"] as const;

function parse(value: unknown, workspaceId: string, days: number): UsageReportResponse {
  if (!object(value) || value.api_version !== "1" || value.workspace_id !== workspaceId || value.days !== days ||
    value.timezone !== "Asia/Ho_Chi_Minh" || !text(value.generated_at) || !text(value.start_date) ||
    !object(value.totals) || !TOTALS.every(key => count((value.totals as Record<string, unknown>)[key])) ||
    !Array.isArray(value.daily) || value.daily.length !== days ||
    !value.daily.every(row => object(row) && text(row.date) && count(row.conversations) && count(row.words) && count(row.unhandled)) ||
    !Array.isArray(value.scenarios) || !value.scenarios.every(row => object(row) && text(row.id) && text(row.label) &&
      count(row.conversations) && count(row.words)) ||
    !labelCounts(value.top_words) || !object(value.unhandled) || !count(value.unhandled.no_word) ||
    !count(value.unhandled.mostly_unclear) || !labelCounts(value.unhandled.undone_labels)) {
    throw new Error("Phản hồi báo cáo không hợp lệ.");
  }
  return value as unknown as UsageReportResponse;
}

/** The workspace usage report (F08) for the last 7, 30 or 90 days. */
export function useUsageReport(platformUrl: string, workspaceId: string, enabled: boolean, days: 7 | 30 | 90) {
  const [revision, setRevision] = useState(0);
  const key = JSON.stringify([platformUrl, workspaceId, days]);
  // Returning to the tab paints the last report for this range at once and revalidates it in place.
  const cacheKey = viewCacheKey("usage-report", [platformUrl, workspaceId, days]);
  const [state, setState] = useState<{ key: string; data: UsageReportResponse | null; error: string; loading: boolean }>(() => {
    const cached = readViewCache<UsageReportResponse>(cacheKey);
    return { key: cached ? key : "", data: cached ?? null, error: "", loading: false };
  });
  const refresh = useCallback(() => setRevision(value => value + 1), []);
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    // The previous range stays on screen while the next one loads.
    setState(current => ({ key, data: current.data ?? readViewCache<UsageReportResponse>(cacheKey) ?? null, error: "", loading: true }));
    workspaceRequest<unknown>(platformUrl, `/api/v1/workspace/usage/report?days=${days}`, { cache: "no-store" }, controller.signal)
      .then(({ body }) => {
        const data = parse(body, workspaceId, days);
        setState({ key, data, error: "", loading: false });
        rememberView(cacheKey, data);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        const denied = cause instanceof WorkspaceApiError && [401, 403].includes(cause.status);
        if (denied) forgetView(cacheKey);
        setState(current => ({ key, data: denied ? null : current.data, loading: false,
          error: denied ? "Tài khoản không có quyền xem báo cáo sử dụng."
            : cause instanceof Error && cause.message.startsWith("Phản hồi báo cáo") ? cause.message : "Chưa tải được báo cáo. Hãy thử lại." }));
      });
    return () => controller.abort();
  }, [enabled, key, platformUrl, workspaceId, days, revision, cacheKey]);
  return { ...state, stale: state.key !== key || (state.loading && state.data?.days !== days), refresh };
}
