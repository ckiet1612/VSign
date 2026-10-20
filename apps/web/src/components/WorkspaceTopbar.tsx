import { ChevronRight, PanelLeft } from "../icons";
import {
  workspaceNavigation,
  type WorkspaceView,
} from "../lib/workspaceNavigation";

interface WorkspaceTopbarProps {
  view: WorkspaceView;
  workspaceName?: string;
  connection: "connected" | "connecting" | "disconnected";
  sidebarCollapsed?: boolean;
  onToggleSidebar?: () => void;
  systemAdmin?: boolean;
}

const connectionText = {
  connected: "AI đang hoạt động",
  connecting: "Đang kết nối AI",
  disconnected: "AI ngoại tuyến",
} as const;

export function WorkspaceTopbar({
  view,
  workspaceName = "VSign workspace",
  connection,
  sidebarCollapsed = false,
  onToggleSidebar,
  systemAdmin = false,
}: WorkspaceTopbarProps) {
  const navigation = workspaceNavigation(systemAdmin);
  const current = [...navigation.primary, ...navigation.admin].find(item => item.id === view);
  return (
    <div className="workspace-topbar">
      {onToggleSidebar && (
        <button type="button" className="sidebar-toggle" onClick={onToggleSidebar}
          aria-label={sidebarCollapsed ? "Mở rộng sidebar" : "Thu gọn sidebar"}
          aria-pressed={sidebarCollapsed} title={sidebarCollapsed ? "Mở rộng sidebar" : "Thu gọn sidebar"}>
          <PanelLeft size={20} aria-hidden="true" />
        </button>
      )}
      <nav className="workspace-breadcrumb" aria-label="Vị trí hiện tại">
        <ol>
          <li>{systemAdmin ? "VSign System" : workspaceName}</li>
          <li aria-hidden="true"><ChevronRight size={14} /></li>
          <li aria-current="page">{current?.label ?? "Nhận dạng"}</li>
        </ol>
      </nav>
      <span className={`topbar-status topbar-status-${connection}`}>
        <i aria-hidden="true" />{connectionText[connection]}
      </span>
    </div>
  );
}
