import type { AuthenticatedUser } from "@workspace-contracts";

export const workspaceRoleLabels: Record<AuthenticatedUser["role"], string> = {
  owner: "Chủ doanh nghiệp", admin: "Quản trị doanh nghiệp", operator: "Nhân viên vận hành",
  reviewer: "Người đánh giá", viewer: "Người xem", model_admin: "Kỹ thuật VSign", system_admin: "Quản trị hệ thống",
};
