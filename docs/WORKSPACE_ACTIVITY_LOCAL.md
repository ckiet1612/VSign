# Hoạt động: kết nối backend giai đoạn 2

## Phạm vi

- Màn hình `/?view=activity` đọc nhật ký thật qua platform API, độc lập với endpoint inference đang chọn.
- Lọc nhóm sự kiện, kết quả, thời gian; làm mới và tải thêm bằng keyset cursor.
- Đăng nhập/đăng xuất và từ chối quyền được máy chủ ghi nhận. Actor, workspace, thời gian và kết quả không do trình duyệt tự gán.
- Chuyển endpoint model chỉ ghi sau khi metadata đã được xác minh; đây không phải triển khai model lên production.
- Phiên thu có ID logic riêng: bắt đầu, tạm dừng, tiếp tục, dừng, hoàn tất và mẫu đã lưu. `capture_session_id` liên kết với ID phiên thu hiện có, không thay đổi payload dữ liệu.
- Mẫu chỉ được báo đã lưu sau ACK hợp lệ. ACK đến sau thao tác dừng vẫn thuộc phiên cũ. Camera ngắt sẽ tạm dừng, cần tiếp tục chủ động.
- Đổi tài khoản/workspace kết thúc ngữ cảnh phiên thu và bỏ mẫu chờ trên giao diện. Upload đã gửi có thể vẫn được máy chủ lưu; phản hồi cũ không được gán sang phiên mới và tiến độ được đọc lại từ máy chủ sau đó.
- Các sự kiện thao tác do trình duyệt báo cáo có nhãn nguồn riêng; không được xem là bằng chứng máy chủ đã triển khai model hoặc kiểm chứng chất lượng mẫu.
- Triển khai/hoàn tác được máy chủ ghi nhận từ vòng đời model giai đoạn 3. Evaluation và tích hợp chưa có bộ phát sự kiện thật; giao diện không tạo lịch sử giả.
- Giao diện doanh nghiệp dùng tên hoạt động dễ đọc. Mã sự kiện nằm trong phần chi tiết đóng mặc định; endpoint, đường dẫn, backend và thông tin kiểm tra kỹ thuật không được trình bày trong metadata.
- Từ giai đoạn 4, phiên thu trong workspace và mẫu lưu qua Data API được backend
  ghi audit cùng transaction; trình duyệt không gửi bản sao `collection.*`.
  Nhóm Dữ liệu lọc `data.labels_created`, `data.dataset_created`,
  `data.quota_changed`, `data.snapshot_created`. Luồng standalone/legacy vẫn dùng
  sự kiện trình duyệt với nhãn nguồn riêng. Xem `docs/WORKSPACE_DATA_LOCAL.md`.

## Đăng nhập và quyền

Local hiện mặc định dùng `Admin local` với quyền `admin` khi `APP_ENV=development` và `AUTH_REQUIRED=false`, không có form đăng nhập hay nút đăng xuất. Backend lưu identity riêng cho workspace để nhật ký và kiểm tra quyền vẫn hoạt động, không tạo mật khẩu sử dụng được hoặc phiên đăng nhập giả. Chỉ dùng trên máy local, không công khai dịch vụ.

Đây là quyền quản trị doanh nghiệp, không phải quản trị kỹ thuật model. Cả năm vai trò doanh nghiệp đều không có quyền đăng ký, kiểm định, phê duyệt, triển khai hay hoàn tác model. Quyền nội bộ `model_admin` được cấp riêng ngoài giao diện khách hàng. Xem `docs/WORKSPACE_MODELS_LOCAL.md` và báo cáo `docs/reports/2026-10-15-enterprise-admin-workspace.md`.

Nhật ký yêu cầu quyền `activity:read`. Ghi chuyển model cần `recognize:use`; ghi phiên thu cần `data:use` và collection được bật ở platform. Đặt `LOCAL_ADMIN_ENABLED=false` khi phát triển luồng tài khoản sau này; production không bật chế độ admin local.

Phần sau chỉ dành cho chế độ đăng nhập bằng tài khoản sau này. Không có mật khẩu mặc định. Dừng riêng dịch vụ platform cổng 8000 rồi chạy trong thư mục dự án bằng zsh để khởi tạo tài khoản của bạn:

```zsh
read 'BOOTSTRAP_ADMIN_EMAIL?Email quản trị: '
read -s 'BOOTSTRAP_ADMIN_PASSWORD?Mật khẩu mới (ít nhất 12 ký tự): '
printf '\n'
export BOOTSTRAP_ADMIN_EMAIL BOOTSTRAP_ADMIN_PASSWORD
APP_ENV=development AUTH_REQUIRED=false LOCAL_ADMIN_ENABLED=false AUTH_COOKIE_SECURE=false DATABASE_AUTO_CREATE=true ./scripts/run_onnx_local.sh
```

Không dừng inference 8002/8003. Không đưa mật khẩu vào source, lịch sử lệnh hoặc tài liệu. Bootstrap không đổi mật khẩu tài khoản đã tồn tại. Cấu hình cookie không secure ở trên chỉ dùng local HTTP; production cần HTTPS và cookie secure.

## API

- `GET /api/v1/workspace/audit/events`: `limit` (1..100), `cursor`, `group`, `outcome`, `from_at`, `to_at`. Thời điểm gửi dạng ISO có múi giờ. Áp dụng đồng thời bộ lọc và giới hạn workspace ở máy chủ.
- `POST /api/v1/workspace/audit/client-events`: chỉ nhận `model.switched` và các sự kiện `collection.*` trong contract; body tối đa 4096 byte. Không nhận actor/workspace/metadata tùy ý.
- UUID sự kiện là khóa chống trùng: 201 khi mới, 200 khi phát lại cùng nội dung, 409 nếu UUID đã dùng cho nội dung khác. Không xác nhận thành công khi DB lỗi.
- Metadata trả về được lọc khóa nhạy cảm; giao diện chỉ trình bày các trường đã biết.

Hàng đợi trình duyệt lưu tối đa 200 sự kiện trong bộ nhớ, ghi tuần tự, thời gian chờ 8 giây. Lỗi hiển thị riêng và có nút thử lại cùng UUID; không tự gửi lại inference hay mẫu thu. Nếu đầy, số sự kiện không được xếp hàng được cảnh báo riêng, không biến mất khi các bản ghi cũ gửi thành công. Tải lại/đóng trang hoặc đổi tài khoản sẽ bỏ hàng đợi chưa gửi; đây không phải hàng đợi bền vững hay audit chống giả mạo.

## Kiểm tra local

```sh
.venv/bin/python -m pytest tests/test_workspace_activity.py tests/test_workspace_api.py tests/test_platform_auth.py tests/test_platform_db.py tests/test_inference_api.py
npm --prefix apps/web test -- --maxWorkers=2 --testTimeout=20000
npm --prefix apps/web run lint
npm --prefix apps/web run build
VSIGN_PLAYWRIGHT_FROM="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json" node tests/e2e/workspace_activity.mjs
```

Browser smoke tự tạo platform/frontend cổng trống và DB/tài khoản tạm, dừng cả hai khi kết thúc. Nó kiểm tra login thật, phân trang thật, ACK bị mất sau commit và retry không trùng, lỗi tải/stale/recovery, bố cục 320/390/768/1365 và pixel không trắng. Metadata inference lấy từ 8002/8003 với fixture CORS cho origin tạm. Không ghi vào tập mẫu thật, không mở webcam, không train hay deploy model. Ảnh và báo cáo nằm trong thư mục tạm được in khi chạy.
