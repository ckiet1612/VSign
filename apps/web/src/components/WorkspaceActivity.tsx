import type { AuthenticatedUser } from "@workspace-contracts";
import type { WorkspaceAuditEvent } from "@workspace-contracts";
import { useState } from "react";
import { RefreshCw, Server } from "../icons";
import { useWorkspaceActivity, type WorkspaceActivityFilters } from "../hooks/useWorkspaceActivity";
import { LoginGate } from "./LoginGate";
import { CardHead, PageHero } from "./PageChrome";
import { activityGroups as groups, activityTitle } from "../lib/activityLabels";
import "../styles/activity.css";
import { Bone, FieldBone, PillBone, SkeletonRegion, TextBone } from "./Skeleton";

interface WorkspaceActivityProps {
  platformUrl: string;
  user: AuthenticatedUser | null;
  canRead: boolean;
  onLogin: (email: string, password: string) => Promise<void>;
  loginBusy?: boolean;
  sessionLoading?: boolean;
  authMode?: "session" | "local_admin";
  workspaceName?: string;
  workspaceId?: string;
}

const actorLabels = { user: "Người dùng", system: "Hệ thống", service: "Dịch vụ" };
const metadataLabels: Record<string, string> = {
  model_id: "ID mô hình", model_version: "Phiên bản mô hình", previous_model_version: "Phiên bản trước",
  new_model_version: "Phiên bản mới", previous_model_id: "Mô hình trước", new_model_id: "Mô hình mới",
  previous_model: "Mô hình trước", new_model: "Mô hình mới", model_option: "Lựa chọn mô hình",
  previous_model_option: "Lựa chọn trước", version: "Phiên bản",
  client_id: "ID trình duyệt", session_id: "ID phiên", capture_session_id: "ID phiên thu",
  sample_id: "ID mẫu", saved_samples: "Số mẫu đã lưu", sample_count: "Số mẫu", label: "Nhãn",
  collection_id: "ID bộ dữ liệu", reason: "Lý do", user_agent: "Trình duyệt", mode: "Chế độ",
  from_view: "Màn hình trước", to_view: "Màn hình mới", view: "Màn hình", action: "Thao tác",
  role: "Vai trò", previous_role: "Vai trò trước", new_role: "Vai trò mới",
  operation: "Thao tác",
  dataset_version_id: "Phiên bản dữ liệu", snapshot_id: "Bản dữ liệu đã chốt", target: "Hạn mức mẫu",
  dataset_version: "Phiên bản dữ liệu",
};
const containers: Record<string, string> = {
  previous: "Trước", new: "Mới", before: "Trước", after: "Sau", changes: "Thay đổi",
  client: "Trình duyệt", session: "Phiên", model: "Mô hình",
};

function metadataDetails(metadata: Record<string, unknown>, prefix = "", depth = 0): Array<[string, string]> {
  if (depth > 4) return [];
  return Object.entries(metadata).flatMap(([key, value]): Array<[string, string]> => {
    // Only known leaf fields and containers are rendered, never arbitrary JSON.
    const container = Object.hasOwn(containers, key) ? containers[key] : undefined;
    if (container && value && typeof value === "object" && !Array.isArray(value)) {
      return metadataDetails(value as Record<string, unknown>, `${prefix}${containers[key]} / `, depth + 1);
    }
    const label = Object.hasOwn(metadataLabels, key) ? metadataLabels[key] : typeof value !== "object" ? container : undefined;
    if (!label || value === null || !["string", "number", "boolean"].includes(typeof value)) return [];
    return [[`${prefix}${label}`, String(value)]];
  });
}

function ActivityRows({ count }: { count: number }) {
  return <>{Array.from({ length: count }, (_, index) => <div key={index} className="activity-row" aria-hidden="true">
    <div className="activity-row-heading"><div><TextBone w={140 + (index * 37) % 90} /></div><PillBone w={92} /></div>
    <div className="activity-row-context"><TextBone w={128} size={12} line={16} /><TextBone w={112} size={12} line={16} /></div>
    <Bone w={72} h={24} r={999} className="skeleton-summary" />
  </div>)}</>;
}

function ActivityRowsBone({ count, label }: { count: number; label: string }) {
  return <SkeletonRegion label={label}><ActivityRows count={count} /></SkeletonRegion>;
}

function AuditRow({ event }: { event: WorkspaceAuditEvent }) {
  const source = event.metadata.source;
  const sourceLabel = source === "browser_report" ? "Trình duyệt báo cáo"
    : source === undefined || source === "server" || source === "server_action" ? "Máy chủ ghi nhận" : "Nguồn chưa xác định";
  const title = activityTitle(event.event_type);
  return (
    <article className="activity-row" aria-label={`${title} · ${event.event_id}`}>
      <div className="activity-row-heading">
        <div><h3>{title}</h3></div>
        <span className={`activity-outcome page-status ${event.outcome === "success" ? "is-success" : "is-failure"}`}>
          {event.outcome === "success" ? "Thành công" : "Thất bại"}
        </span>
      </div>
      <div className="activity-row-context">
        <time dateTime={event.occurred_at}>{new Date(event.occurred_at).toLocaleString("vi-VN")}</time>
        <span>{sourceLabel}</span>
      </div>
      <details>
        <summary>Chi tiết</summary>
        <dl className="activity-details">
          <div><dt>Mã sự kiện</dt><dd>{event.event_type}</dd></div>
          <div><dt>ID sự kiện</dt><dd>{event.event_id}</dd></div>
          <div><dt>Tác nhân</dt><dd>{event.actor_id ?? actorLabels[event.actor_type]}</dd></div>
          {event.actor_id && <div><dt>Loại tác nhân</dt><dd>{actorLabels[event.actor_type]}</dd></div>}
          {event.resource_type !== null && <div><dt>Loại tài nguyên</dt><dd>{event.resource_type}</dd></div>}
          {event.resource_id !== null && <div><dt>ID tài nguyên</dt><dd>{event.resource_id}</dd></div>}
          {metadataDetails(event.metadata).map(([label, value], index) => <div key={`${label}-${index}`}><dt>{label}</dt><dd>{value}</dd></div>)}
        </dl>
      </details>
    </article>
  );
}

function localToIso(value: string) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toISOString() : value;
}

export function WorkspaceActivity({ platformUrl, user, canRead, onLogin, loginBusy = false,
  sessionLoading = false, authMode = "session", workspaceName = "VSign workspace", workspaceId = "local" }: WorkspaceActivityProps) {
  const [group, setGroup] = useState<WorkspaceActivityFilters["group"]>("");
  const [outcome, setOutcome] = useState<WorkspaceActivityFilters["outcome"]>("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const reader = useWorkspaceActivity({ platformUrl, user, canRead, workspaceId,
    filters: { group, outcome, from_at: localToIso(from), to_at: localToIso(to) } });
  const busy = reader.loading || reader.refreshing || reader.loadingMore;
  // First read of a list (or a filter that emptied it): rows-shaped placeholders instead of a status line.
  const firstLoad = busy && !reader.loadingMore && reader.events.length === 0;
  const invalidRange = !!from && !!to && new Date(from).getTime() > new Date(to).getTime();
  return (
    <div className="workspace-page activity-page">
      <PageHero title={user?.role === "system_admin" ? "Nhật ký hệ thống" : "Hoạt động"}>
        {!sessionLoading && reader.access !== "login_required" && reader.access !== "forbidden" &&
          <button type="button" className="activity-refresh page-icon-button" title="Làm mới hoạt động" aria-label="Làm mới hoạt động"
            disabled={busy || invalidRange} data-busy={busy || undefined} onClick={() => void reader.refresh()}>
            <RefreshCw size={18} aria-hidden="true" />
          </button>}
      </PageHero>
      {sessionLoading ? <SkeletonRegion label="Đang tải workspace...">
        <div className="activity-filters page-card">{[0, 1, 2, 3].map(index => <FieldBone key={index} className="skeleton-filter" label={index < 2 ? 92 : 104} />)}</div>
        <div className="activity-log page-card"><ActivityRows count={8} /></div>
      </SkeletonRegion> : reader.access === "login_required" ? authMode === "local_admin"
        ? <p role="alert">Chưa xác nhận được quyền admin local. Hãy làm mới workspace.</p> : (
        <LoginGate embedded workspaceName={workspaceName} busy={loginBusy} onLogin={async (email, password) => {
          await onLogin(email, password);
          await reader.refresh();
        }} />
      ) : reader.access === "forbidden" ? (
        <p role="status" className="activity-status">Bạn không có quyền xem nhật ký hoạt động.</p>
      ) : <>
        <section className="activity-filters page-card" aria-label="Bộ lọc hoạt động">
          <label>Loại hoạt động<select value={group} onChange={event => setGroup(event.target.value as WorkspaceActivityFilters["group"])}>
            <option value="">Tất cả hoạt động</option>{groups.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select></label>
          <label>Kết quả<select value={outcome} onChange={event => setOutcome(event.target.value as WorkspaceActivityFilters["outcome"])}>
            <option value="">Tất cả kết quả</option><option value="success">Thành công</option><option value="failure">Thất bại</option>
          </select></label>
          <label>Từ thời điểm<input type="datetime-local" value={from} aria-invalid={invalidRange} onChange={event => setFrom(event.target.value)} /></label>
          <label>Đến thời điểm<input type="datetime-local" value={to} aria-invalid={invalidRange} onChange={event => setTo(event.target.value)} /></label>
        </section>
        <section className="activity-log page-card" aria-label="Nhật ký hoạt động" aria-busy={busy} data-previewing={reader.previewing || undefined}>
          {reader.error && <div className="activity-error" role="alert">
            <p>{reader.error}{reader.stale ? " Đang hiển thị dữ liệu cũ; chưa cập nhật." : ""}</p>
            {!invalidRange && <button type="button" className="secondary-button" disabled={busy} onClick={() => void (reader.failedOperation === "more" ? reader.loadMore() : reader.refresh())}>Thử lại</button>}
          </div>}
          {firstLoad ? <ActivityRowsBone count={8} label="Đang tải hoạt động..." />
            : busy && !reader.loadingMore && <p className="sr-only" role="status">{reader.refreshing ? "Đang làm mới..." : "Đang tải hoạt động..."}</p>}
          {!busy && !reader.error && reader.loaded && reader.events.length === 0 && <p className="activity-status" role="status">Không có hoạt động phù hợp.</p>}
          {reader.events.map(event => <AuditRow key={event.event_id} event={event} />)}
          {reader.loadingMore && <ActivityRowsBone count={2} label="Đang tải thêm..." />}
          {reader.hasMore && <div className="activity-pagination"><button type="button" className="secondary-button" disabled={busy} onClick={() => void reader.loadMore()}>Tải thêm</button></div>}
        </section>
        <section className="activity-sources page-card" aria-label="Nguồn nhật ký">
          <CardHead icon={Server} title="Nguồn nhật ký" />
          <dl><div><dt>Triển khai</dt><dd>Máy chủ ghi nhận yêu cầu và kết quả deploy/rollback</dd></div>
            <div><dt>Đánh giá</dt><dd>Máy chủ ghi nhận yêu cầu, hủy và kết quả đánh giá</dd></div>
            <div><dt>Tích hợp</dt><dd>Chưa có nguồn nhật ký</dd></div></dl>
        </section>
      </>}
    </div>
  );
}
