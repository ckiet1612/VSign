import type { Icon } from "../icons";
import {
  Activity,
  BarChart3,
  Boxes,
  ChartPie,
  Database,
  LayoutDashboard,
  Plug,
  Radar,
  ScanLine,
  Settings2,
  UsersRound,
} from "../icons";

export type WorkspaceView =
  | "overview"
  | "recognize"
  | "reports"
  | "data"
  | "evaluation"
  | "monitoring"
  | "models"
  | "activity"
  | "integrations"
  | "team"
  | "settings";

export interface WorkspaceNavigationItem {
  id: WorkspaceView;
  label: string;
  icon: Icon;
}

export const PRIMARY_NAVIGATION: readonly WorkspaceNavigationItem[] = [
  { id: "overview", label: "Tổng quan", icon: LayoutDashboard },
  { id: "recognize", label: "Nhận dạng", icon: ScanLine },
  { id: "reports", label: "Báo cáo sử dụng", icon: ChartPie },
  { id: "data", label: "Dữ liệu", icon: Database },
  { id: "evaluation", label: "Đánh giá", icon: BarChart3 },
  { id: "monitoring", label: "Giám sát", icon: Radar },
  { id: "models", label: "Mô hình nhận dạng", icon: Boxes },
  { id: "activity", label: "Hoạt động", icon: Activity },
];

export const ADMIN_NAVIGATION: readonly WorkspaceNavigationItem[] = [
  { id: "integrations", label: "Tích hợp", icon: Plug },
  { id: "team", label: "Thành viên & quyền", icon: UsersRound },
  { id: "settings", label: "Cài đặt", icon: Settings2 },
];

const SYSTEM_LABELS: Record<WorkspaceView, string> = {
  overview: "Tổng quan hệ thống", recognize: "Nhận dạng", reports: "Báo cáo sử dụng", data: "Dữ liệu & thu mẫu",
  evaluation: "Đánh giá mô hình", monitoring: "Giám sát dịch vụ", models: "Mô hình & triển khai",
  activity: "Nhật ký hệ thống", integrations: "Tích hợp & API", team: "Tài khoản & quyền", settings: "Cấu hình hệ thống",
};

export function workspaceNavigation(systemAdmin = false) {
  const map = (items: readonly WorkspaceNavigationItem[]) => systemAdmin
    ? items.map(item => ({ ...item, label: SYSTEM_LABELS[item.id] })) : items;
  return { primary: map(PRIMARY_NAVIGATION), admin: map(ADMIN_NAVIGATION) };
}

const WORKSPACE_VIEWS = new Set<WorkspaceView>([
  ...PRIMARY_NAVIGATION.map(item => item.id),
  ...ADMIN_NAVIGATION.map(item => item.id),
]);

export function isWorkspaceView(value: string): value is WorkspaceView {
  return WORKSPACE_VIEWS.has(value as WorkspaceView);
}

export function readWorkspaceView(value: string | null): WorkspaceView {
  return value && isWorkspaceView(value) ? value : "recognize";
}
