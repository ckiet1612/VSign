# Workspace Data Phase 4

Giao diện quản trị doanh nghiệp có bốn mục: Thu mẫu, Phiên thu, Bộ dữ liệu,
Danh mục ký hiệu. Dữ liệu được đọc từ platform, độc lập với endpoint nhận dạng.
Local tiếp tục dùng Admin local, không thêm form đăng nhập hoặc quyền kỹ thuật model.

## Quyền Và Phạm Vi

| Vai trò | Đọc dữ liệu | Thu mẫu | Danh mục, bộ dữ liệu, hạn mức, snapshot |
| --- | --- | --- | --- |
| owner / admin | Có | Có | Có |
| operator | Có | Có, quản lý phiên của mình | Không |
| reviewer / viewer | Có | Không | Không |
| model_admin nội bộ | Không | Không | Không |

Backend lấy workspace từ identity đã xác thực; không nhận workspace tùy ý từ
body. Capability chỉ điều khiển hiển thị, không thay thế kiểm tra quyền máy chủ.
Khi `COLLECTION_ENABLED=false`, vẫn đọc/quản lý dữ liệu và đóng phiên được,
nhưng không bắt đầu, tiếp tục hoặc lưu mẫu mới.

## Quy Trình

1. Tạo phiên bản danh mục với UUID ổn định cho từng ký hiệu. Chỉnh danh mục tạo
   phiên bản mới dựa trên bản gốc; bộ dữ liệu cũ không đổi theo.
2. Tạo bộ dữ liệu nháp gắn một phiên bản danh mục. Hạn mức mặc định là 100 mẫu
   mỗi ký hiệu, cộng cả hai tay và tất cả phiên; có thể đặt từ 1 đến 10.000.
3. Chọn bộ dữ liệu nháp, bắt đầu phiên rồi thu mẫu theo luồng camera hiện có.
   Phiên bắt đầu/tiếp tục chỉ bật thu sau khi máy chủ xác nhận.
4. Tạm dừng hoặc kết thúc phiên. Lệnh đóng chờ mẫu đang lưu hoàn tất. Tải lại
   trang vẫn thấy lịch sử; người thu có thể khôi phục phiên đang mở của mình.
5. Chốt phiên bản sau khi có ít nhất một mẫu và mọi phiên đã kết thúc. Snapshot
   không yêu cầu đủ hạn mức tất cả ký hiệu; quality gate thuộc giai đoạn đánh giá.

Chốt tạo bản sao MP4/JSON riêng và manifest ràng buộc workspace, phiên bản bộ
dữ liệu, phiên bản danh mục, mẫu và SHA256. Tệp được kiểm chứng, đồng bộ đĩa và
công bố nguyên tử trước khi commit bản ghi chốt. Dataset đã chốt không thể thu
thêm, đổi hạn mức hoặc sửa danh mục. Không có API xóa/sửa snapshot.

## API

Base: `/api/v1/workspace/data`. GET overview và các mutation trả overview mới;
upload trả collection ACK với số đếm máy chủ.

| Method | Path | Body |
| --- | --- | --- |
| GET | base | Không |
| POST | `/labels` | `request_id`, `name`, `parent_id?`, `entries: [{id,name,kind}]` |
| POST | `/datasets` | `request_id`, `name`, `label_version_id`, `quota_per_label?` |
| POST | `/datasets/{id}/quota` | `quota_per_label` |
| POST | `/sessions` | `request_id`, `dataset_version_id` |
| POST | `/sessions/{id}/state` | `state: running/paused/stopped/completed` |
| POST | `/sessions/{id}/samples` | CollectionSampleRequest, `sample_key` UUID bắt buộc |
| POST | `/datasets/{id}/snapshot` | `request_id` |
| GET | `/snapshots/{id}/manifest` | Không; kiểm tra manifest và mọi tệp trước khi trả |

Các ID yêu cầu tạo mới là UUID. Cùng ID/cùng nội dung không tạo bản ghi hay audit
trùng; dùng lại ID cho nội dung khác bị từ chối. Quota và session state là thao
tác đặt trạng thái. POST kiểm tra quyền/origin và giới hạn body trước khi xử lý.
Mẫu dùng `MAX_MESSAGE_BYTES`; các mutation dữ liệu khác tối đa 64 KiB.

## Lưu Trữ Và Khôi Phục

Migration: `0006_workspace_data`. Năm bảng `data_label_versions`, `data_versions`,
`data_sessions`, `data_samples`, `data_snapshots` có khóa ngoại theo workspace.

```text
COLLECTION_DIR/workspaces/<workspace>/datasets/<dataset_version>/...
COLLECTION_DIR/workspaces/<workspace>/snapshots/<snapshot>/manifest.json
```

Chỉ mẫu đã commit trong DB được tính. SQLite khóa writer bằng `BEGIN IMMEDIATE`;
PostgreSQL khóa hàng workspace để tuần tự hóa quota, lưu mẫu, đóng phiên và chốt.
Kiểm tra đồng thời trong đợt này chạy bằng SQLite nhiều app instance; chưa kiểm
chứng PostgreSQL thực tế hoặc tải lớn. Backup vận hành phải bao gồm cả DB và media.

Mất phản hồi lưu mẫu không tự retry: giao diện tạm dừng, giữ clip trong bộ nhớ và
cho thử lưu lại cùng khóa. Mẫu đã commit có thể nhận lại ACK sau khi phiên đóng;
mẫu chưa commit không được ghi vào phiên đã đóng. Retry khi paused tạm mở server
session, lưu cùng clip rồi tạm dừng lại, không bật thu tự động. Reload làm mất clip
chưa xác nhận trong RAM, không tự phục hồi nó từ tệp thừa.

Tệp công bố nhưng DB commit thất bại không được tính hoặc đưa vào snapshot. Retry
mẫu chưa có DB sẽ tạo lại cặp tệp thuộc yêu cầu đó từ payload; không tin tệp thừa.
Retry snapshot chỉ dùng lại vùng công bố trùng manifest và toàn bộ mã băm. Các
đường dẫn quản lý từ chối symlink. Sửa tệp bằng công cụ ngoài ứng dụng không bị
khóa ở cấp hệ điều hành nhưng sẽ bị phát hiện khi đọc manifest hoặc chốt.

UI không nhận phản hồi khác workspace, xóa trạng thái khi đổi identity/quyền,
chặn mutation mới khi lần đọc xác nhận quá 15 giây và giữ yêu cầu lỗi để retry
tường minh. Đọc nền tạm ngưng trong lúc upload; upload giới hạn chờ 60 giây.
Đổi quyền cũng hủy ngữ cảnh thu và bỏ qua phản hồi upload cũ. Một lần đọc mới xác
nhận phiên chưa từng được tạo sẽ bỏ ID tạm để bắt đầu lại; yêu cầu chưa rõ kết quả
vẫn giữ ID ban đầu cho nút thử lại, kể cả sau khi làm mới.

## Ranh Giới

- Không nhập tự động các mẫu legacy dưới `batches/personal-100`; màn hình mới
  bắt đầu trống cho đến khi doanh nghiệp tạo danh mục và bộ dữ liệu.
- Các endpoint cũ `/collection/*` và công cụ Dev/Test vẫn là API phát triển local,
  không được bổ sung RBAC bởi giai đoạn này. Không công khai dịch vụ passwordless.
- Không khởi chạy training, evaluation, deploy hoặc đổi active model pointer.
  Fine-tune vẫn chỉ tạo candidate. Kết nối training với snapshot là công việc riêng.
- Không thêm pipeline retention, export, xóa dữ liệu hoặc nhập dữ liệu legacy.

## Kiểm Chứng

```sh
PYTHONPATH=services/inference:. .venv/bin/python -m pytest -o addopts='' -q tests/test_workspace_data.py
npm --prefix apps/web test -- --no-file-parallelism
npm --prefix apps/web run lint
npm --prefix apps/web run build
VSIGN_PLAYWRIGHT_FROM="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json" node tests/e2e/workspace_data.mjs
```

E2E dùng DB/media tạm, mock inference và camera giả lập. Đây là bằng chứng tích
hợp và lưu trữ, không chứng minh chất lượng nhận dạng camera thật hay production.
