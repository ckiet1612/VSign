# VSign inference contract

`v1/` là contract version `1.0` dùng chung giữa web và inference service. `inference.ts`, `inference.py`, JSON Schema và examples mô tả cùng một protocol. Request luôn có đúng 16 ảnh JPEG/WebP dạng data URL. Server giữ nguyên `sequence` để client loại kết quả cũ hoặc sai thứ tự.

Cùng module contract còn có `SentenceComposeRequest`/`SentenceComposeResponse` cho `POST /sentence/compose`. Endpoint chỉ chấp nhận từ thuộc Sales30 và không nhận frame, transcript tự do hay credential từ client.

Giới hạn runtime mặc định: 256 KiB cho mỗi ảnh đã decode và 6 MiB cho toàn bộ WebSocket message. Các example chỉ minh hoạ cấu trúc; chuỗi ảnh rút gọn không phải ảnh hợp lệ để inference.

`v1/sales30.labels.json` là thứ tự nhãn chuẩn cho bộ thu thập/huấn luyện bán
hàng mới. Trường metadata `labels` vẫn mô tả output của checkpoint suy luận
đang chạy; `collection_labels` mô tả bộ nhãn được phép lưu mẫu.

## Workspace platform contract

Giai đoạn nền tảng dùng các endpoint versioned dưới `/api/v1/workspace`:

- `GET /api/v1/workspace` trả context local từ `WORKSPACE_ID`, `WORKSPACE_NAME`
  và `APP_ENV`, kèm `auth_required`.
- `POST /api/v1/auth/login`, `POST /api/v1/auth/logout` và `GET /api/v1/auth/me`
  dùng session cookie HttpOnly; không có public signup.
- `GET /api/v1/workspace/capabilities` trả capability flags theo backend hiện
  có. `false` nghĩa là contract backend chưa sẵn sàng, không phải lỗi runtime.
- `GET /api/v1/workspace/members` và `GET /api/v1/workspace/audit/events` yêu
  cầu membership phù hợp. Audit dùng cursor keyset và lưu trong database.

HTTP response có `X-VSign-API-Version: 1` và `X-Request-ID`. Client có thể gửi
`X-Request-ID` an toàn để nối log; nếu không gửi, server tự sinh một request ID.
Các endpoint inference hiện có vẫn giữ nguyên body contract và protocol `1.0`.

## Đợt thu bổ sung personal-100

`GET /collection/summary?batch=personal-100` trả tiến độ riêng với
`batch: personal-100`, `target_per_label: 100` và `counts` từng tay.
Quota là tổng `right + left` cho mỗi nhãn; người thu không cần đổi tay.
Không truyền `batch` vẫn đọc thư mục và quota legacy như trước.

`POST /collection/samples` nhận thêm `batch: personal-100` và `sample_key`
(UUID bắt buộc cho đợt mới). Mỗi lượt dùng một UUID cố định. Retry cùng payload
trả mẫu đã lưu; reuse mã với payload khác trả 409. Đủ 100 mẫu cũng trả 409,
ngoại trừ retry một mẫu đã lưu. Response thêm `label_count` tổng hai tay.
Đường dẫn trả về là `batches/personal-100/<label-slug>/<hand>/<sample_key>.mp4`
tính từ `COLLECTION_DIR`; không ghi đè dữ liệu legacy. Quota/save được tuần tự
hóa trong một process; chạy một worker cho dịch vụ thu local này.
Đợt mới chỉ đếm mẫu có đủ MP4 và metadata JSON đã commit; video chưa có metadata
không chiếm quota và có thể phục hồi bằng cùng mã lượt thu. API legacy vẫn giữ
cách đếm cũ.

## Cảnh báo ghép câu

`SentenceComposeResponse.warnings` bổ sung danh sách cảnh báo về cấu trúc
câu. Client mới vẫn chấp nhận response cũ chưa có trường này. Cảnh báo thiếu
đoạn nhận dạng được giữ riêng; ghép thành công không xác nhận rằng từ nhận
dạng đã đầy đủ hoặc đúng ngữ nghĩa VSL.

## Workspace Integration Contract

`v1/integrations.py` và `v1/integrations.ts` mô tả API version `1` cho quản lý
khóa API, webhook, đăng ký sự kiện, lượt giao và nhật ký tích hợp theo workspace.
Management dưới `/api/v1/workspace/integrations` yêu cầu owner/admin.
Khóa bí mật chỉ trả một lần, không nằm trong overview hoặc nhật ký.

Machine API dưới `/api/v1/integrations/{models|snapshots|evaluations}` chỉ đọc,
bắt buộc Bearer API key có scope tương ứng. Không dùng cookie/local admin làm
fallback; Bearer không cấp quyền gọi API quản trị. Response có `api_version`,
`workspace_id`, `items` và `next_cursor`; workspace do backend quyết định.
Vượt hạn mức trả `429` và `Retry-After`.

Webhook envelope chỉ xuất định danh sự kiện/tài nguyên đã cho phép, không xuất
video, đường dẫn hoặc audit metadata tùy ý. Giao ít nhất một lần, bên nhận cần
kiểm chữ ký HMAC, timestamp và loại trùng delivery ID. Chi tiết endpoint, giới
hạn và vận hành: `docs/WORKSPACE_INTEGRATIONS_LOCAL.md`.

## Workspace Team Contract

`v1/team.py` và `v1/team.ts` mô tả quản lý membership, ma trận vai trò, lời mời
và nhật ký quyền version `1`. `/api/v1/workspace/team` yêu cầu owner/admin;
không cấp owner/model_admin, không sửa self/owner/local admin. Update có
`expected_revision` và `request_id`, trạng thái chỉ theo workspace.

`/api/v1/invitations/{inspect|accept}` dùng mã mời trong body và mật khẩu rõ
ràng, không fallback cookie/local admin. Mã chỉ lưu hash, trả một lần khi tạo,
không trả trong dữ liệu đọc/validation errors. Chấp nhận không đổi mật khẩu cũ
hoặc tạo session. Phản hồi luôn kiểm `api_version`/`workspace_id`; danh sách tối
đa 50 và `next_cursor`. Chi tiết: `docs/WORKSPACE_TEAM_LOCAL.md`.
