# VSign

VSign là vertical slice để **nhận dạng từng ký hiệu VSL rời rạc** bằng camera trình duyệt. Người dùng giữ nút hoặc phím Space, hoặc chọn tự động phát hiện đầu/cuối của từng ký hiệu; frontend lấy mẫu 16 frame, ưu tiên gửi tới model Sales30 trên inference server và dùng model landmark trong trình duyệt làm fallback. Thêm từ mặc định là thủ công bằng click; người dùng có thể bật thêm từ tự động riêng với chế độ thu ký hiệu.

> Runtime local mặc định dùng `sales30-mvitv2s-seated-v3-epoch5` với 30 nhãn.
> Artifact đứng epoch 7 và các model landmark vẫn được giữ riêng để fallback và
> đánh giá A/B. Chi tiết bộ từ tại [`docs/SALES_30.md`](docs/SALES_30.md).
>
> Phiên local ngày 2026-10-09 đã triển khai candidate personal epoch 29: fine-tune
> head từ seated-v3, giữ backbone và thêm lớp `Không ký hiệu`. Candidate có launcher
> riêng; mặc định ONNX/Docker vẫn là v3. Evidence và rollback tại
> [`docs/PERSONAL_FINETUNE_LOCAL.md`](docs/PERSONAL_FINETUNE_LOCAL.md).

## Increment hiện tại

- Candidate seated + personal epoch 33 được train riêng, không dùng clip đứng
  để cập nhật trọng số. Bản local cho phép chuyển model trong UI và quay lại
  model hiện tại; chưa phải cải thiện chất lượng rõ rệt hay model mặc định mới.
  Kết quả và lệnh chạy tại [`docs/SEATED_PERSONAL_LOCAL.md`](docs/SEATED_PERSONAL_LOCAL.md).
- Dev/test thủ công chỉ trên bản development: chọn từ kỳ vọng, lưu clip/kết quả,
  kiểm định clip, thống kê từng từ và xuất CSV/JSON; tách hoàn toàn khỏi dữ liệu
  train và bundle production. Khởi động riêng tại
  [`docs/MANUAL_DEV_TEST_LOCAL.md`](docs/MANUAL_DEV_TEST_LOCAL.md).
- React + TypeScript + Vite, giao diện tiếng Việt, responsive và có accessible names/`aria-live`.
- Camera chỉ được xin quyền sau khi bấm “Bật camera”; xử lý denied, thiếu/bận/ngắt camera và dừng mọi track khi tắt/unmount.
- Tracking tay và thân trên chạy local, vẽ đầu/vai/khuỷu/cổ tay; nhánh landmark dùng khung thích ứng, còn Sales30 RGB dùng khung vuông cố định giữa ảnh.
- Lớp vẽ tracking dùng lọc One Euro thích ứng và giữ màu theo từng tay. Điểm mất dấu chỉ được giữ/mờ tối đa 150 ms để hiển thị; không được tính là tay quan sát mới hoặc đưa vào feature AI/điều kiện thu mẫu. Khi mất bàn tay nhưng pose còn hợp lệ, chỉ vẽ phần cơ thể/cổ tay quan sát được, không dựng thêm ngón tay.
- V3 `16 × 128` là runtime demo mặc định. V5 bootstrap `16 × 185` giữ nguyên V3 và chỉ cho nhánh context có giới hạn xử lý cụm `Uống–Ăn–Trường học–Nói–Đâu`; V4.2 và V5 đều nằm ở nút thử nghiệm cho tới khi vượt paired A/B camera độc lập.
- 80 đoạn idle thật ở biên clip tạo lớp `Không ký hiệu`; top-1 idle hoặc confidence/margin thấp luôn trả `uncertain`, không được thêm vào câu.
- Bản local ưu tiên Sales30 RGB trên inference server; khi server mất kết nối mới fallback sang landmark ONNX trong browser. Public demo không mở socket và chỉ dùng landmark local.
- Hold-to-sign bằng pointer/touch hoặc Space, clip 0,65–3 giây và queue giới hạn. Sales30 RGB lấy đều đúng 16 frame như pipeline train; landmark local vẫn ưu tiên mật độ chuyển động.
- Sales30 RGB dùng crop vuông cố định ở giữa, resize `224×224`, encode WebP/JPEG; ưu tiên Web Worker + OffscreenCanvas và fallback canvas khi không hỗ trợ.
- FastAPI với `GET /health`, `GET /metadata`, `WS /ws/inference`; validate UUID/schema/MIME/base64/kích thước và decode bằng Pillow.
- Một inference slot; request đến khi slot bận nhận `busy` thay vì nằm chờ.
- Transcript trong bộ nhớ gồm thêm thủ công, cooldown 1 giây, hoàn tác, xóa và copy có fallback.
- Chọn **Thêm từ → Thủ công/Tự động** độc lập với **Giữ để ký/Tự động beta**. Tự động chỉ thêm kết quả `ok` của model thật với nhãn và phiên bản đã xác minh, một lần cho mỗi lượt hợp lệ; giữ nguyên cooldown và ngưỡng nhận dạng.
- Adapter PyTorch MViTv2-S và ONNX tách khỏi mock, giữ nguyên frontend/protocol khi đổi runtime.
- Model thật trả top-3/confidence; UI phân biệt rõ mock, AI thật và label chưa xác minh.
- Transcript có thể gửi riêng danh sách từ đã xác nhận tới `POST /sentence/compose`; OpenAI Responses chỉ được gọi khi server có cả `OPENAI_API_KEY` và `OPENAI_MODEL`, nếu không server chuẩn hóa câu cục bộ.
- Pipeline tải/xác minh SHA256, giải nén Unicode an toàn, tạo split theo nhóm filename và chọn common-20 từ ViSignLanguage-Video.
- Chế độ **Thu dữ liệu AI** dùng riêng 30 nhãn bán hàng `sales-30` cộng lớp negative, không phụ thuộc danh sách output của model `common-20` đang chạy.
- Thu dữ liệu có phiên **Tự động**: Bắt đầu, đếm ngược, quay 2,1 giây, kiểm tra tối thiểu 8/16 frame tay, tự lưu và chuyển lượt; có Tạm dừng/Tiếp tục/Dừng, tự dừng khi đủ 100 mẫu/từ hoặc tạm dừng khi lưu lỗi. Thu dữ liệu không cần model nhận dạng sẵn sàng.
- Đợt bổ sung `personal-100` có 100 mẫu tổng mỗi từ, dùng tay thuận, không yêu cầu chia hai tay. Đếm riêng đợt mới, không xóa hoặc thay thế dữ liệu cũ. Quota từng tay và kế hoạch V5/common-20 cũ chỉ còn áp dụng cho API/pipeline legacy.
- Mỗi mẫu thu có thể gắn khoảng cách, ánh sáng và loại hành động negative; pipeline frozen-camera báo cáo riêng theo từng điều kiện.
- Chế độ **Tự động (beta)** chỉ khởi động sau nhiều frame có landmark bàn tay thật, lọc rung bằng cửa sổ trung vị, chuẩn hóa chuyển động theo thời gian để ổn định ở 15–30 FPS, giữ pre-roll/post-roll theo mili giây và chờ trạng thái nghỉ trước khi nhận từ tiếp theo. Pose cổ tay/khuỷu chỉ duy trì một ký hiệu đã bắt đầu khi tay bị che, không còn tự kích hoạt clip chỉ có cơ thể. Việc thu tự động không tự bật chế độ thêm từ tự động.

“Giữ để ký” vẫn là luồng kiểm soát tốt nhất. “Tự động” là beta vì lớp idle hiện mới bao phủ trạng thái đứng yên ở biên clip, chưa đủ các cử động đời thường như chỉnh tóc/kính hoặc quay người. Thêm từ thủ công vẫn là mặc định; thêm tự động cần người dùng chủ động bật và có thể hoàn tác khi nhận sai.

Phân tích regression V3/V4.2 và số liệu trước/sau sửa nằm tại
[`docs/V3_V4_2_REGRESSION.md`](docs/V3_V4_2_REGRESSION.md). Quy trình paired
release gate nằm tại [`docs/FROZEN_CAMERA_EVAL.md`](docs/FROZEN_CAMERA_EVAL.md).
Kế hoạch dữ liệu candidate tiếp theo nằm tại
[`docs/V5_DEVELOPMENT.md`](docs/V5_DEVELOPMENT.md).

## Kiến trúc

```text
apps/web                 camera → Sales30 server-first → landmark local fallback → UI
        │ fallback/lưu mẫu: 16 JPEG/WebP data URLs
        ▼
services/inference       validation → mock/PyTorch/ONNX backend + collection

contracts/v1             JSON Schema, TypeScript types, Pydantic models, examples
ml/configs               cấu hình train/evaluate/export common-20
ml/data                  schema/template; tuyệt đối không chứa video thật
ml/scripts               data audit, label generator và checkpoint smoke test
tests                    backend/data integration tests và synthetic fixtures
```

## Yêu cầu

- Node.js `>=22.12` và npm (đã kiểm tra với Node `26.4.0`, npm `11.17.0`).
- Python `3.9–3.11` cho runtime PyTorch đã kiểm chứng (đã chạy với Python `3.9.6`).
- Docker + Docker Compose nếu chạy bằng container.

## Chạy local

Bản demo công khai hiện chạy trên GitHub Pages. Bản này dùng HTTPS, chạy V3 ONNX và
MediaPipe hoàn toàn trong trình duyệt; không kết nối backend `localhost` của
người truy cập, không cho phép lưu/thu video. Thu dữ liệu và train vẫn phải
chạy từ workspace local. Để tạo lại bản web công khai cho GitHub Pages:

```bash
cd apps/web
npm run build:public
```

Khi triển khai tại tên miền riêng hoặc trang Pages ở gốc tên miền, dùng
`npm run build:public:root` để các tài nguyên tải từ `/`.

Chỉ nội dung `apps/web/dist/` được triển khai; dữ liệu webcam dưới
`ml/data/collected/` không được đưa lên web. Hiện trang public không tự đồng bộ
với chỉnh sửa local; sau mỗi thay đổi phải build và cập nhật lại nhánh
`gh-pages` rồi xác nhận GitHub Pages đã build xong.

Từ root repo, cài và chạy backend mock:

```bash
python3 -m venv .venv
.venv/bin/pip install -e 'services/inference[test]'
PYTHONPATH="services/inference:." .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Trong terminal khác:

```bash
cd apps/web
npm install
npm run dev
```

Mở `http://localhost:5173`, bấm **Bật camera**, giữ **Giữ để ký** hoặc Space tối thiểu 0,65 giây, rồi thả. Backend mock sẽ trả kết quả deterministic từ checksum frame/sequence; kết quả này không phản ánh ý nghĩa ký hiệu thực tế.

Health check:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/metadata
```

### Candidate Fine-Tune Personal Local

Sau khi dừng backend đang chiếm cổng 8000, chạy từ root repo:

```bash
./scripts/run_personal_local.sh
```

Launcher kiểm tra gate hồi quy, checksum và thứ tự 31 nhãn, khóa ngưỡng
`0.70`/`0.15`. Reload trang `http://localhost:5173` để đọc metadata mới.
Đây là triển khai development local; smoke dùng clip đã thu, chưa chứng minh
chất lượng webcam ở phiên mới. Model v3 được giữ nguyên để rollback.

Trên Mac Apple Silicon, chạy `./scripts/run_coreml_local.sh` để dùng bản
Core ML FP32 của cùng checkpoint. Benchmark replay median 722 -> 372 ms;
launcher kiểm tra gate và quay về PyTorch nếu artifact hoặc runtime lỗi.
Checkpoint cũ không bị thay thế; rollback bằng launcher personal ở trên sau
khi dừng backend hiện tại. Xem [hướng dẫn Core ML](docs/PERSONAL_COREML_LOCAL.md)
cho bằng chứng, giới hạn đo và cách benchmark lại.

### Tự động nhận dạng từng ký hiệu với Sales30 v3

Chế độ local có thể tự gom từ và ghép **câu dự thảo** khi nhân viên bật cả
thu ký hiệu tự động và thêm từ tự động. Hệ thống chờ capture/hàng đợi rỗng,
giữ từ cuối đến muộn và dừng ghép khi có đoạn chưa nhận dạng; không coi dự
thảo là yêu cầu đã xác nhận. Xem [luồng câu tự động B2B](docs/AUTOMATIC_SENTENCE_LOCAL.md).

1. Mở `http://localhost:5173`, chọn **Nhận dạng**, bấm **Bật camera**.
2. Khi AI đã kết nối, chọn **Tự động beta**. Giữ hai tay trong khung RGB vuông ở giữa.
3. Thực hiện một ký hiệu, rồi giữ tay yên một nhịp để hệ thống kết thúc lượt thu.
4. Mặc định **Thêm từ → Thủ công**: chờ kết quả và bấm **Thêm vào câu** nếu đúng. Muốn thêm không cần click, chọn **Thêm từ → Tự động**.
5. Chờ trạng thái sẵn sàng rồi ký từ tiếp theo. Chọn **Giữ để ký** hoặc **Tắt camera** để dừng.

Tracking tay/pose chạy local để xác định đầu/cuối. Nhánh Sales30 giữ pre-roll
650 ms, lấy đều đúng 16 ảnh RGB `224×224` theo crop vuông cố định, rồi gửi qua
WebSocket hiện có. Camera tiếp tục thu khi AI đang xử lý lượt trước. Hàng đợi
FIFO giữ tối đa **2 lượt chờ**, ngoài **1 request đang chạy**. Khi đủ 2 lượt chờ,
giao diện báo **Hàng đợi đầy**, tạm ngừng thu và tự cho thu tiếp khi có chỗ trống;
không thay thế clip cũ bằng clip mới. Chỉ một lượt inference được gửi tại một
thời điểm; ảnh camera chỉ giữ tạm trong bộ nhớ, không tự lưu video.

Lượt đã kết thúc bằng khoảng nghỉ/post-roll mở lại thu ngay sau khi xử lý ảnh,
không cộng thêm cooldown 700 ms rồi một vòng chờ tay nghỉ nữa. Lượt bị cắt ở
giới hạn 3 giây vẫn có cooldown an toàn; khoảng nghỉ được quan sát trong thời
gian đó. Khi chưa đủ điều kiện mở lượt mới hoặc vừa tiếp tục sau hàng đợi đầy,
giao diện báo **Chờ tay nghỉ**, không báo **Sẵn sàng**. Điều này vẫn yêu cầu các
ký hiệu rời rạc có khoảng nghỉ, không tự tách câu ký liên tục.

Đổi camera, chế độ hoặc nhánh AI hủy các clip chưa gửi và bỏ kết quả cũ đến muộn.
Request đã gửi không thể dừng model từ trình duyệt: slot được giữ đến khi reply
về, kể cả khi chuyển về thủ công. Khi socket đóng, bỏ slot của kết nối đã mất;
server có thể vẫn đang xử lý và trả `busy` nếu kết nối mới đến quá sớm.
Khi server mất kết nối, nhánh landmark
local chỉ hoạt động nếu model local đã sẵn sàng; đây không phải model Sales30 v3.

Readout hiển thị số lượt đang xử lý/chờ và timing của lượt hoàn tất gần nhất:
**Đoạn thu** là thời lượng đoạn ảnh gồm pre-roll/post-roll, **Encode ảnh** là
thời gian chuẩn bị ảnh gửi, **Chờ gửi** là thời gian trong hàng đợi, **Phản hồi AI**
là từ lúc gửi đến khi nhận kết quả (gồm truyền dữ liệu, decode và suy luận).
Đây không phải số đo riêng thời gian model hay độ trễ từ lúc người dùng thực sự
ký xong. Hàng đợi này dành cho clip chờ AI, không phải lịch sử kết quả; panel
nhận dạng vẫn hiển thị kết quả hiện tại. Thêm từ thủ công vẫn cần click; khi bật
thêm từ tự động, từng phản hồi hợp lệ được thêm ngay, kể cả khi hàng đợi đã chuyển
sang xử lý lượt tiếp theo.

Đây là tự động thu **từng ký hiệu rời rạc có khoảng nghỉ**, không phải tách từ
trong câu ký liên tục. Không đổi checkpoint hay ngưỡng confidence/margin của
Sales30 v3 (`0.70`/`0.15`). Phiên **Thu dữ liệu AI → Tự động** vẫn là luồng quay
và lưu mẫu riêng, không phải chế độ nhận dạng này.

### Thêm từ tự động, độc lập với cách thu ký hiệu

Lựa chọn **Thêm từ** nằm trong panel kết quả và mặc định là **Thủ công**. Bật
**Tự động** không đổi chế độ camera, model hay confidence/margin. Chế độ này dùng
được với cả **Giữ để ký** và **Tự động beta**, chỉ trong luồng nhận dạng.

- Chỉ các lượt bắt đầu thu sau khi bật mới được tự thêm; kết quả đang hiển thị,
  request đang xử lý và clip đã thu/đang chờ không bị thêm lại.
- Chỉ nhận `status: ok`, nhãn không phải idle, có trong label map đã xác minh,
  và `model_version` khớp runtime hiện tại. Mock, nhãn chưa xác minh, `uncertain`,
  `busy`, lỗi và kết quả hủy/đến muộn không được tự thêm.
- Tắt rồi bật lại không tự nhận lại các request của đợt cũ. Một sequence chỉ
  được tự thêm một lần, kể cả sau hoàn tác/xóa hoặc nhận reply trùng.
- Cooldown 1 giây cho cùng một từ vẫn giữ nguyên; một lượt ký mới sau cooldown
  vẫn có thể thêm lại từ đó. Hoàn tác, xóa và sao chép không thay đổi.
- Transcript và trạng thái chọn chỉ nằm trong bộ nhớ trang; không lưu video,
  không tự gọi API ghép câu và không tự gửi transcript đi nơi khác.

Kiểm thử tự động: `cd apps/web` rồi chạy `npm test`, `npm run build`,
`npm run lint`. Kiểm tra camera thật cần bao gồm đứng yên/không thấy tay,
ký từng từ, hai từ có khoảng nghỉ, và tắt camera/đổi chế độ khi đang xử lý.
Replay một clip cũ qua camera giả lập chỉ xác minh luồng kỹ thuật, không chứng
minh chất lượng nhận dạng với người ký mới hoặc điều kiện camera thật.
Smoke trình duyệt có thể chạy lại theo [`tests/e2e/README.md`](tests/e2e/README.md).

### Thu mẫu webcam để cải thiện AI

`./scripts/run_onnx_local.sh` bật sẵn chế độ thu dữ liệu local. Trên web, chọn
**Thu dữ liệu AI**, chọn một nhãn `sales-30`, tay thuận và điều kiện quay,
bật camera rồi bấm **Bắt đầu thu** một lần. Web đếm ngược, quay mỗi lượt
2,1 giây rồi tự lưu. Mỗi mẫu tạo một MP4 `224×224` và một JSON metadata tại:

```text
ml/data/collected/sales30/batches/personal-100/<tu>/<right|left>/
```

Màn hình Thu dữ liệu AI hiển thị video mẫu tương ứng cho đủ 30 từ Sales30,
có điều khiển phát và phát lại. Clip VSL-472 (CC BY 4.0) được phục vụ từ
`apps/web/public/reference-videos/sales30/`; `manifest.json` giữ nguồn và checksum.
Nhãn `Không ký hiệu` giữ hướng dẫn negative, không thay bằng một video ký hiệu.

Mục tiêu là **100 mẫu mỗi từ**, tổng cộng 3.000 mẫu positive; không bắt buộc
đổi tay. Chỉ tăng bộ đếm sau khi máy chủ xác nhận lưu thành công, tự dừng ở
100 và giữ nguyên từ đang chọn. Tải lại trang sẽ đọc tiến độ trên đĩa của
đợt `personal-100`, không cộng mẫu legacy tại `<tu>/<right|left>/`.

Nhãn do người thu chọn, không dùng dự đoán AI làm nhãn hoặc điều kiện lưu.
Kiểm tra hình tay chỉ là kiểm tra kỹ thuật, không xác nhận đúng nghĩa ký hiệu.
Lượt thiếu ảnh/tay được bỏ và thu lại; lỗi lưu tạm dừng, giữ mẫu trong bộ nhớ
và cho phép **Thử lưu lại** với cùng mã lượt để tránh tạo clip trùng khi mất
phản hồi. Không tự retry mạng. Tạm dừng/Dừng hủy lượt đang quay; mẫu đã lưu
không bị xóa. Request đã gửi có thể hoàn tất lưu sau khi dừng.

Dữ liệu và model cũ giữ nguyên. Chưa tự fine-tune, chưa tự chia train/validation/test;
hãy thu nhiều buổi với điều kiện khác nhau và audit trước khi train candidate
riêng. Lớp `Không ký hiệu` được thu riêng và không thuộc 30 nhãn.
Thư mục thu thập bị Git ignore. API legacy không truyền `batch` vẫn giữ hành vi cũ.

### Model common-20 legacy và lần train sales-30

Pipeline sales-30 mới dùng 30 nhãn trong
`contracts/v1/sales30.labels.json` và nguồn VSL-472 công khai. Audit, tải chọn
lọc và local smoke train:

```bash
.venv/bin/python -m ml.scripts.audit_sales30_sources
.venv/bin/python -m ml.scripts.download_sales30_sources
.venv/bin/python -m ml.scripts.build_sales30_manifest
.venv/bin/python -m ml.scripts.audit_sales30_manifest \
  ml/data/raw/sales30/manifest.csv \
  --data-root ml/data/raw/sales30/media
.venv/bin/python -m ml.scripts.train_visignlanguage \
  --config ml/configs/sales30_mvitv2_s.yaml \
  --output-dir runs/sales30_smoke \
  --device cpu --epochs 1 --batch-size 1 --num-workers 0 \
  --max-train-batches 1 --max-val-batches 1 --no-pretrained
```

Full 12-epoch run dùng Kaggle GPU miễn phí theo
[`ml/notebooks/SALES30_KAGGLE.md`](ml/notebooks/SALES30_KAGGLE.md). Kết quả từ
split hiện tại là `development-only`, chưa phải production gate.

Các lệnh V4/V5 bên dưới chỉ tái tạo checkpoint `common-20` hiện tại. Chúng chưa
phải pipeline train `sales-30`. Không chạy chúng với label map 30 lớp cho đến
khi extractor, public manifests và evaluation gate đã được chuyển đồng bộ.

Máy Mac local thực hiện được toàn bộ bước này trên CPU; không cần Colab GPU.
Lệnh đầu trích feature MediaPipe theo contract train V4.2; lệnh cuối train,
đánh giá, export ONNX và copy model vào `apps/web/public/models/`:

```bash
.venv/bin/pip install -r ml/requirements.txt
.venv/bin/python -m ml.scripts.extract_landmarks_v4
.venv/bin/python -m ml.scripts.build_idle_landmarks_v4
.venv/bin/python -m ml.scripts.train_landmarks_v4
```

Run hiện tại có 207 mẫu webcam, 80 đoạn idle thật và 660 mẫu public cân bằng
(common-20 + 80 lớp OOV). Split phát triển kết hợp có 769 train/178 validation;
checkpoint đạt 90,4% validation thường, 91,0% mirrored và 91,0% stress che một
tay. Khi dùng hai view giống browser, validation đạt 91,0%; false-accept OOV là
4,1% ở chế độ giữ và 3,1% ở chế độ tự động. Đây vẫn là kiểm tra phát triển,
không được diễn giải là độ chính xác với người ký mới. Metrics/model nằm tại
`ml/artifacts/landmark_v4/`.

Để tái tạo phần public/OOV rồi train model đã chọn:

```bash
.venv/bin/python -m ml.scripts.extract_public_landmarks_v4
.venv/bin/python -m ml.scripts.train_landmarks_v4 \
  --supplement-dataset ml/data/processed/landmarks_v4/public_balanced_trainval.npz
```

Artifact chuyên gia V2/V3 cũ chỉ dùng để so sánh/fallback trong đánh giá:

```bash
.venv/bin/python -m ml.scripts.extract_public_focus_landmarks
.venv/bin/python -m ml.scripts.train_landmarks_v2 \
  --supplement-dataset ml/data/processed/landmarks_v3/public_school_chao.npz \
  --supplement-max-groups-per-label 100 \
  --occlusion-probability 0.5 \
  --output-dir ml/artifacts/landmark_school_expert/v2 \
  --web-model-name vsign-school-expert-v2.onnx
.venv/bin/python -m ml.scripts.train_landmarks_v2 \
  --architecture keyframe-v3 \
  --supplement-dataset ml/data/processed/landmarks_v3/public_school_chao.npz \
  --supplement-max-groups-per-label 100 \
  --occlusion-probability 0.5 \
  --output-dir ml/artifacts/landmark_school_expert/v3 \
  --web-model-name vsign-school-expert-v3.onnx
```

### V5 bootstrap có cổng bảo vệ V3

V5 khóa toàn bộ checkpoint V3, thêm ngữ cảnh thân trên và chỉ cho phép hiệu
chỉnh 5 logits mục tiêu với biên độ hữu hạn; 15 logits còn lại không thể bị sửa.
Nếu pose không đủ hoặc V3 đang chọn một từ ngoài nhóm mục tiêu, output V5 bằng
đúng V3.

```bash
.venv/bin/python -m ml.scripts.train_landmarks_v5
```

Candidate hiện là **development-only**. Nút V5 trên web chỉ để thử; V3 vẫn là
mặc định cho tới khi thu xong development set và V5 vượt paired A/B release
gate. Chi tiết tại [docs/V5_DEVELOPMENT.md](docs/V5_DEVELOPMENT.md).

Pipeline scale-up không giả số lượng bằng cách lặp clip. Sau khi thu đủ quota,
trích V5 cho public train/validation và webcam rồi bật chốt cứng 100 mẫu/từ:

```bash
.venv/bin/python -m ml.scripts.extract_landmarks_v5 \
  --manifest ml/data/raw/visignlanguage-video/common20_manifest.csv \
  --output ml/data/processed/landmarks_v5/public_trainval.npz
.venv/bin/python -m ml.scripts.extract_landmarks_v5 \
  --input-dir ml/data/collected/webcam \
  --output ml/data/processed/landmarks_v5/webcam.npz
.venv/bin/python -m ml.scripts.train_landmarks_v5 \
  --supplement-v5-dataset ml/data/processed/landmarks_v5/public_trainval.npz \
  --supplement-v5-dataset ml/data/processed/landmarks_v5/webcam.npz \
  --require-samples-per-label 100
```

### Chuẩn bị nguồn ViSignLanguage-Video

Dataset CC BY 4.0 được tải ngoài Git. Pipeline kiểm tra checksum, không thực thi pickle tùy ý, chuẩn hóa tên tiếng Việt về NFC và tạo split không rò rỉ các biến thể `_1/_2/_3` của cùng video gốc:

```bash
.venv/bin/pip install -r ml/requirements.txt
.venv/bin/hf download star092304/ViSignLanguage-Video dataset.zip \
  --local-dir ml/data/raw/visignlanguage-video

.venv/bin/python -m ml.scripts.prepare_visignlanguage_video \
  --archive ml/data/raw/visignlanguage-video/dataset.zip \
  --metadata ml/vendor/ViSignLanguage-Video/dataset_metadata.csv \
  --output-root ml/data/raw/visignlanguage-video
```

Kết quả local hiện tại: 3.875 video/100 lớp; split tự tạo gồm 3.086 train, 383 validation và 406 test. Common-20 có 989 video (799/90/100). Xem [docs/VISIGNLANGUAGE_VIDEO.md](docs/VISIGNLANGUAGE_VIDEO.md).

### Chạy baseline AI Multi-VSL legacy

Checkpoint local được giữ ngoài Git tại `ml/artifacts/source/`. Sau khi đã có artifact hợp lệ:

```bash
.venv/bin/pip install -e 'services/inference[pytorch,test]'
.venv/bin/pip install -r ml/requirements.txt
.venv/bin/python -m ml.scripts.generate_class_id_labels \
  ml/artifacts/source/multivsl1000_class_ids.json --class-count 1000
./scripts/run_ai_local.sh
```

Backend legacy load MViTv2-S một lần và trả top-3 từ 1.000 output. UI hiển thị class ID và khóa ghép câu để không nhầm kết quả này với model 20 từ mới. Hướng dẫn runtime nằm tại [docs/AI_RUNTIME.md](docs/AI_RUNTIME.md).

Trên Linux host có NVIDIA GPU và NVIDIA Container Toolkit:

```bash
docker compose -f docker-compose.yml -f docker-compose.ai.yml up --build
```

## Docker Compose

```bash
docker compose config
docker compose up --build
```

Compose khởi động PostgreSQL, chạy Alembic trước inference và bật login workspace.
Tạo `.env` từ `.env.example`, sau đó đặt tối thiểu `BOOTSTRAP_ADMIN_EMAIL` và
`BOOTSTRAP_ADMIN_PASSWORD` trước khi chạy. Sau khi health check đạt, mở
`http://localhost:8080`. Dừng bằng `Ctrl+C`, sau đó `docker compose down` nếu cần
xóa container/network do Compose tạo. `docker compose down -v` sẽ xóa dữ liệu
PostgreSQL local.

## Workspace platform Phase 0

Local development mặc định dùng quyền quản trị doanh nghiệp, không cần form đăng nhập, với
`APP_ENV=development` và `AUTH_REQUIRED=false`. Identity `Admin local` được lưu
riêng cho workspace, không có mật khẩu sử dụng được hay cookie phiên. Chỉ dùng
trên máy local; không công khai dịch vụ này. Database SQLite có thể tạo tự động:

```bash
APP_ENV=development DATABASE_AUTO_CREATE=true \
  DATABASE_URL=sqlite:///./data/vsign-platform.db \
  PYTHONPATH=services/inference .venv/bin/python -m uvicorn app.main:app --app-dir services/inference --port 8000
```

Đặt `LOCAL_ADMIN_ENABLED=false` để phát triển luồng đăng nhập sau này. Production
hoặc `AUTH_REQUIRED=true` không tự bật admin local; cấu hình ép bật bị từ chối.
Production hoặc PostgreSQL phải chạy migration trước khi start app:

```bash
DATABASE_URL=postgresql+psycopg://vsign:password@localhost:5432/vsign \
  PYTHONPATH=services/inference .venv/bin/python -m app.migrate
```

Database cũ được tạo bởi bản Phase 0 trước migration có thể được nhận diện và
chuyển tiếp an toàn một lần sau khi đã sao lưu:

```bash
DATABASE_URL=sqlite:///./data/vsign-platform.db \
  PYTHONPATH=services/inference .venv/bin/python -m app.migrate --adopt-legacy
```

Phase 0 gồm workspace, user/membership, năm vai trò doanh nghiệp, Argon2 password
hash, HttpOnly session cookie, capability flags và audit store. Tổng quan/Giám sát
đọc trạng thái dịch vụ thật; Hoạt động đọc audit theo workspace. Mô hình nhận dạng
chỉ hiển thị phiên bản đang dùng, trạng thái và lịch sử cập nhật. Chỉ số chưa có
nguồn thật không được thay bằng số liệu giả.

Cả năm vai trò doanh nghiệp đều không được đăng ký ứng viên, kiểm định, phê duyệt,
triển khai hoặc hoàn tác model. Vòng đời model dùng quyền `model_admin` nội bộ,
được cấp riêng ngoài giao diện doanh nghiệp; fine-tune vẫn chỉ tạo candidate.
Ở mốc nền tảng chưa có public signup, invitation, evaluation pipeline hoặc cấu
hình tích hợp; các tab chưa có contract thật giữ trạng thái disabled. Các mốc
Dữ liệu, Đánh giá và Tích hợp sau đó được ghi riêng. Chi tiết và giới hạn:
[báo cáo quản trị doanh nghiệp](docs/reports/2026-10-15-enterprise-admin-workspace.md).

Phase 4 nối Dữ liệu với platform: phiên thu bền vững, bộ dữ liệu theo phiên bản,
hạn mức mặc định 100 mẫu/ký hiệu và danh mục có ID ổn định. Chốt phiên bản tạo
snapshot MP4/JSON bất biến kèm manifest SHA256; không tự nhập mẫu cũ hoặc chạy
training/deploy. Chi tiết API, quyền và khôi phục:
[Workspace Data local](docs/WORKSPACE_DATA_LOCAL.md).
[Báo cáo kiểm chứng giai đoạn 4](docs/reports/2026-10-16-workspace-data.md).

Phase 6 nối Tích hợp với platform: khóa API chỉ đọc theo quyền, webhook HTTPS
có chữ ký, đăng ký sự kiện backend, hạn mức dùng chung và nhật ký đã lọc bí mật.
Worker webhook chạy riêng; mở trang không tự tạo khóa hoặc gửi webhook.
Admin local vẫn không cần đăng nhập; không mở cấu hình local ra Internet.
[Workspace Integrations local](docs/WORKSPACE_INTEGRATIONS_LOCAL.md).
[Báo cáo kiểm chứng giai đoạn 6](docs/reports/2026-10-16-workspace-integrations.md).

Phase 7 nối Thành viên & quyền: tìm kiếm/phân trang thành viên, đổi vai trò,
tạm khóa/khôi phục/gỡ trong workspace, lời mời dùng một lần và nhật ký quyền.
Lời mời gửi thủ công, không đặt lại mật khẩu tài khoản cũ hoặc tự đăng nhập.
Admin local vẫn giữ nguyên; không cấp quyền triển khai model qua màn hình này.
[Workspace Team local](docs/WORKSPACE_TEAM_LOCAL.md).
[Báo cáo kiểm chứng giai đoạn 7](docs/reports/2026-10-16-workspace-team.md).

## Test, lint và build

```bash
.venv/bin/pytest

cd apps/web
npm test
npm run lint
npm run build
npm audit
```

Kiểm tra data tools trên CSV của bạn:

```bash
.venv/bin/python -m ml.scripts.prepare_visignlanguage_video \
  --archive ml/data/raw/visignlanguage-video/dataset.zip \
  --metadata ml/vendor/ViSignLanguage-Video/dataset_metadata.csv \
  --output-root ml/data/raw/visignlanguage-video
```

Các công cụ Multi-VSL cũ vẫn được giữ để tái lập baseline nhưng không còn là nguồn train chính.

## Cấu hình

Root `.env.example` mô tả các biến được hỗ trợ:

| Biến | Mặc định | Vai trò |
| --- | --- | --- |
| `INFERENCE_BACKEND` | `onnx` trong `.env.example` | `mock`, `pytorch` hoặc `onnx` |
| `MODEL_VERSION` | `sales30-mvitv2s-seated-v3-epoch5` | Phiên bản trả trong response/metadata |
| `ONNX_MODEL_PATH` | `ml/artifacts/sales30_seated_v3/model.onnx` | Model bắt buộc khi backend là ONNX |
| `PYTORCH_MODEL_PATH` | rỗng | Checkpoint bắt buộc khi backend là PyTorch |
| `PYTORCH_DEVICE` | `auto` | `auto`, `cpu` hoặc `cuda`; không dùng MPS |
| `LABEL_MAP_PATH` | rỗng | JSON/CSV theo đúng output index của model |
| `LABELS_VERIFIED` | `false` | Chỉ đặt `true` sau khi mapping đã được xác minh |
| `CONFIDENCE_THRESHOLD` | `0.70` | Reject top-1 thấp |
| `MARGIN_THRESHOLD` | `0.15` | Reject margin top1–top2 thấp |
| `ALLOWED_ORIGINS` | localhost `5173`, `5174`, `5175`, `8080` | Origin HTTP/WebSocket được phép |
| `MAX_FRAME_BYTES` | `262144` | Giới hạn bytes sau decode cho mỗi frame |
| `MAX_MESSAGE_BYTES` | `6291456` | Giới hạn toàn bộ WebSocket message |
| `COLLECTION_ENABLED` | `false` | Cho phép API/UI lưu mẫu webcam có xác nhận |
| `COLLECTION_DIR` | `ml/data/collected/sales30` | Thư mục local chứa MP4 và metadata của bộ mới |
| `COLLECTION_TARGET_PER_HAND` | `50` | Mục tiêu số mẫu cho mỗi từ và mỗi tay |
| `OPENAI_API_KEY` | rỗng | Khóa server-only để bật hoàn thiện câu bằng OpenAI Responses |
| `OPENAI_MODEL` | rỗng | Model OpenAI phải được cấu hình cùng API key; không có giá trị mặc định ẩn |
| `VITE_INFERENCE_WS_URL` | `ws://localhost:8000/ws/inference` | WebSocket URL lúc Vite build/start |
| `VITE_INFERENCE_HTTP_URL` | `http://localhost:8000` | Metadata URL lúc Vite build/start |
| `VITE_PLATFORM_HTTP_URL` | `http://localhost:8000` | Workspace/auth API URL; độc lập với cổng model inference |
| `VITE_PLATFORM_AUTH_REQUIRED` | `false` local, `true` Compose | Chờ platform trước khi mount workspace khi login là bắt buộc |

Vite đọc biến từ shell hoặc `apps/web/.env.local`. Docker Compose đọc `.env` ở root và truyền URL frontend thành build args. Không đặt secret vào file env được commit.

## Runtime ONNX tùy chọn

Artifact Sales30 fine-tune cho tư thế ngồi được đặt ngoài Git tại
`ml/artifacts/sales30_seated_v3/`:

```bash
.venv/bin/pip install -e 'services/inference[onnx,test]'
./scripts/run_onnx_local.sh
```

Script mặc định đọc gói đã xác minh tại `ml/artifacts/sales30_seated_v3/`.
Exporter hiện tại tạo một file `model.onnx` nhúng toàn bộ trọng số; ONNX Runtime
vẫn tự đọc file `.data` cạnh model khi một artifact khác dùng external data.

Checkpoint tốt nhất của seated-v3 là epoch 5. So sánh CPU trên cùng manifest
v3: validation 744 video đạt accuracy `0,7419`, macro-F1 `0,6976` (v2:
`0,5995` và `0,5745`). Standing test 351 video giữ nguyên: accuracy hai model
đều `0,9658`; macro-F1 v3 `0,9485`, thấp hơn v2 `0,9612`. Số liệu Kaggle
gốc được giữ riêng tại `training/summary.json` và `test_metrics.json`;
phép so sánh CPU nằm trong `comparison.json`, không ghi đè số liệu Kaggle.

Người dùng chấp nhận seated-v3 sau khi thử camera và báo cáo nhận dạng tốt
hơn v2. Đây là lựa chọn runtime local, không phải kết quả paired A/B camera
độc lập hay chứng nhận production. Seated validation chỉ có người `Như`,
nguồn đứng không có signer ID; confidence `0.70` và margin `0.15` giữ nguyên.
Artifact v2 vẫn giữ riêng, rollback bằng:

```bash
MODEL_VERSION=sales30-mvitv2s-seated-v2-epoch5 \
ONNX_MODEL_PATH=ml/artifacts/sales30_seated_v2/model.onnx \
LABEL_MAP_PATH=ml/artifacts/sales30_seated_v2/labels.json \
./scripts/run_onnx_local.sh
```

Artifact đứng epoch 7 trước đó vẫn được giữ tại
`ml/artifacts/sales30_mvitv2_s/`. Có thể chạy lại để A/B mà không sửa file:

```bash
MODEL_VERSION=sales30-mvitv2s-vsl472-epoch7 \
ONNX_MODEL_PATH=ml/artifacts/sales30_mvitv2_s/model.onnx \
LABEL_MAP_PATH=ml/artifacts/sales30_mvitv2_s/labels.json \
./scripts/run_onnx_local.sh
```

Adapter yêu cầu một input float `[1,C,T,H,W]` và một logits output float `[1,num_classes]`; dtype, rank, dimension cố định và số class được kiểm tra ngay khi khởi động. Preprocess dùng RGB, 16 frame `224×224`, ImageNet normalization, softmax và top 3. Với CSV, thứ tự dòng phải đúng thứ tự output của model; `source_class_id` vẫn được giữ làm ID nguồn chính thức và không bị giả định là số liên tiếp. Với JSON có thể dùng array theo output index hoặc object có key index liên tiếp từ 0. Service fail-fast nếu artifact, label map, interface output hoặc runtime không hợp lệ.

## Camera và quyền riêng tư

`getUserMedia` chỉ hoạt động trong secure context: `localhost` được phép khi phát triển; mọi hostname/IP khác cần HTTPS. Ứng dụng không dùng `MediaRecorder`, không ghi frame/base64 vào console hoặc telemetry, không lưu video ở chế độ nhận dạng và giải phóng `ImageBitmap`/canvas/MediaStreamTrack sau khi dùng. Ở chế độ server-first, 16 ảnh đã lấy mẫu được gửi qua WebSocket chỉ để suy luận và bị giải phóng sau request. Khi người dùng bấm hoàn thiện câu, chỉ danh sách từ đã xác nhận được gửi tới API câu; API này chỉ chuyển tiếp sang OpenAI nếu server đã cấu hình rõ khóa và model. Trong chế độ **Thu dữ liệu AI**, frame chỉ được ghi thành MP4 local sau thao tác xác nhận **Lưu mẫu vào máy**; metadata không chứa base64.

## Việc còn lại trước public demo dịch ra tiếng Việt

- Dataset mới đã có license CC BY 4.0 và mapping 100 nhãn tiếng Việt; cần giữ attribution khi phát hành.
- Nguồn không có signer ID, nên split local không chứng minh khả năng tổng quát hóa sang người ký chưa thấy.
- Đã có idle biên clip nhưng chưa có đủ negative đời thường; thu tự động vẫn beta. Thêm từ thủ công là mặc định; thêm tự động cần chủ động bật và hoàn tác khi nhận sai.
- Landmark V4 mới được kiểm định với một người ký trong cùng buổi; cần bộ camera đóng băng nhiều khoảng cách/ánh sáng và người ký mới để đo generalization.
- Đã benchmark ONNX và thấy tracking khoảng 15 FPS với camera hiện tại; vẫn cần đo end-to-end P50/P95/cold start trên nhiều thiết bị.
- Cần benchmark/tinh chỉnh motion gate tự động với nhiều tốc độ ký và thiết bị camera hơn.

Không commit video, dataset, checkpoint, model binary, credential hay generated build output. Xem [PROJECT_PLAN.md](PROJECT_PLAN.md), [docs/VISIGNLANGUAGE_VIDEO.md](docs/VISIGNLANGUAGE_VIDEO.md) và [docs/AI_RUNTIME.md](docs/AI_RUNTIME.md) để biết lộ trình, nơi train/inference và điều kiện go/no-go.
