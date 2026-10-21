// Vietnamese names for audit event types, shared by the activity log and the system overview.
/** Groups the activity log can filter by (the server accepts exactly these). */
export const activityGroups = [
  ["auth", "Đăng nhập & phiên"], ["permission", "Quyền truy cập"], ["model", "Mô hình"],
  ["collection", "Thu dữ liệu"], ["data", "Bộ dữ liệu"], ["deployment", "Triển khai"], ["evaluation", "Đánh giá"], ["integration", "Tích hợp"],
] as const;
const labels: Record<string, string> = {
  "auth.login": "Đăng nhập", "auth.login_succeeded": "Đăng nhập", "auth.login_success": "Đăng nhập",
  "auth.login_failed": "Đăng nhập thất bại", "auth.logout": "Đăng xuất",
  "permission.denied": "Từ chối truy cập", "model.selected": "Đổi mô hình",
  "permission.member_updated": "Cập nhật thành viên", "permission.invitation_created": "Tạo lời mời",
  "permission.invitation_revoked": "Thu hồi lời mời", "permission.invitation_accepted": "Chấp nhận lời mời",
  "model.switched": "Đổi mô hình",
  "model.selection_changed": "Đổi mô hình", "collection.started": "Bắt đầu thu dữ liệu",
  "collection.paused": "Tạm dừng thu dữ liệu", "collection.resumed": "Tiếp tục thu dữ liệu",
  "collection.stopped": "Dừng thu dữ liệu", "collection.completed": "Hoàn tất thu dữ liệu", "collection.sample_saved": "Lưu mẫu",
  "model.registered": "Thêm phiên bản đề xuất", "model.baseline_observed": "Ghi nhận phiên bản ban đầu",
  "model.validation_passed": "Đánh giá đạt", "model.validation_failed": "Đánh giá không đạt", "model.approved": "Phiên bản được phê duyệt",
  "deployment.deploy_requested": "Yêu cầu triển khai", "deployment.rollback_requested": "Yêu cầu hoàn tác",
  "deployment.succeeded": "Triển khai hoàn tất", "deployment.failed": "Triển khai thất bại",
  "data.labels_created": "Tạo phiên bản danh mục", "data.dataset_created": "Tạo bộ dữ liệu",
  "data.quota_changed": "Cập nhật hạn mức mẫu", "data.snapshot_created": "Chốt phiên bản dữ liệu",
  "evaluation.requested": "Yêu cầu đánh giá", "evaluation.started": "Bắt đầu đánh giá",
  "evaluation.completed": "Hoàn tất đánh giá", "evaluation.failed": "Đánh giá thất bại", "evaluation.cancelled": "Hủy lượt đánh giá",
  "integration.key_created": "Tạo khóa API", "integration.key_revoked": "Thu hồi khóa API",
  "integration.webhook_created": "Thêm webhook", "integration.webhook_updated": "Cập nhật webhook",
  "integration.webhook_rotated": "Đổi khóa ký webhook", "integration.webhook_test_requested": "Yêu cầu thử webhook",
  "integration.delivery_retry_requested": "Yêu cầu gửi lại webhook",
  "data.sample_saved": "Lưu mẫu thu",
  "display.enrollment_created": "Tạo mã màn hình khách", "display.enrollment_confirmed": "Xác nhận màn hình khách",
  "display.enrollment_rejected": "Từ chối màn hình khách", "display.claim_failed": "Nhập sai mã màn hình khách",
  "display.renamed": "Đổi tên màn hình khách", "display.revoked": "Huỷ màn hình khách", "display.taken_over": "Tiếp quản màn hình khách",
};

/** The Vietnamese name of an audit event: its own label, else its group's; null for a type outside every group. */
export function activityLabel(eventType: string): string | null {
  return (Object.hasOwn(labels, eventType) ? labels[eventType] : undefined)
    ?? [...activityGroups, ["display", "Màn hình khách"]].find(([group]) => eventType.startsWith(`${group}.`))?.[1] ?? null;
}

export const activityTitle = (eventType: string) => activityLabel(eventType) ?? "Hoạt động khác";
