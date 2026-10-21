import type { WorkspaceView } from "../lib/workspaceNavigation";
import type { AuthenticatedUser } from "@workspace-contracts";
import { LogOut } from "../icons";
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
        <span className="sidebar-logo" role="img" aria-label="VSign"><img className="sidebar-logo-mark" src="/brand/vsign-mark.svg" alt="" draggable={false} /><svg className="sidebar-logo-rest" viewBox="0 -851.5 1794 1000" aria-hidden="true" focusable="false"><path fill="currentColor" d="M549 -189C549 -408 110 -357 110 -496C110 -560 197 -608 286 -608C356 -608 428 -578 459 -504L540 -537C494 -648 389 -695 286 -695C153 -695 23 -617 23 -496C23 -266 461 -322 461 -186C461 -124 367 -75 272 -75C200 -75 127 -104 96 -178L15 -145C56 -46 155 14 279 14C439 14 549 -89 549 -189Z M611 -450V0H699V-450Z M1248 -1H1160C1160 25 1133 131 1008 131H938V219H1008C1166 219 1248 94 1248 -1ZM1248 -228C1248 -302 1214 -377 1139 -426L1183 -468C1142 -511 1162 -490 1122 -532C1073 -485 1098 -508 1049 -462C1035 -464 1021 -465 1007 -465C878 -465 768 -359 768 -225C768 -93 875 14 1008 14C1155 14 1248 -106 1248 -228ZM1008 -74C924 -74 856 -142 856 -225C856 -309 924 -377 1008 -377C1092 -377 1160 -309 1160 -225C1160 -142 1092 -74 1008 -74Z M1764 0V-246C1764 -367 1665 -465 1544 -465C1423 -465 1325 -367 1325 -246V0H1413V-246C1413 -319 1472 -377 1544 -377C1617 -377 1676 -319 1676 -246V0Z" /></svg></span>
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
