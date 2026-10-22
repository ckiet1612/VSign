# Nhận dạng trên Modal GPU, tự fallback về Mac

Nhận dạng ưu tiên chạy trên Modal (NVIDIA L4/A10/T4/L40S/A100, PyTorch CUDA, cùng `best.pt` với Mac).
Khi Modal tắt, lỗi hoặc đang khởi động, trình duyệt tự dùng Mac (port 8000, Core ML).
Khi Modal hoạt động lại, trình duyệt tự quay về Modal giữa các lượt ký.

Mac vẫn giữ login, database, metadata, ghép câu và thu thập mẫu. Modal chỉ mở
`/health`, `/metadata` và `/ws/inference` (`RUNTIME_ROLE=inference_only`).

## Cách hoạt động

1. Trình duyệt đọc `/metadata` của Mac như cũ.
2. Hook `useInferenceEndpoint` gọi `/metadata` của Modal. Chỉ chuyển sang Modal khi
   `model_version`, `protocol_version`, `input_framing` và danh sách nhãn giống hệt Mac.
3. Trình duyệt xin token từ Mac (`POST /api/v1/inference/token`, cần đăng nhập và quyền
   `recognize:use`). Token ký HMAC, hạn 10 phút, rồi mở `wss://…modal.run/ws/inference?token=…`.
   Modal kiểm tra chữ ký bằng secret chung, không cần database.
4. Socket cũ phục vụ tiếp cho đến khi socket mới mở, nên chuyển runtime không làm mất kết nối.
   Token được làm mới bằng cách nối lại giữa các lượt, trước khi hết hạn 5 phút.
5. Fallback và quay lại:
   - Socket Modal mất quá 6 giây thì chuyển về Mac.
   - Khi đang dùng Mac và có người dùng, trình duyệt thử lại Modal mỗi 15 giây. Lần thử này
     cũng đánh thức container đang ngủ.
   - Không có lượt ký nào trong 10 phút thì trình duyệt đóng socket Modal để container ngủ
     (`scaledown_window` 5 phút), rồi chỉ thử lại khi có lượt ký hoặc camera bật.
   - Không chuyển khi một lượt đang chờ kết quả.

Trên camera, chip trạng thái hiện `AI: Đã kết nối · GPU` hoặc `· Mac`.

Đăng xuất không cắt ngay socket Modal đang mở: token đã cấp còn hiệu lực tối đa 10 phút.

## Cài đặt lần đầu

```bash
python3.12 -m venv .venv-modal && .venv-modal/bin/pip install modal python-dotenv
.venv-modal/bin/modal token new          # đăng nhập Modal trong trình duyệt
bash scripts/deploy_modal.sh
```

`deploy_modal.sh` làm các việc sau:

1. Tạo `data/inference-token-secret` nếu chưa có. File này được gitignore; không chép nó vào chat hay commit.
2. Đưa secret lên Modal Secret `vsign-inference-token`.
3. Deploy `deploy/modal_app.py`. Trước khi deploy, script kiểm tra gate, label map và SHA256
   của checkpoint, giống `run_personal_local.sh`.

Sau khi tạo secret lần đầu, khởi động lại service đang giữ port 8000. Nếu Mac dùng
LaunchAgent `vn.vsign.backend` như cấu hình hiện tại:

```bash
launchctl kickstart -k "gui/$(id -u)/vn.vsign.backend"
```

LaunchAgent chạy `scripts/run_public_local.sh` và tự đọc file secret. Chỉ chạy
`bash scripts/run_public_local.sh` trực tiếp khi port 8000 đang trống và không có service
tự khởi động lại. Khi Mac đã có secret, `POST /api/v1/inference/token` không kèm cookie
trả 401; nếu trả 404 nghĩa là Mac chưa có secret.

Modal in ra URL dạng `https://<workspace>--vsign-inference-inference.modal.run`. Đặt thêm
trên Vercel rồi redeploy:

```text
VITE_INFERENCE_MODAL_HTTP_URL=https://ckiet1612--vsign-inference-inference-ap-southeast.ap-south.modal.run
VITE_INFERENCE_MODAL_WS_URL=wss://ckiet1612--vsign-inference-inference-ap-southeast.ap-south.modal.run/ws/inference
```

Các biến `VITE_INFERENCE_*` và `VITE_PLATFORM_*` hiện có vẫn trỏ về `https://api.vsign.io.vn`.
Nếu bỏ hai biến Modal, web chỉ dùng Mac như trước.

## Web local cổng 5174

`apps/web/.env.development.local` đã được cấu hình hai URL Modal ở trên cùng các URL
Mac fallback/platform là `127.0.0.1:8000`. File này được gitignore và chỉ áp dụng cho
frontend development; không tự cập nhật Vercel.

Mở `http://127.0.0.1:5174`, tải lại trang rồi đăng nhập. Khi chọn nhận dạng trên server,
web ưu tiên Modal sau khi metadata khớp và Mac cấp token. Chip camera hiện `GPU` khi
socket Modal được chọn, hoặc `Mac` khi đang fallback/đợi Modal khởi động. Mac vẫn phải
chạy để phục vụ login và cấp token. Không dùng `localhost:5174` cho phiên đăng nhập này.

Lần chuyển vùng ngày 22/10/2026 lúc 20:39 (+07), Modal xác nhận deployment v2 trên app
`ap-aOiYYvcqSL5Pnyvvn0SxOJ`, Function `inference_ap_southeast` dùng GPU L4.
Vite 5174 đã nạp endpoint mới. Lúc 20:40, log báo đang chờ cấp L4 tại `ap-southeast`;
chưa xác nhận health hoặc nhận dạng trên endpoint mới. Cần kiểm tra lại trạng thái
thực tế, không coi `deployed` là container đã sẵn sàng.

Lúc 21:02 (+07) cùng ngày, deployment v4 đổi mặc định sang `ap` và cho phép
`L4`, `A10`, `T4`. Lúc 21:03 log xác nhận `NVIDIA A10G`, health trả 200.
Kiểm tra 20 clip cùng payload với Mac: 20/20 cặp cùng trạng thái và nhãn;
Modal trung vị 338 ms, P95 556 ms; RTT ứng dụng trung vị 244 ms và ping WebSocket
110 ms. Mac cùng lượt đo trung vị 313 ms, P95 326 ms.
Số đo gốc: `data/benchmarks/mac-modal-asia-fallback-20261022.json`.
Đây là 20 replay sau warmup, không phải đánh giá camera hoặc tải nhiều người dùng;
không gộp thành so sánh phần cứng với lượt benchmark L4/Mỹ trước đó.

Deployment v5 lúc 21:10 (+07) cùng ngày bổ sung L40S/A100 và thông báo tên GPU
qua WebSocket. Các test metadata, thông báo kết nối, chuyển socket và nhãn đã đạt;
hai lượt kiểm tra metadata sau deploy bị timeout, chưa xác nhận inference trực tiếp
trên v5. Kết quả A10G nêu trên thuộc v4, không phải xác nhận mọi GPU trong danh sách.

## Vận hành

| Việc | Lệnh |
| --- | --- |
| Deploy / cập nhật | `bash scripts/deploy_modal.sh` |
| Tắt Modal (web tự về Mac) | `.venv-modal/bin/modal app stop vsign-inference -y` |
| Bật lại | `bash scripts/deploy_modal.sh` |
| Xem log | `.venv-modal/bin/modal app logs vsign-inference` |

- Đổi model trên Mac thì phải deploy lại Modal. Nếu `model_version` lệch, web tự ở lại Mac.
- GPU mặc định ở `ap` (toàn châu Á); có thể ghi đè bằng `MODAL_REGION`.
  Danh sách GPU theo thứ tự ưu tiên là `L4`, `A10`, `T4`, `L40S`, `A100-40GB`, `A100-80GB`.
  Chỉ một GPU được cấp, không chạy đồng thời cả danh sách. Chi phí phụ thuộc GPU được cấp.
  Log `VSign CUDA device:` ghi thiết bị thực tế; metadata có `gpu_name`.
  WebSocket gửi `runtime_info` khi kết nối GPU để nhãn hiện đúng GPU của kết nối đó,
  ví dụ `Modal A10G` hay `Modal T4`. Client phải bỏ qua message không phải prediction.
  GPU chưa có tên xác nhận vẫn hiện `Modal GPU`; không đoán từ cấu hình ưu tiên.
  Function `inference_ap_southeast` dùng `routing_region="ap-south"` (Mumbai).
  Chọn vùng container phát sinh phụ phí theo Modal. Không suy ra vùng GPU chỉ từ URL routing.
  Khi đổi routing region lần nữa phải tạo Function mới; không đổi routing trên Function cũ.
- Cấu hình: một GPU trong danh sách trên, 4 CPU, 16 GiB RAM, tối đa 1 container. Mỗi WebSocket tối đa 1 giờ, sau đó web
  tự nối lại.
- Giới hạn message WebSocket của Modal là 2 MiB. Một clip 16 frame WebP 224 px chỉ khoảng 0,3 MB.
- Trên Modal, `best.pt` chạy FP32 CUDA; trên Mac là Core ML FP16. Trước khi bật cho người dùng, so hai
  runtime trên bộ Personal CV.

## Kiểm tra runtime

```bash
curl --max-time 60 https://ckiet1612--vsign-inference-inference-ap-southeast.ap-south.modal.run/health
.venv-modal/bin/modal app logs vsign-inference --tail 30 --timestamps
```

`deployed` chỉ xác nhận app đã được tạo. Phải kiểm tra thêm health, metadata và WebSocket
có token với đủ 16 frame mới xác nhận được runtime nhận dạng.

Image cài thêm CUDA NVRTC, khai báo đường dẫn thư viện và tạo symlink `libnvrtc.so`
trỏ tới file versioned thật. Thiếu các bước này, cuDNN có thể làm container crash với
`Could not load library libcudnn_cnn_infer.so.8 ... libnvrtc.so` ngay khi warmup model.
Khi đọc log sau redeploy, đối chiếu thời gian/container để tránh nhầm lỗi của image cũ.

Nếu log báo `waiting to be scheduled on a GPU_L4 worker`, Modal đang chờ cấp GPU;
request cold start có thể timeout dù image đã sửa đúng. Giữ Mac làm fallback trong thời gian
này. Health 200 trước đó không bảo đảm lần đánh thức tiếp theo được cấp GPU ngay.

Ngày 22/10/2026, deployment v5 đã trả health và metadata 200, đúng model/framing/31 nhãn;
health đo từ Mac khoảng 0,88-0,98 giây. Sau khi container ngủ, lần kiểm tra tiếp theo phải
chờ cấp L4 và timeout lúc mở WebSocket. Khi được cấp lại GPU, runtime khởi động thành công.

WebSocket Modal đã xử lý ba lượt 16 frame tổng hợp, trả prediction hợp lệ: khoảng 734 ms
ở lượt đầu và 390-392 ms ở hai lượt sau, tính từ gửi clip đến nhận phản hồi trên Mac.
Các kết nối thiếu token, dùng token giả hoặc origin không hợp lệ đều bị từ chối HTTP 403.
Mac cũng nhận token dùng chung và xử lý được clip 16 frame. Route cấp token của Mac cả
local và public trả 401 khi không có cookie đăng nhập.

Replay cùng clip ghi `Chào` (16 frame) qua hai runtime cho cùng nhãn và top-3:
Modal trả `ok`, confidence khoảng 0,987745, thời gian phản hồi 1.327 ms; Mac trả `ok`,
confidence khoảng 0,987754, thời gian phản hồi 1.237 ms. Đây là một clip công khai,
không phải kết quả đánh giá toàn bộ bộ dữ liệu hay bằng chứng Modal nhanh hơn Mac.

Các số đo trong phần smoke test trên thuộc endpoint Mỹ cũ, trước khi đổi sang châu Á.
Benchmark Mac/Mỹ được lưu riêng tại `data/benchmarks/mac-modal-20261022.json`;
không dùng số đo cũ làm số đo endpoint châu Á.

Đây là smoke test runtime, chưa phải benchmark camera-to-display, đánh giá Personal CV,
kiểm thử tải hay nghiệm thu đăng nhập/chuyển runtime trên web public. Chưa thay cấu hình
Vercel và chưa redeploy frontend public trong lần kiểm tra này.
