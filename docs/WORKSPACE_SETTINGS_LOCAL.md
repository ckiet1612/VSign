# Cài Đặt Workspace

## Phạm Vi

Giai đoạn 8 lưu cấu hình trong DB, không còn là trang giữ chỗ. Owner/admin có
năm tab Workspace, Retention, Thu mẫu, Runtime và Thông báo. Thành viên active
khác chỉ sửa thông báo của chính mình trong workspace hiện tại. Không cấp quyền
triển khai model, không đổi cơ chế đăng nhập hoặc bố cục nhận dạng.

Trang local: `http://127.0.0.1:5174/?view=settings`. Chế độ hiện tại là
`local_admin`, chỉ dùng loopback. Không coi đây là cấu hình public đã harden.

## API

Prefix `/api/v1/workspace/settings`:

- `GET /`: snapshot gắn workspace/user, revision chung, quyền quản lý và revision
  thông báo riêng. Nhóm quản lý là null với người không có quyền.
- `POST /update`: `request_id` UUID, `expected_revision` và ít nhất một nhóm
  `workspace`, `retention`, `collection_policy`, `runtime_defaults`.
- `POST /notifications`: `request_id`, revision thông báo và đầy đủ `preferences`.
  Không nhận user ID từ client; danh tính lấy từ phiên xác thực.
- `GET /effective`: chính sách thu mẫu có hiệu lực và mặc định runtime.
- `GET /retention/preview`: số lượng hết hạn/được bảo vệ, revision và thời điểm
  thống kê; chỉ owner/admin. Không có API xóa dữ liệu.

Quyền `settings:manage` thuộc owner/admin; `settings:preferences` thuộc các vai
trò thành viên được hỗ trợ. API key không có quyền cài đặt. POST kiểm Origin và
body tối đa 8192 byte. Membership, vai trò và phiên được đọc lại bên trong khóa
ghi SQLite; có nhánh row lock PostgreSQL nhưng chưa kiểm chứng trên PostgreSQL.

Mỗi lần lưu gửi đủ một nhóm để thay thế nhóm đó, không thay nhóm khác. Nhóm thiếu
trường trả 422, không tự điền mặc định làm mất chính sách đã lưu. Revision
cũ trả 409. ID yêu cầu gắn người thực hiện, workspace, thao tác và nội dung;
gửi lại nguyên yêu cầu chỉ xác nhận kết quả trước, không tăng revision hai lần.
Phản hồi có `request_id`, `applied_revision` và snapshot mới nhất.

UI chờ tối đa 8 giây, khóa ghi khi lỗi hoặc snapshot quá 60 giây. Bản nháp đang
sửa được giữ khi làm mới; nút nạp phiên bản mới bỏ bản nháp theo thao tác tường
minh. Khi chưa rõ kết quả lưu, giữ nguyên ID/nội dung để thử lại, kể cả sau làm
mới. Không ghi yêu cầu chưa xác nhận vào localStorage. Khi mất phiên/quyền,
xóa cấu hình cá nhân khỏi màn hình.

## Năm Nhóm

**Workspace:** tên 1..120 ký tự, chuẩn hóa Unicode và từ chối ký tự điều khiển;
múi giờ IANA hợp lệ. Tên tồn tại qua restart, cập nhật tên ở thanh điều hướng.
Múi giờ là cấu hình được lưu, chưa thay đổi cách hiển thị thời gian toàn ứng dụng.
Không chỉnh ID workspace, môi trường, URL máy chủ, khóa bí mật hoặc model pointer.

**Retention:** thời hạn mẫu nháp và nhật ký, null là không giới hạn, nếu có là
1..3650 ngày. `automatic_deletion=false` luôn cố định. Preview dùng chính sách
đã lưu, chỉ đếm; không mở/xóa tệp. Loại trừ mẫu thuộc bộ dữ liệu đã đóng, có
snapshot hoặc có phiên đang chạy/tạm dừng. Không xử lý dữ liệu legacy, artifact
model hay bằng chứng đánh giá. Không có lịch tự xóa/archival.

**Thu mẫu:** `enabled`, `require_consent` và `default_quota_per_label` 1..10000
(mặc định 100). Cờ process `COLLECTION_ENABLED=false` luôn thắng lựa chọn trong
workspace. Backend kiểm lại chính sách trong transaction bắt đầu/tiếp tục/lưu
mẫu ở `/api/v1/workspace/data`. Yêu cầu đồng ý mặc định tắt để giữ hành vi cũ;
khi bật, checkbox phải do người dùng tự chọn. Phiên lưu thời điểm đồng ý và
revision chính sách. Phiên cũ không có đồng ý phải dừng rồi bắt đầu phiên mới.
Không tự dừng phiên đang chạy khi thay đổi chính sách, nhưng backend chặn mẫu
mới/tiếp tục trái chính sách. Hạn mức chỉ áp dụng cho bộ dữ liệu mới khi request
không gửi hạn mức; không sửa hạn mức hoặc số mẫu của bộ dữ liệu hiện có.
Request tạo dataset mới phân biệt quota tường minh và quota kế thừa; receipt
trước giai đoạn 8 vẫn nhận lại đúng yêu cầu cũ mà không tính lại quota theo
chính sách mới. Không chuyển đổi hoặc sửa receipt cũ khi chỉ thử lại.
Các endpoint legacy `/collection/*` giữ hợp đồng cũ, không chịu chính sách
workspace mới; không dùng chúng để triển khai collection public.

**Runtime:** chế độ thu nhận dạng `manual`/`automatic`, mặc định `manual`.
Chỉ áp dụng một lần khi mở phiên trình duyệt mới, trước thao tác người dùng
hoặc sử dụng camera. Không thay phiên đang dùng, model, ngưỡng, hàng đợi hoặc
chế độ tự thêm từ vào câu. Thu mẫu giữ mặc định tự động hiện có.

**Thông báo:** ba lựa chọn `collection_completed`, `evaluation_finished`,
`integration_failed`, mặc định bật. Lưu riêng theo user/workspace với revision
riêng, không làm cũ revision cấu hình chung. `delivery=not_configured`; chưa
có email, push, SMTP hoặc thông báo thực được gửi từ các lựa chọn này.

## Lưu Trữ Và Nhật Ký

Migration `0010_workspace_settings` thêm `workspace_preferences`,
`user_notification_preferences`, `settings_mutations` và hai cột
`data_sessions.consented_at/policy_revision`. GET không tự tạo cấu hình trong DB.

Thay đổi cấu hình và sự kiện `settings.updated` ghi cùng transaction, có trước/
sau. `settings.notifications_updated` chỉ ghi tên trường và revision, không ghi
giá trị lựa chọn cá nhân. Người không quản lý không đọc sự kiện cài đặt của
người khác qua API Hoạt động. Không thêm sự kiện webhook mới.

## Kiểm Chứng

```sh
PYTHONPATH=services/inference:. .venv/bin/pytest -o addopts='' -q \
  tests/test_workspace_settings.py tests/test_workspace_data.py \
  tests/test_platform_auth.py tests/test_platform_db.py
npm --prefix apps/web test -- --maxWorkers=1
npm --prefix apps/web run lint
npm --prefix apps/web run build
VSIGN_PLAYWRIGHT_FROM="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json" \
  node tests/e2e/workspace_settings.mjs
VSIGN_PLAYWRIGHT_FROM="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json" \
  node tests/e2e/workspace_settings_live.mjs
```

Fixture dùng SQLite/mock, session login và cổng trống, tự dọn browser/server.
`--serve` chỉ giữ fixture cho kiểm tra thủ công; dừng bằng Ctrl+C. Browser cần
Chrome, Playwright, sharp và các dependency `.venv`. Live smoke chỉ dùng máy
local đang chạy ở chế độ local_admin, chặn mọi request ghi của trình duyệt;
`VSIGN_API`, `VSIGN_WEB`, `VSIGN_EVIDENCE_DIR` đổi URL loopback/thư mục bằng chứng.
Không dùng fixture write để kiểm tra trên DB thật.

## Migration Và Khôi Phục

Sao lưu SQLite bằng backup API, đặt quyền 0600, kiểm integrity trước khi nâng
schema. Xác nhận không có phiên thu, evaluation, webhook delivery hoặc deployment
đang chạy/chờ. Dừng platform/managed runtime và các worker liên quan, migrate
bằng `PYTHONPATH=services/inference:. .venv/bin/python -m app.migrate`, khởi động
lại với đúng môi trường cũ. Không in hoặc lưu khóa operator trong log/snapshot.
Đối chiếu metadata, model pointer, hash artifact/media, số bản ghi, foreign keys,
health và heartbeat. Giữ runtime thử nghiệm không liên quan và Vite đang chạy.

Nếu lỗi: giữ backup/log, dừng các process ghi DB rồi kiểm schema. Không hạ
revision bằng tay hoặc ghi đè DB đang mở. Chỉ phục hồi backup khi đã xác nhận
không có ghi mới cần giữ, và dùng mã tương ứng schema đó. Downgrade từ chối khi
có cấu hình, lịch sử thao tác, tùy chọn cá nhân hoặc đồng ý thu mẫu cần bảo toàn.

Chưa kiểm PostgreSQL, tải production, reboot, camera thật, email/push hoặc
nghiệm thu release độc lập. Xem báo cáo local ngày 2026-10-16 để tách kết quả
fixture khỏi kết quả dịch vụ thật.
