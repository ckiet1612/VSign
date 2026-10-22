import type { WorkspaceView } from "../lib/workspaceNavigation";
import type { AuthenticatedUser } from "@workspace-contracts";
import { LogOut } from "../icons";
import { SignWordmark } from "./SignWordmark";
import { workspaceRoleLabels } from "../lib/workspaceRoles";
import {
  PRIMARY_NAVIGATION,
  workspaceNavigation,
} from "../lib/workspaceNavigation";

interface AppSidebarProps {
  activeView: WorkspaceView;
  capabilities?: Partial<Record<WorkspaceView, boolean>>;
  user?: AuthenticatedUser | null;
  onLogout?: () => Promise<void>;
  onNavigate: (view: WorkspaceView) => void;
}

export function AppSidebar({
  activeView,
  capabilities = {},
  user = null,
  onLogout,
  onNavigate,
}: AppSidebarProps) {
  const systemAdmin = user?.role === "system_admin";
  const navigation = workspaceNavigation(systemAdmin);
  const renderItem = (item: (typeof PRIMARY_NAVIGATION)[number]) => {
    const enabled = capabilities[item.id] !== false;
    const Icon = item.icon;
    return (
      <li key={item.id}>
        <button
          type="button"
          className={`sidebar-nav-item ${activeView === item.id ? "active" : ""}`}
          aria-current={activeView === item.id ? "page" : undefined}
          aria-pressed={activeView === item.id}
          aria-label={item.label}
          title={item.label}
          disabled={!enabled}
          onClick={() => onNavigate(item.id)}
        >
          <Icon size={18} strokeWidth={1.9} aria-hidden="true" />
          <span>{item.label}</span>
        </button>
      </li>
    );
  };

  return (
    <aside className={`app-sidebar${systemAdmin ? " is-system-admin" : ""}`}>
      <div className="sidebar-brand">
        {/* The hand mark stands in for the "V" of the Bingo wordmark; the collapsed rail keeps only the mark.
            "Sign" is Bingo outlined to paths (36px, line-height 1) so the logo never waits on a web font. */}
        <span className="sidebar-logo" role="img" aria-label="VSign"><img className="sidebar-logo-mark" src="/brand/vsign-mark.svg" alt="" draggable={false} /><SignWordmark className="sidebar-logo-rest" /></span>
      </div>

      <nav className="sidebar-navigation" aria-label="Workspace">
        <span className="sidebar-section-label">Vận hành</span>
        <ul>{navigation.primary.map(renderItem)}</ul>

        <span className="sidebar-section-label sidebar-section-label-admin">Quản trị</span>
        <ul>{navigation.admin.map(renderItem)}</ul>
      </nav>

      {/* The signed-in user at the bottom: a colour avatar, name and role, logout. */}
      {user && (
        <div className="sidebar-account">
          <span className="sidebar-avatar" aria-hidden="true" />
          <div className="sidebar-account-copy">
            <strong title={user.display_name}>{user.display_name}</strong>
            <span title={workspaceRoleLabels[user.role]}>{workspaceRoleLabels[user.role]}</span>
          </div>
          {onLogout && <button type="button" className="sidebar-account-action" onClick={() => void onLogout()}
            aria-label="Đăng xuất" title="Đăng xuất">
            <LogOut size={16} aria-hidden="true" />
          </button>}
        </div>
      )}
    </aside>
  );
}
