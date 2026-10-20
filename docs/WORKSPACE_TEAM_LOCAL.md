# Thành Viên Và Quyền Workspace

## Phạm Vi

Giai đoạn 7 nối bốn tab Thành viên, Vai trò, Lời mời và Nhật ký quyền với
platform. Không thay đổi mô hình, ngưỡng nhận dạng, dữ liệu legacy hoặc cách
đăng nhập local. Cấu hình local chỉ dành loopback, không mở ra Internet.

Vai trò cố định: owner, admin, operator, reviewer, viewer. Owner quản lý admin
và các vai trò thấp hơn; admin chỉ quản lý operator/reviewer/viewer. Không tự
đổi quyền của mình, sửa owner, admin local hoặc cấp `model_admin` qua giao diện
doanh nghiệp. Bảng vai trò đọc quyền thật từ backend, không có quyền triển khai
model cho các vai trò doanh nghiệp.

## API Quản Lý

Prefix `/api/v1/workspace/team`, tất cả yêu cầu quyền `members:manage`:

- `GET /?search=&cursor=`: tối đa 50 thành viên/trang, tìm theo tên/email,
  trạng thái, revision, cờ được bảo vệ, tổng active/suspended/removed.
- `GET /roles`: ma trận năm vai trò và quyền backend.
- `POST /members/{user_uuid}/update`: `request_id`, `expected_revision`,
  `role` và/hoặc `status` (`active`, `suspended`, `removed`).
- `GET /invitations?cursor=`: tối đa 50 lời mời/trang, trạng thái và hạn dùng.
- `POST /invitations`: `request_id`, `email`, `role`, `expires_in_days`
  (1–14, mặc định 7). Tối đa 100 lời mời đang chờ/workspace.
- `POST /invitations/{uuid}/revoke`: `request_id`.
- `GET /audit?cursor=&member_id=&action=&from_at=&to_at=`: tối đa 50 sự kiện,
  thứ tự mới nhất trước. Bộ chọn thành viên có tìm kiếm/phân trang riêng,
  không bị giới hạn bởi trang đầu hoặc cursor của nhật ký.

ID yêu cầu là UUID. Gửi lại đúng ID/nội dung/người thực hiện không ghi hai lần;
thay nội dung hoặc tài nguyên trả 409. Revision cũ cũng trả 409. Sau lỗi không
rõ kết quả: làm mới, thử lại **cùng yêu cầu**. Đừng tạo ID khác để thử lại mù.
UI chờ tối đa 8 giây; lỗi hoặc dữ liệu quá 15 giây khóa thao tác ghi.

Thành viên bị gỡ phải nhận lời mời mới. Tạm khóa/khôi phục chỉ tác động membership
trong workspace, không sửa `User.is_active` hoặc xóa tài khoản dùng chung.
Tạm khóa/gỡ thu hồi các phiên của workspace đó; khôi phục không hồi sinh phiên
cũ. Đổi vai trò áp dụng ở yêu cầu kế tiếp. Login và thao tác quản lý khóa cùng
workspace, kiểm tra lại tài khoản/membership trước khi ghi phiên hoặc thay đổi.
SQLite dùng writer lock; PostgreSQL có đường mã row lock nhưng chưa chạy thử.

## Lời Mời

Backend tạo mã ngẫu nhiên 256-bit và chỉ lưu SHA256. Chỉ phản hồi tạo lần đầu
có `id` và `secret`; lần gửi lại có `secret=null`. UI kiểm ID xác nhận khớp
yêu cầu. Không lưu liên kết trong localStorage, overview hoặc nhật ký. Liên kết
bị xóa khỏi màn hình khi đổi tab, mất quyền, lỗi hoặc dữ liệu cũ, không tự hiện
lại sau khi kết nối phục hồi. Nếu mất liên kết, thu hồi lời mời rồi tạo mới.

Gửi thủ công liên kết `/invite#token=...` cho đúng người nhận. Không có SMTP hoặc
tự gửi email. Trang nhận lời mời xóa fragment trước khi gửi yêu cầu, dùng
`no-referrer`, không tự chấp nhận, không dùng cookie/local admin làm danh tính:

- `POST /api/v1/invitations/inspect`: `{token}`.
- `POST /api/v1/invitations/accept`:
  `{token,request_id,password,display_name}`.

Tài khoản mới cần tên và mật khẩu ít nhất 12 ký tự. Tài khoản đã có cần mật khẩu
hiện tại; không được đặt lại mật khẩu qua lời mời. Backend kiểm lại quyền người
mời, hạn dùng, trạng thái tài khoản và membership trong transaction. Một mã chỉ
cấp membership một lần. Lặp lại yêu cầu đã thành công cùng ID/thông tin xác thực
chỉ xác nhận lại, không tái cấp quyền sau khi thành viên bị gỡ.

Chấp nhận không đăng nhập hoặc chuyển phiên trình duyệt. Với chế độ session,
người nhận đăng nhập riêng sau đó. Bản local vẫn dùng Admin local, không tự chuyển
sang tài khoản được mời. Không tạo người dùng/lời mời thật chỉ để kiểm trang.

Hai endpoint nhận lời mời giới hạn bền vững 20 lần/IP/phút và 120 lần/workspace/
phút, đếm trước kiểm mật khẩu, dùng IP kết nối thực, không tin forwarded header.
Phản hồi 429 kèm Retry-After. Chưa có chống lạm dụng ở public edge. Body tối đa
8192 byte; lỗi validation không trả lại giá trị token/password.

## Nhật Ký Và Dữ Liệu

Sự kiện `permission.member_updated`, `permission.invitation_created`,
`permission.invitation_revoked`, `permission.invitation_accepted` ghi cùng
transaction; có người thực hiện, tài nguyên và trước/sau nhưng không có mật
khẩu/token/URL mời. Nhật ký quyền cũng hiển thị `permission.denied` trước đó.
Các sự kiện quản lý thành viên và denial liên quan bị lọc khỏi API Hoạt động
đối với người không phải owner/admin. Không thêm loại đăng ký webhook mới.

Migration `0009_workspace_team` bổ sung `memberships.status/revision`,
`team_invitations`, `team_mutations`, `team_rate_buckets`. Không nhập lại dữ liệu
legacy. Phải sao lưu DB trước migration và dừng tác vụ đang chạy. Chỉ restart
platform/managed runtime cùng các worker dùng chung DB, giữ nguyên môi trường;
không đổi model pointer hay restart runtime thử nghiệm không liên quan.

## Kiểm Chứng Và Khôi Phục

```sh
PYTHONPATH=services/inference:. .venv/bin/python -m pytest -o addopts='' -q \
  tests/test_workspace_team.py tests/test_platform_auth.py tests/test_platform_db.py
npm --prefix apps/web test -- --run --maxWorkers=1 --no-file-parallelism
npm --prefix apps/web run lint
npm --prefix apps/web run build
VSIGN_PLAYWRIGHT_FROM="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json" \
  node tests/e2e/workspace_team.mjs
```

Browser E2E ghi vào DB tạm, không ghi workspace thật. Kiểm login/session, mới/cũ,
revoke, role/status và bốn tab ở 320/390/768/1024/1440 px. Pixel/DOM không thay cho
nghiệm thu thị giác thủ công, screen reader hoặc chất lượng camera/model.

Nếu migration/startup lỗi: giữ backup, dừng các process dùng chung DB, kiểm
revision/integrity/foreign keys và log. Khôi phục bằng bản DB trước migration
chỉ sau khi xác nhận không có ghi mới cần giữ; khởi động mã tương ứng với revision
đó. Không ghi đè DB đang mở hoặc tự hạ revision. Downgrade từ chối khi có lịch sử
team/thay đổi membership, tránh bỏ mất quyền hoặc khả năng thu hồi lời mời.

Chưa xác minh PostgreSQL, SMTP, public deployment, tải production, reboot hoặc
nghiệm thu release độc lập. Lịch sử chưa có retention/archival tự động.
