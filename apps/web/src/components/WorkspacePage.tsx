import {
  Activity,
  ArrowUpRight,
  BarChart3,
  Boxes,
  CircleCheck,
  CircleOff,
  Database,
  Plug,
  ScanLine,
} from "../icons";
import type { ReactNode } from "react";
import { workspaceNavigation, type WorkspaceView } from "../lib/workspaceNavigation";
import type { WorkspaceAuditEvent, WorkspaceMemberResponse } from "@workspace-contracts";
import type { RuntimeSnapshot } from "../hooks/useRuntimeStatus";
import { RuntimeRefreshButton, WorkspaceRuntime } from "./WorkspaceRuntime";
import { PageHero } from "./PageChrome";
import { SkeletonRegion, TextBone } from "./Skeleton";
import { workspaceRoleLabels } from "../lib/workspaceRoles";

interface WorkspacePageProps {
  view: Exclude<WorkspaceView, "recognize" | "data">;
  connection: "connected" | "connecting" | "disconnected";
  modelVersion: string;
  backend: string;
  protocolVersion: string;
  labelCount: number;
  labelsVerified: boolean;
  collectionEnabled: boolean;
  collectionTarget: number;
  modelSelector?: ReactNode;
  members?: WorkspaceMemberResponse[] | null;
  auditEvents?: WorkspaceAuditEvent[] | null;
  capabilities?: Partial<Record<WorkspaceView, boolean>>;
  onNavigate?: (view: WorkspaceView) => void;
  runtime?: RuntimeSnapshot;
  onRefreshRuntime?: () => void;
  systemAdmin?: boolean;
}

const connectionText = {
  connected: "AI đang hoạt động",
  connecting: "Đang kết nối AI",
  disconnected: "AI ngoại tuyến",
} as const;

function PageHeader({ title, children }: { title: string; children?: ReactNode }) {
  return <PageHero title={title}>{children}</PageHero>;
}

const QUICK_ACTIONS: ReadonlyArray<{ view: WorkspaceView; icon: typeof Activity; title: string }> = [
  { view: "recognize", icon: ScanLine, title: "Nhận dạng ký hiệu" },
  { view: "data", icon: Database, title: "Thu dữ liệu" },
  { view: "models", icon: Boxes, title: "Mô hình nhận dạng" },
];

// Audit/member list while it loads: heading and rows in the list surface's own grid.
function ListSkeleton({ label }: { label: string }) {
  return <SkeletonRegion label={label} className="workspace-list-surface">
    <div className="workspace-list-heading"><TextBone w={64} size={12} line={16} /><TextBone w={64} size={12} line={16} /></div>
    {[0, 1, 2, 3, 4].map(index => <div key={index} className="workspace-list-row"><div><TextBone w={`${30 + (index * 13) % 25}%`} /><TextBone w="40%" size={12} line={16} /></div>
      <TextBone w={120} /></div>)}
  </SkeletonRegion>;
}

function EmptyWorkspacePage({
  icon: Icon,
  title,
  description,
}: {
  icon: typeof Activity;
  title: string;
  description: string;
}) {
  return (
    <section className="workspace-empty-state" aria-live="polite">
      <Icon size={22} aria-hidden="true" />
      <h2>{title}</h2>
      <p>{description}</p>
    </section>
  );
}

export function WorkspacePage({
  view,
  connection,
  modelVersion,
  labelCount,
  labelsVerified,
  collectionEnabled,
  collectionTarget,
  members = null,
  auditEvents = null,
  capabilities = {},
  onNavigate,
  runtime,
  onRefreshRuntime,
  systemAdmin = false,
}: WorkspacePageProps) {
  const navigation = workspaceNavigation(systemAdmin);
  const quickActions = systemAdmin ? [...navigation.primary, ...navigation.admin].filter(item => item.id !== "overview")
    .map(item => ({ view: item.id, icon: item.icon, title: item.label })) : QUICK_ACTIONS;
  if (view === "overview") {
    return (
      <div className="workspace-page">
        <PageHeader title={systemAdmin ? "Tổng quan hệ thống" : "Tổng quan"}>
          {runtime && onRefreshRuntime && <RuntimeRefreshButton checking={runtime.checking} onRefresh={onRefreshRuntime} />}
        </PageHeader>
        {runtime ? <WorkspaceRuntime runtime={runtime} systemAdmin={systemAdmin} /> : <section className="workspace-overview" aria-label="Trạng thái dịch vụ">
          <div className="workspace-metric workspace-metric-status">
            <span className="workspace-metric-label">Dịch vụ nhận dạng</span>
            <strong><i aria-hidden="true" />{connectionText[connection]}</strong>
          </div>
          <div className="workspace-metric">
            <span className="workspace-metric-label">Phiên bản nhận dạng</span>
            <strong>{modelVersion || "Chưa có thông tin phiên bản"}</strong>
          </div>
          <div className="workspace-metric">
            <span className="workspace-metric-label">Ký hiệu hỗ trợ</span>
            <strong>{labelCount} ký hiệu</strong>
            <span className="workspace-metric-detail">{labelsVerified ? "Đã xác minh" : "Cần xác minh"}</span>
          </div>
          <div className="workspace-metric">
            <span className="workspace-metric-label">Thu dữ liệu</span>
            <strong>{collectionEnabled ? "Đã bật" : "Chưa bật"}</strong>
            <span className="workspace-metric-detail">{collectionEnabled ? `${collectionTarget} mẫu / tay` : "Không ghi dữ liệu"}</span>
          </div>
        </section>}
        {onNavigate && (
          <section className="workspace-quick-actions" aria-labelledby="quick-actions-title">
            <h2 id="quick-actions-title">Bắt đầu nhanh</h2>
            <div className="workspace-quick-grid">
              {quickActions.map(({ view: target, icon: Icon, title }) => {
                const enabled = capabilities[target] !== false && (target !== "data" || collectionEnabled);
                return (
                  <button key={target} type="button" className="workspace-quick-card" disabled={!enabled}
                    onClick={() => onNavigate(target)}>
                    <span className="workspace-quick-icon" aria-hidden="true"><Icon size={18} /></span>
                    <strong className="workspace-quick-title">{title}</strong>
                    <ArrowUpRight className="workspace-quick-arrow" size={16} aria-hidden="true" />
                  </button>
                );
              })}
            </div>
          </section>
        )}
      </div>
    );
  }

  if (view === "models") {
    return (
      <div className="workspace-page">
        <PageHeader title="Mô hình nhận dạng" />
        <section className="workspace-model-surface" aria-label="Phiên bản nhận dạng">
          <div className="workspace-surface-heading">
            <div>
              <span className="workspace-page-eyebrow">Phiên bản đang dùng</span>
              <h2>{modelVersion || "Chưa có thông tin phiên bản"}</h2>
            </div>
            {connection === "connected" ? <CircleCheck className="workspace-status-icon is-good" size={20} aria-label="Đang hoạt động" /> : <CircleOff className="workspace-status-icon" size={20} aria-label={connectionText[connection]} />}
          </div>
          <dl className="workspace-detail-list">
            <div><dt>Ký hiệu hỗ trợ</dt><dd>{labelCount} ký hiệu</dd></div>
            <div><dt>Xác minh</dt><dd>{labelsVerified ? "Đã xác minh" : "Chưa xác minh"}</dd></div>
          </dl>
        </section>
      </div>
    );
  }

  if (view === "evaluation") {
    return <div className="workspace-page"><PageHeader title="Đánh giá" /><EmptyWorkspacePage icon={BarChart3} title="Chưa có báo cáo đánh giá" description="Chưa có kết quả đánh giá cho workspace này." /></div>;
  }

  if (view === "activity") {
    return (
      <div className="workspace-page">
        <PageHeader title="Hoạt động" />
        {auditEvents === null ? <ListSkeleton label="Đang tải hoạt động" /> : auditEvents.length === 0 ?
          <EmptyWorkspacePage icon={Activity} title="Chưa có hoạt động được ghi nhận" description="Các lần đăng nhập và thao tác platform sẽ xuất hiện tại đây" /> :
          <section className="workspace-list-surface" aria-label="Audit log">
            <div className="workspace-list-heading"><span>Sự kiện</span><span>Thời gian</span></div>
            {auditEvents.map(event => <div className="workspace-list-row" key={event.event_id}>
              <div><strong>{event.event_type}</strong><span>{event.actor_type === "user" ? "Người dùng" : "Hệ thống"} · {event.outcome === "success" ? "Thành công" : "Thất bại"}</span></div>
              <time dateTime={event.occurred_at}>{new Date(event.occurred_at).toLocaleString("vi-VN")}</time>
            </div>)}
          </section>}
      </div>
    );
  }

  if (view === "monitoring") {
    return <div className="workspace-page"><PageHeader title={systemAdmin ? "Giám sát dịch vụ" : "Giám sát"}>
      {onRefreshRuntime && <RuntimeRefreshButton checking={!!runtime?.checking} onRefresh={onRefreshRuntime} />}
    </PageHeader><WorkspaceRuntime runtime={runtime} monitoring systemAdmin={systemAdmin} /></div>;
  }

  if (view === "integrations") {
    return <div className="workspace-page"><PageHeader title="Tích hợp" /><EmptyWorkspacePage icon={Plug} title="Chưa có tích hợp" description="Chưa có kết nối được cấu hình cho doanh nghiệp." /></div>;
  }

  if (view === "team") {
    return (
      <div className="workspace-page">
        <PageHeader title="Thành viên & quyền" />
        {members === null ? <ListSkeleton label="Đang tải thành viên" /> :
          <section className="workspace-list-surface" aria-label="Danh sách thành viên">
            <div className="workspace-list-heading"><span>Thành viên</span><span>Vai trò</span></div>
            {members.map(member => <div className="workspace-list-row" key={member.id}>
              <div><strong>{member.display_name}</strong><span>{member.email} · {member.active ? "Đang hoạt động" : "Đã vô hiệu hóa"}</span></div>
              <span className="workspace-role">{workspaceRoleLabels[member.role]}</span>
            </div>)}
          </section>}
      </div>
    );
  }

  return <div className="workspace-page"><PageHeader title="Cài đặt" /><EmptyWorkspacePage icon={Database} title="Cài đặt doanh nghiệp" description="Chưa có cấu hình riêng cho workspace này." /></div>;
}
