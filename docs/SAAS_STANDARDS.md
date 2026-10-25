# Tiêu chuẩn Kỹ thuật SaaS cho Nền tảng VSign

Tài liệu này xác định các tiêu chuẩn kỹ thuật, bảo mật, vận hành và trải nghiệm người dùng áp dụng cho **VSign** khi triển khai dưới mô hình **SaaS (Software-as-a-Service)**.

VSign là nền tảng SaaS trợ năng (Assistive Tech) và thị giác máy tính thời gian thực (Real-time Computer Vision) hỗ trợ nhận dạng Ngôn ngữ Ký hiệu Việt Nam (VSL) tại quầy giao dịch, tích hợp màn hình kép (nhân viên & khách), quản lý workspace doanh nghiệp và quản trị dữ liệu huấn luyện.

---

## 1. Tiêu chuẩn Hiệu năng & Tốc độ (Performance & Latency)

Vì VSign phục vụ đối thoại trực tiếp tại quầy, độ trễ và độ mượt mà của khung hình là yếu tố quyết định chất lượng dịch vụ:

### 1.1. Độ trễ suy luận AI (Inference Latency)
* **Thời gian phản hồi đầu-cuối (End-to-End Latency):** $\le 200\text{ms} - 350\text{ms}$ tính từ khi người dùng nhả phím Space / nút bấm (hoặc thuật toán phát hiện kết thúc cử chỉ) cho tới khi từ hiển thị trên transcript.
* **Xử lý frame tại Frontend:**
  * Lấy mẫu đúng 16 frame RGB ($224 \times 224$), nén định dạng WebP/JPEG qua `Web Worker` và `OffscreenCanvas`.
  * Thời gian tiền xử lý frame phía client phải $\le 50\text{ms}$ để đảm bảo Main Thread không bị block, duy trì khung hình camera ổn định ở mức **60 FPS** (tối thiểu 30 FPS trên thiết bị yếu).
* **Kiểm soát nghẽn (Slot Backpressure):**
  * Inference server xử lý trên slot đơn; nếu slot đang bận, server phải trả về ngay mã `busy` ($< 10\text{ms}$), không đưa vào hàng đợi gây dồn ứ kết quả cũ.

### 1.2. Độ trễ Màn hình khách (WebRTC Customer Display)
* **Độ trễ truyền phát (RTT):** $\le 100\text{ms} - 150\text{ms}$ qua mạng Wi-Fi/LAN quầy giao dịch.
* **Xử lý mất frame:** Khi mất video quá **1.5 giây**, màn hình nhân viên phải ẩn khung hình ngay lập tức (không giữ frame đông cứng gây hiểu nhầm).

### 1.3. Khả năng chuyển đổi dự phòng (Fallback Switching)
* Khi inference server ngắt kết nối hoặc lỗi mạng, frontend chuyển sang mô hình Landmark ONNX/MediaPipe chạy trực tiếp trong trình duyệt trong vòng $\le 150\text{ms}$ mà không gián đoạn camera.

### 1.4. Web Vitals
* **LCP (Largest Contentful Paint):** $< 1.5\text{s}$ (nhờ lazy loading các model trọng số nặng và tách riêng bundle ứng dụng).
* **INP (Interaction to Next Paint):** $< 50\text{ms}$ đối với các thao tác bấm giữ, xóa từ, hoàn tác.
* **CLS (Cumulative Layout Shift):** $= 0$ cho bố cục camera và transcript.

---

## 2. Tiêu chuẩn Bảo mật & Quyền riêng tư (Security & Privacy)

Dữ liệu hình ảnh và chuyển động cơ thể của người ký là dữ liệu sinh trắc học và thông tin cá nhân nhạy cảm:

### 2.1. Bảo vệ dữ liệu video (Zero-Persistence Policy)
* **Không lưu trữ video nhận dạng:** Luồng video tại quầy phục vụ khách chỉ được giải mã trong bộ nhớ RAM (in-memory) để suy luận, sau đó hủy ngay lập tức. Tuyệt đối không ghi vào ổ đĩa hoặc cơ sở dữ liệu.
* **Tách biệt luồng Thu thập dữ liệu (Data Collection):** Chức năng lưu clip chỉ được kích hoạt trong phiên thu thập dữ liệu có chủ đích, có sự đồng thuận của người dùng và yêu cầu quyền quản trị tương ứng.

### 2.2. Định danh & Quản lý phiên (Authentication & Sessions)
* **Băm mật khẩu:** Bắt buộc sử dụng **Argon2id** với tham số độ phức tạp an toàn.
* **Cookie phiên:** Bắt buộc có cờ `HttpOnly`, `Secure`, và `SameSite=Lax`. Chặn chia sẻ cookie giữa các domain không an toàn.
* **Phân quyền truy cập (RBAC):** Phân tách nghiêm ngặt giữa `system_admin`, `owner`, `admin`, và `member`. Cách ly tuyệt đối dữ liệu giữa các Workspace doanh nghiệp (Multi-Tenant Isolation).

### 2.3. Ghép nối Màn hình quầy (Kiosk Pairing Security)
* Đăng ký laptop khách thông qua mã Pairing 6 chữ số dùng một lần (hết hạn sau 10 phút, tự khoá sau 10 lần nhập sai) kèm mã đối chiếu 2 ký tự trực quan.
* Cookie `vsign_display` cấp cho màn hình khách chỉ có quyền stream WebRTC và nhận nhãn hiển thị tại đúng quầy đăng ký, không có quyền truy cập bất kỳ REST API quản trị nào khác.

### 2.4. An toàn mạng & Giao thức
* Bắt buộc 100% **HTTPS** và **WSS (TLS 1.3)** (yêu cầu để trình duyệt cấp quyền Camera và WebRTC).
* Kiểm tra `Origin` nghiêm ngặt trên mọi request WebSocket và HTTP POST để ngăn chặn tấn công CSRF / CSWSH.
* Cấu hình STUN/TURN với thông tin chứng thực (credentials) có thời hạn, không để lộ TURN server mở.

---

## 3. Tiêu chuẩn Độ tin cậy & Khả năng sẵn sàng (Reliability & Availability)

### 3.1. Mức độ sẵn sàng (SLA)
* Cam kết thời gian hoạt động tối thiểu **99.9% Uptime** cho dịch vụ nhận dạng thời gian thực tại các điểm bán hàng/giao dịch.

### 3.2. Suy thoái mượt (Graceful Degradation)
* **Nhận dạng 2 tầng:** Ưu tiên Cloud/Edge GPU $\rightarrow$ Tự động rơi về Landmark ONNX in-browser khi mất kết nối backend.
* **Ghép câu 2 tầng:** Endpoint `POST /sentence/compose` ưu tiên dùng LLM (OpenAI Responses) để chuẩn hóa câu văn. Nếu API bên thứ ba gặp sự cố hoặc timeout, tự động rơi về bộ ghép câu dựa trên luật cục bộ (rule-based local composer) để không làm gián đoạn hội thoại.

### 3.3. Khôi phục kết nối tự động (Auto-reconnect)
* Tự động kết nối lại WebSocket và WebRTC khi mạng chập chờn.
* Khi mất kết nối giữa hai laptop, camera khách được giữ mở trong 30 giây để chờ kết nối lại, tránh việc trình duyệt khóa quyền camera.

### 3.4. Kiểm soát toàn vẹn mô hình (Model Integrity)
* Checkpoint mô hình chỉ được nạp vào runtime khi mã băm SHA256, số lượng nhãn và phiên bản tiền xử lý khớp chính xác với manifest đã kiểm định.

---

## 4. Tiêu chuẩn Trợ năng & Trải nghiệm (Accessibility & Ergonomics)

VSign phục vụ người Điếc, người Khiếm thính (DHH) và nhân viên thu ngân/tiếp tân:

### 4.1. Tiêu chuẩn Trợ năng WCAG 2.1 AA+
* **Độ tương phản màu sắc:** Tối thiểu $4.5:1$ đối với văn bản thông thường và $3:1$ cho các nút điều khiển, viền khung nhận diện.
* **Live Regions:** Khu vực transcript hiển thị câu phải cấu hình `aria-live="polite"` để phần mềm đọc màn hình (Screen Reader) thông báo ngay khi có từ mới.

### 4.2. Minh bạch trạng thái AI
* Giao diện phải phân biệt rõ ràng 3 trạng thái:
  * **Đã xác thực (Verified):** Từ nhận dạng bởi model chính thức với độ tin cậy vượt ngưỡng.
  * **Chưa chắc chắn (Uncertain):** Độ tự tin thấp hoặc rơi vào cử động nghỉ/nhiễu (Idle), không tự ý thêm vào câu.
  * **Giả lập (Mock):** Đang chạy mock backend để kiểm thử.

### 4.3. Công thái học vận hành
* **Phương thức kích hoạt linh hoạt:** Hỗ trợ phím Space, chạm/giữ trên màn hình cảm ứng, hoặc chế độ tự động phát hiện cử chỉ (Auto-detect có lọc trung vị chống rung).
* **Cooldown & Undo:** Cooldown 1 giây giữa các lượt nhận để chống trùng từ. Luôn hiển thị nút Hoàn tác (Undo) và Xóa từ tức thì.

---

## 5. Tiêu chuẩn Quản trị & Vận hành B2B (Governance & Operations)

### 5.1. Quản lý Vòng đời Dữ liệu (Data Retention)
* Hỗ trợ thiết lập chính sách lưu trữ (Retention Policy) cho từng workspace: tự động xóa lịch sử phiên, thống kê dev/test hoặc mẫu thu thập sau 30/60/90 ngày tuân thủ quy định bảo vệ dữ liệu.

### 5.2. Nhật ký kiểm toán (Audit Trail)
* Ghi nhận đầy đủ thông tin về các thay đổi quan trọng: thêm/xóa thành viên workspace, hủy kết nối màn hình khách, thay đổi phiên bản mô hình suy luận, xuất dữ liệu.
* API áp dụng cơ chế idempotent với `request_id` và `expected_revision` để chống xung đột ghi đồng thời (optimistic concurrency).

### 5.3. Giám sát & Đo lường (Telemetry & Observability)
* Cung cấp các endpoint chuẩn: `GET /health` (kiểm tra tiến trình sống) và `GET /metadata` (thông số runtime, model version, commit hash).
* Giám sát các chỉ số vận hành quan trọng:
  * Tỷ lệ nhận dạng thành công vs uncertain.
  * Tỷ lệ khung hình bị drop (Drop frame rate).
  * Thời gian suy luận phân vị p95 và p99.
  * Tần suất phản hồi trạng thái `busy`.

---

## 6. Bảng chỉ số kiểm soát chất lượng (SLI / SLO)

| Danh mục | Chỉ số đo lường (SLI) | Ngưỡng mục tiêu (SLO) | Hành động khi vi phạm |
| :--- | :--- | :--- | :--- |
| **Tốc độ AI** | End-to-End Latency | $\le 300\text{ms}$ (p95) | Tối ưu hóa kích thước frame, kiểm tra tải GPU |
| **Độ mượt** | Tốc độ dựng khung hình Camera | $\ge 50$ FPS | Chuyển việc trích xuất frame sang Worker |
| **Màn hình khách** | WebRTC Stream Latency | $\le 150\text{ms}$ | Kiểm tra kết nối mạng nội bộ hoặc cấu hình TURN |
| **Bảo mật video** | Lưu trữ video nhận diện quầy | **0 byte** trên đĩa | Báo động đỏ an ninh dữ liệu |
| **Độ khả dụng** | Uptime dịch vụ suy luận | $\ge 99.9\%$ | Tự động kích hoạt Local ONNX Fallback |
| **Độ chính xác** | Tỷ lệ nhận nhầm cử chỉ nghỉ | $\le 2\%$ | Điều chỉnh ngưỡng margin và bộ lọc Idle |
| **Trợ năng** | Khả năng tương thích WCAG | Đạt chuẩn AA+ | Sửa lỗi tương phản và thuộc tính ARIA |
