# Màn hình khách (nhận dạng trên hai laptop)

Tại quầy bán hàng dùng hai laptop:

- **Laptop khách** mở `https://vsign.io.vn/display`. Màn hình chỉ có camera của khách, khung hướng dẫn, từ vừa nhận và câu.
- **Laptop nhân viên** dùng trang Nhận dạng như trước. Video lấy từ camera của laptop khách qua WebRTC.

Nhận dạng chạy trên máy nhân viên, qua `/ws/inference` như cũ. Kết quả được máy chủ chuyển sang máy khách qua `/ws/display/{id}`. Video đi thẳng giữa hai máy và không được lưu trên máy chủ.

## Đăng ký laptop khách (một lần)

Việc này cần quyền quản trị workspace: owner, admin hoặc system admin.

1. Trên máy nhân viên, vào **Cài đặt → Màn hình khách**. Nhập tên quầy (ví dụ "Quầy 1") rồi chọn **Thêm màn hình quầy**. Màn hình hiện mã 6 số và mã QR. Mã chỉ dùng một lần, hết hạn sau 10 phút, và bị khoá sau 10 lần nhập sai.
2. Trên laptop khách, mở `https://vsign.io.vn/display` rồi nhập mã. Hoặc quét QR, hoặc mở liên kết đã sao chép.
3. Cả hai máy hiện cùng một **mã đối chiếu 2 ký tự**. Nếu hai mã trùng nhau, nhân viên chọn **Xác nhận**.

Laptop khách lúc này nhận cookie `vsign_display`. Cookie này không có hạn phía máy chủ, chỉ hết hiệu lực khi bị huỷ. Mở lại trình duyệt hay khởi động lại máy đều vào thẳng màn chờ, không cần nhập lại mã. Cookie chỉ mở được màn hình của đúng quầy đó và không gọi được API nào khác.

Muốn huỷ một quầy, vào **Cài đặt → Màn hình khách → Huỷ**. Laptop khách thoát ngay và quay về màn nhập mã.

## Phục vụ khách

1. Ở trang **Nhận dạng**, chọn quầy rồi chọn **Kết nối**. Trang sẽ nhớ quầy này cho lần tải lại sau.
2. Laptop khách bật camera, và video hiện trên máy nhân viên. Nhận dạng thủ công và tự động vẫn dùng như cũ. Từ và câu hiện trên cả hai máy.
3. **Cuộc hội thoại mới** xoá từ và câu trên cả hai máy nhưng vẫn giữ kết nối.
4. **Kết thúc phiên** đưa laptop khách về màn chờ và tắt camera. Máy vẫn còn đăng ký.

Mỗi quầy chỉ có một nhân viên kết nối tại một thời điểm. Nhân viên thứ hai sẽ thấy ai đang dùng quầy và có thể chọn **Tiếp quản**. Người đang dùng trước đó sẽ được báo lý do.

Khi mất kết nối:

- Máy nhân viên báo "Mất video từ …" và ẩn hình ngay khi video ngừng chạy khoảng 1,5 giây. Hình đóng băng không bao giờ được dùng làm hình trực tiếp.
- Máy khách xoá từ và câu, rồi hiện "Mất kết nối với máy nhân viên". Camera được giữ thêm 30 giây để chờ nối lại.
- Cả hai máy tự nối lại.

## Yêu cầu

- **HTTPS.** Trình duyệt chỉ cho dùng camera và WebRTC trên HTTPS (hoặc `localhost`).
- **Quyền camera** trên laptop khách. Nên chọn "Luôn cho phép" cho `vsign.io.vn`.
- **Mạng.** Hai laptop dùng cùng Wi-Fi hoặc LAN thì chỉ cần STUN (mặc định là `stun:stun.l.google.com:19302`). Nếu hai máy ở hai mạng khác nhau, hoặc mạng chặn UDP ngang hàng, thì cần TURN. Cloudflare Tunnel không chuyển UDP nên không thay được TURN. Cấu hình TURN trên máy chủ như sau:

  ```bash
  export DISPLAY_ICE_SERVERS='[{"urls":"stun:stun.l.google.com:19302"},{"urls":"turn:turn.example.com:3478","username":"vsign","credential":"..."}]'
  ```

  Chỉ chấp nhận URL bắt đầu bằng `stun:`, `turn:` hoặc `turns:`, cùng các khoá `urls`, `username`, `credential`. Nếu cấu hình sai, máy chủ sẽ không khởi động.
- **Một worker uvicorn.** Trạng thái phòng (ai đang kết nối quầy nào) nằm trong bộ nhớ tiến trình. Khi máy chủ khởi động lại, hai máy tự nối lại, và quầy vẫn còn vì được lưu trong cơ sở dữ liệu.

## Chế độ kiosk cho laptop khách

Chrome hoặc Edge, mở toàn màn hình và không có thanh địa chỉ:

```bash
# macOS
open -na "Google Chrome" --args --kiosk https://vsign.io.vn/display
# Windows
chrome.exe --kiosk https://vsign.io.vn/display
```

Nên tắt chế độ ngủ và trình bảo vệ màn hình. Thêm lệnh trên vào mục khởi động cùng hệ thống để laptop tự mở màn hình quầy sau mỗi lần bật máy.

## Triển khai

1. **Cơ sở dữ liệu.** Migration `0012_display_devices` tạo hai bảng `display_devices` và `display_enrollments`. Port 8000 chạy với `DATABASE_AUTO_CREATE=false`, nên phải chạy migration trước khi khởi động lại:

   ```bash
   # Từ thư mục gốc repo, sau khi sao lưu data/vsign-platform.db
   DATABASE_URL="sqlite:///$PWD/data/vsign-platform.db" PYTHONPATH=services/inference:. .venv/bin/python -m app.migrate
   ```

   Sau đó khởi động lại port 8000 **chỉ bằng** `bash scripts/run_public_local.sh`.
2. **Web (Vercel).** `vercel.json` (gốc repo) chuyển mọi đường dẫn không phải tệp tĩnh về `index.html`, để `/display` và `/invite` mở được trực tiếp. Nếu không có rewrite này, Vercel trả 404 cho cả hai đường dẫn.
3. Các thao tác thay đổi đều dùng `POST`, vì CORS của API chỉ cho phép `GET` và `POST`.

## API

| Endpoint | Quyền | Mô tả |
|---|---|---|
| `GET /api/v1/displays` | `recognize:use` | Danh sách quầy, trạng thái online và nhân viên đang dùng. Quản trị viên thấy thêm các mã đang chờ. |
| `POST /api/v1/displays/enrollments` `{name}` | `settings:manage` | Tạo mã 6 số và link token. |
| `POST /api/v1/displays/enrollments/{id}/confirm` \| `reject` | `settings:manage` | Xác nhận hoặc từ chối một máy khách đã nhập mã. |
| `POST /api/v1/displays/{id}/rename` `{name}` | `settings:manage` | Đổi tên quầy. |
| `POST /api/v1/displays/{id}/revoke` | `settings:manage` | Huỷ quầy và đóng socket của nó (mã đóng 4003). |
| `POST /api/v1/displays/claim` `{code}` hoặc `{link_token}` | không cần đăng nhập, giới hạn tần suất | Máy khách nhập mã và nhận mã đối chiếu. |
| `GET /api/v1/displays/me` | cookie `vsign_display` | Trạng thái của chính máy khách. |
| `WS /ws/display/{id}?role=staff\|device[&takeover=1]` | phiên đăng nhập hoặc cookie thiết bị | Trao đổi tín hiệu WebRTC, trạng thái hiển thị và lệnh. |

Mã đóng WebSocket:

| Mã | Ý nghĩa |
|---|---|
| 4001 | Bị thay bằng cửa sổ khác của cùng quầy. |
| 4003 | Quầy đã bị huỷ. |
| 4009 | Quầy đang có nhân viên khác dùng. |
| 4010 | Bị tiếp quản. |
| 4011 | Nhân viên kết thúc phiên. |

Contract chi tiết nằm trong `contracts/v1/display.py` và `contracts/v1/display.ts`.
