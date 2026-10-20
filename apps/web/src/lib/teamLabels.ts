import type { TeamActionName, MemberStatus } from '../../../../contracts/v1/team';
import type { AuthenticatedUser } from '../../../../contracts/v1/workspace';

export const teamRoleLabels:Record<AuthenticatedUser['role'],string> = {owner:'Chủ sở hữu',admin:'Quản trị viên',operator:'Vận hành',reviewer:'Đánh giá',viewer:'Người xem',model_admin:'Kỹ thuật VSign',system_admin:'Quản trị hệ thống'};
export const memberStatusLabels:Record<MemberStatus,string> = {active:'Đang hoạt động',suspended:'Tạm khóa',removed:'Đã gỡ'};
export const teamActionLabels:Record<TeamActionName,string> = {'permission.member_updated':'Cập nhật thành viên',
  'permission.invitation_created':'Tạo lời mời','permission.invitation_revoked':'Thu hồi lời mời',
  'permission.invitation_accepted':'Chấp nhận lời mời','permission.denied':'Từ chối quyền truy cập'};
export const permissionLabels:Record<string,string> = {'workspace:read':'Xem workspace','recognize:use':'Nhận dạng',
  'data:read':'Xem dữ liệu','data:use':'Thu thập dữ liệu','data:manage':'Quản lý dữ liệu','evaluation:read':'Xem đánh giá',
  'evaluation:create':'Tạo đánh giá','evaluation:cancel':'Hủy đánh giá','monitoring:read':'Xem giám sát',
  'models:read':'Xem mô hình','activity:read':'Xem hoạt động','integrations:manage':'Quản lý tích hợp',
  'members:read':'Xem thành viên','members:manage':'Quản lý thành viên và lời mời','settings:read':'Xem cài đặt',
  'settings:manage':'Quản lý cài đặt workspace','settings:preferences':'Tùy chọn cá nhân',
  'models:register':'Đăng ký ứng viên','models:validate':'Nhập báo cáo đánh giá','models:approve':'Phê duyệt mô hình','models:deploy':'Triển khai và hoàn tác mô hình'};
