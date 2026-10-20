# Tích hợp workspace

## Phạm Vi Và Quyền

Owner/admin quản lý khóa API, webhook, sự kiện đăng ký và nhật ký của workspace.
Giữ `local_admin` cho môi trường local, không thêm đăng nhập. Đây không phải
cấu hình public an toàn: legacy inference/collection/dev endpoints vẫn theo
hợp đồng cũ và chỉ dành loopback. Không mở dịch vụ local ra Internet.

API keys chỉ đọc, không dùng trên API quản trị hoặc thừa hưởng cookie/admin.
Không đọc video, đường dẫn artifact, manifest nội bộ hoặc danh sách thành viên.
Các quyền: `models:read`, `snapshots:read`, `evaluations:read`. Mỗi khóa có tên,
ngày hết hạn tối đa365 ngày, hạn mức1–60 lượt/phút và thu hồi. Backend chỉ lưu
SHA256 của khóa256-bit ngẫu nhiên và prefix nhận diện.

## API

Management dưới `/api/v1/workspace/integrations`:

- `GET /`: latest50 keys (active first), all webhooks (max10), latest50 deliveries,
  permission, encryption readiness, dispatcher heartbeat and ceilings.
- `POST /keys`: request_id, name, scopes, expires_at timezone-aware,
  requests_per_minute. Tối đa20 khóa hoạt động/workspace.
- `POST /keys/{id}/revoke`: idempotent, không cần request_id.
- `POST /webhooks`: request_id, name, url, events. Endpoint không sửa tại chỗ;
  đổi địa chỉ bằng webhook mới, tắt webhook cũ.
- `POST /webhooks/{id}/configure`: request_id và enabled hoặc events (hoặc cả hai).
  Trường bị bỏ qua giữ nguyên; sửa sự kiện không thay trạng thái bật/tắt và ngược lại.
- `POST /webhooks/{id}/rotate`: request_id.
- `POST /webhooks/{id}/test`: request_id, chỉ xếp hàng, không đồng nghĩa đã giao.
- `POST /deliveries/{id}/retry`: request_id, chỉ lượt failed và webhook đang bật.
- `GET /logs?kind=api|webhook&cursor=...`:50 dòng/trang; next_cursor hoặc null.

Management POST trả overview mới; tạo khóa/tạo webhook/rotate bổ sung `secret`
và `id`. Secret chỉ trả một lần. Gửi lại cùng request_id/nội dung trả secret=null;
đổi nội dung hoặc tài nguyên với ID cũ trả409. Mất ACK: refresh, thử lại đúng
request_id; nếu khóa đã tạo mà không còn secret thì thu hồi/tạo mới hoặc rotate.
Không lưu secret trong localStorage. Màn hình mới không có dữ liệu mẫu.

Machine GET endpoints, `Authorization: Bearer <API_KEY>` bắt buộc:

```text
/api/v1/integrations/models?cursor=<last UUID>
/api/v1/integrations/snapshots?cursor=<last UUID>
/api/v1/integrations/evaluations?cursor=<last UUID>
```

Trả api_version, workspace_id, items (max50, UUID ascending), next_cursor.
Workspace lấy từ cấu hình và key đã lưu, không tin workspace do client gửi.
Không có bearer thì401 kể cả khi có cookie hoặc bật local admin. Bearer trên
API platform khác bị403. Khóa thu hồi/hết hạn401; sai scope403; vượt hạn429
kèm Retry-After. Số đo thời gian nhật ký là thời gian backend, không phải mạng
client hoặc camera. Không ghi request/response body, khóa hoặc exception text.

## Khóa Mã Hóa Của Máy Chủ

Cài dependency mới trong các môi trường phục vụ platform (đã cài trên local):

```bash
.venv/bin/python -m pip install 'cryptography>=44,<47'
.venv-coreml/bin/python -m pip install 'cryptography>=44,<47'
```

Operator cấp khóa Fernet qua `INTEGRATION_ENCRYPTION_KEY`, hoặc file qua
`INTEGRATION_ENCRYPTION_KEY_FILE`. Biến inline có ưu tiên. File thiếu, symlink,
không phải regular file, quá128 byte, sai mã hóa hoặc khóa sai làm webhook
unavailable, không làm mất các chức năng platform khác. Mất file/đổi khóa máy
chủ không tương đương rotate khóa ký: ciphertext cũ sẽ không giải mã được.
Phải sao lưu DB và operator key riêng, giữ quyền đọc hạn chế.

Đường dẫn local đã dùng: `$HOME/.config/vsign/integration-encryption.key`,
quyền0600, ngoài Git/database. `run_onnx_local.sh` và managed CoreML launcher
tự dùng file này nếu có, trừ khi đã chỉ định file riêng. Giá trị không xuất
trong báo cáo/log. Worker mặc định đọc cùng file:

```bash
bash scripts/run_integration_worker_local.sh
```

Worker phải dùng cùng DATABASE_URL và WORKSPACE_ID với platform. Worker
độc lập với inference; không đổi active model pointer. Evaluation
workers cũng cần chạy bản mã mới để fanout sự kiện đánh giá. Không chạy nhiều
dispatcher là bắt buộc; hàng chờ có claim fencing và giới hạn chung nếu có
nhiều dispatcher. Không tự tạo API key, webhook hoặc gửi request test khi mở UI.

## Sự Kiện Và Giao Nhận

Chỉ allowlist collection session (started/paused/resumed/stopped/completed),
data.snapshot_created, evaluation (requested/started/completed/failed/cancelled),
deployment (succeeded/failed). Subscription áp dụng cho sự kiện mới, không replay
audit lịch sử. Browser-reported events và integration logs không được fanout.
Audit insertion và delivery cùng commit hoặc cùng rollback trong DB.

Envelope JSON v1 chỉ chứa event_id, workspace_id, event_type, occurred_at,
outcome, resource_type và resource_id. Không xuất tùy ý metadata. Test delivery
có `event_type=integration.test`. Headers:

```text
Content-Type: application/json
User-Agent: VSign-Webhooks/1
X-VSign-Delivery: <stable delivery UUID>
X-VSign-Event: <event type>
X-VSign-Timestamp: <Unix seconds at attempt>
X-VSign-Signature: sha256=<HMAC hex>
```

HMAC-SHA256 dùng signing secret và bytes `timestamp + '.' + raw_request_body`.
Bên nhận cần compare hằng thời gian, kiểm timestamp (ví dụ lệch không quá5 phút),
và loại trùng delivery ID. Nội dung và delivery ID giữ nguyên khi thử lại;
timestamp/chữ ký tạo lại. Chỉ HTTP2xx là delivered; không theo redirect.

HTTPS cổng443, hostname TLS verification, không proxy môi trường; không URL
credentials/query/fragment. Kiểm tất cả DNS answers, chặn private/link-local/
multicast/reserved/IPv6 transition, kết nối IP đã kiểm thay vì phân giải lại.
Một subprocess/lượt, tối đa20 giây DNS+network và tối đa3 giây dọn process;
claim lease60 giây. Retry tối đa5 lần, backoff15/60/300/900 giây. Worker mất
thì claim hết hạn được thu hồi khi dispatcher trở lại. Dừng webhook hủy lượt
pending/sending, nhưng không thể thu hồi request đã rời máy chủ. Rotate dùng
khóa ký mới cho lần gửi tiếp theo; request đang bay có thể dùng khóa cũ.

## Giới Hạn Và Vận Hành

Fixed-minute DB counters:60/key,300/workspace cho machine requests; người tạo
key chỉ được hạ giới hạn key. Webhook30/endpoint,60/workspace/phút. SQLite dùng
BEGIN IMMEDIATE; PostgreSQL dùng workspace row lock. Counter cũ được dọn khi
ghi, không phải bộ đếm riêng từng process. Không có sliding-window/billing,
public edge abuse protection hoặc tùy chỉnh trần hệ thống trong UI.

Overview chỉ50 bản ghi gần đây; active keys luôn ưu tiên để còn thu hồi được.
Logs có phân trang; DB giữ lịch sử đầy đủ. Retention/archival chưa thuộc giai
đoạn này, cần theo dõi dung lượng DB. Outbox không đảm bảo exactly-once, không
tự replay sự kiện lịch sử, không đảm bảo bên nhận đã xử lý nghiệp vụ chỉ từ2xx.

Kiểm thử ghi dữ liệu nằm trong temp fixtures. Kiểm thử HTTPS dùng TLS thật trên
loopback với DNS/socket remap chỉ trong test, không thêm tùy chọn bỏ TLS/SSRF
vào production. Browser E2E không khởi động dispatcher hoặc gửi ra bên ngoài.
Chưa kiểm chứng HTTPS tới hạ tầng khách hàng, tải production hoặc PostgreSQL.
