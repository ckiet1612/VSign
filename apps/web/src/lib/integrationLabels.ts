import type { IntegrationScope } from '../../../../contracts/v1/integrations';

export const scopeLabels:Record<IntegrationScope,string>={'models:read':'Đọc mô hình','snapshots:read':'Đọc bản dữ liệu','evaluations:read':'Đọc kết quả đánh giá'};
export const eventLabels:Record<string,string>={'collection.started':'Bắt đầu thu','collection.paused':'Tạm dừng thu','collection.resumed':'Tiếp tục thu',
  'collection.stopped':'Kết thúc thu','collection.completed':'Hoàn tất thu','data.snapshot_created':'Chốt bản dữ liệu',
  'evaluation.requested':'Yêu cầu đánh giá','evaluation.started':'Bắt đầu đánh giá','evaluation.completed':'Hoàn tất đánh giá',
  'evaluation.failed':'Đánh giá thất bại','evaluation.cancelled':'Hủy đánh giá','deployment.succeeded':'Triển khai hoàn tất','deployment.failed':'Triển khai thất bại',
  'integration.test':'Kiểm tra kết nối'};
