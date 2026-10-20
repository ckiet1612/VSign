# Đánh giá workspace (giai đoạn 5)

## Sử dụng

Mở `http://127.0.0.1:5174/?view=evaluation`. Admin doanh nghiệp chọn model
đã đăng ký và snapshot (bản dữ liệu đã chốt). Production tại thời điểm tạo là
model đối chiếu, không phải model đang chọn tạm ở màn hình nhận dạng.

- Owner/admin: xem, tạo, hủy; reviewer: chỉ xem.
- Operator/viewer/model_admin: không có API đánh giá doanh nghiệp.
- Quyền Dữ liệu không đổi. Không thêm form đăng nhập; local admin vẫn mặc định.
- Không có quyền doanh nghiệp để đăng ký/duyệt/deploy model.
- Chỉ một lượt chờ/đang chạy mỗi workspace. Tối đa 1000 video/lượt.

API v1: `GET/POST /api/v1/workspace/evaluations`,
`POST /api/v1/workspace/evaluations/{id}/cancel`.
Body tạo chỉ có `request_id`, `model_id`, `snapshot_id`; không nhận workspace,
đường dẫn model, metric, threshold hay cờ tự xác nhận dữ liệu độc lập.
Mất phản hồi: làm mới, thử lại đúng request ID; không tự tạo yêu cầu mới.

## Worker Riêng

Migration `0007_workspace_evaluations` cần chạy trước trên bản sao lưu DB:

```sh
PYTHONPATH=services/inference:. .venv/bin/python -m app.migrate
bash scripts/run_evaluation_worker_local.sh onnx
COREML_COMPUTE_UNITS=CPU_AND_GPU bash scripts/run_evaluation_worker_local.sh coreml
```

Giữ `DATABASE_URL`, `WORKSPACE_ID`, `COLLECTION_DIR`, `MODEL_REGISTRY_ROOTS`,
`MODEL_EVALUATION_ROOTS` giống platform. Interpreter cần hỗ trợ backend tương ứng.
Các thư mục phải là đường dẫn thật, không qua symlink (trên macOS thư mục tạm
`/var/...` cần chuyển thành `/private/var/...` trước khi cấu hình).
Worker không mở cổng mạng, không gọi endpoint inference production, không ghi
active pointer. Mỗi lượt chạy trong subprocess riêng. Dừng worker bằng SIGTERM;
subprocess bị hủy nếu yêu cầu đã hủy hoặc vượt 30 phút. Worker mất heartbeat
45 giây: lượt chạy cũ được đánh dấu lỗi khi worker hoạt động trở lại hoặc khi
có yêu cầu mới; không tự chạy lại. Lượt queued còn lưu trong DB.

## Cách Tính

Hai model đọc đúng các video snapshot đã kiểm hash, cùng 16 frame đều theo thời
gian, RGB 224px/JPEG90 và xử lý backend hiện có. Mỗi model có một lượt làm nóng
không tính thời gian. Video tối đa 32 MB, 600 frame, 1920x1080/frame. Model và
snapshot được kiểm lại trước khi công bố kết quả. Không dùng backend mock.

Độ chính xác tính trên cả mẫu ký hiệu lẫn mẫu âm; từ chối trên mẫu dương là sai.
F1 tính trung bình trên tất cả nhãn dương của model, không tính `Không ký hiệu`.
Mẫu âm bị nhận thành bất kỳ ký hiệu nào là false accept. Thiếu support cho một
nhãn: F1 tổng hợp không có; thiếu mẫu âm: tỷ lệ nhận nhầm không có.
P95 chỉ đo `predict`, không gồm load model, đọc video, thu camera hay mạng.
Kết quả từ worker có thể chịu ảnh hưởng tải máy; không phải SLA production.

## Bằng Chứng Độc Lập

Snapshot bất biến **không tự chứng minh** độc lập với tập huấn luyện. Mặc định
lượt đánh giá vẫn chạy nhưng chỉ tham khảo và không đủ điều kiện triển khai.
Nhân sự kỹ thuật cung cấp tệp operator-owned trong `MODEL_EVALUATION_ROOTS`:
`provenance-<snapshot_sha256>.json`. Ví dụ cấu trúc:

```json
{
  "schema_version": "1",
  "workspace_id": "local",
  "snapshot_sha256": "<64 lowercase hex>",
  "complete_training_lineage": true,
  "evaluation_groups": {"<evaluation video sha256>": "heldout-signer-session"},
  "models": {
    "<model artifact sha256>": {
      "source_run_id": "<exact registry source_run_id>",
      "training_video_sha256": ["<training video sha256>"],
      "training_group_ids": ["training-signer-session"]
    }
  }
}
```

Phải liệt kê đầy đủ lineage huấn luyện cho **cả hai** artifact, mọi video đánh
giá và nhóm người/phiên thu tương ứng. Hash video và group không được trùng
training của model nào. Group phải định danh người/phiên đúng thực tế, không
đặt tên mới chỉ để vượt kiểm tra. Đây là bằng chứng do nhân sự kỹ thuật tin cậy
cung cấp; hệ thống không thể tự xác minh lời khai hay nguồn training bên ngoài.
Không dùng tệp fixture để xác nhận chất lượng thật. Thư mục này không được
web client hay tiến trình thu dữ liệu ghi vào.

Hash nội dung tệp được đóng băng lúc tạo lượt; thêm/sửa tệp sau đó không nâng
cấp lượt cũ, cần tạo lượt mới. Sửa/xóa bằng chứng sau khi đạt làm approve/deploy
bị chặn. Endpoint nhập `report_path` cũ chỉ tham khảo, không thể mở chốt deploy.

## Chốt Triển Khai

Policy `workspace-heldout-v2`: đúng identity/hash/baseline/config, dữ liệu dương
heldout và âm độc lập, đủ từng nhãn; F1 giảm không quá 0,02; false accept <=5%
và tăng <=1 điểm phần trăm; recall mỗi nhãn giảm <=0,10; P95 <=2000 ms và
<=120% baseline trên cùng worker. Đây là gate chống hồi quy, không phải bảo đảm
độ chính xác tuyệt đối hay chứng minh hiệu quả với người ký mới.

Kết quả đạt vẫn cần phê duyệt riêng và deploy rõ ràng bởi vai trò nội bộ.
Approve, API deploy và deployment worker kiểm lại kết quả do worker tạo,
SHA256 báo cáo, file snapshot, provenance và baseline hiện tại. Fine-tune chỉ
tạo candidate, không liên quan tới thay production trong giai đoạn này.

## Kiểm Tra Tách Biệt

```sh
PYTHONPATH=services/inference:. .venv/bin/python -m pytest -o addopts='' -q tests/test_workspace_evaluations.py
npm --prefix apps/web test -- --no-file-parallelism
VSIGN_PLAYWRIGHT_FROM="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json" node tests/e2e/workspace_evaluations.mjs
```

Browser fixture tự tạo DB, ONNX nhỏ và video trắng/đen ở thư mục tạm; dừng toàn
bộ dịch vụ fixture khi xong. Nó kiểm luồng tích hợp, không đo chất lượng ký
hiệu, webcam thật hoặc production. Test deployment mechanics có seed evidence
tổng hợp trong `tests/evaluation_fixtures.py`, được tách khỏi phép tính thật.
