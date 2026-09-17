# VSign

VSign là vertical slice chạy local để **nhận dạng từng ký hiệu VSL rời rạc** bằng camera trình duyệt. Người dùng giữ nút hoặc phím Space trong lúc thực hiện một ký hiệu; frontend lấy mẫu 16 frame tay + thân trên, suy luận ngay trong trình duyệt và hiển thị dự đoán/top 3 để người dùng xác nhận vào transcript.

> Runtime nhận dạng hiện tại vẫn dùng checkpoint legacy `common-20`. Bộ mục tiêu mới `sales-30` được dùng riêng cho thu thập dữ liệu và lần huấn luyện kế tiếp; không thay label map của checkpoint cũ. Chi tiết tại [`docs/SALES_30.md`](docs/SALES_30.md).

## Increment hiện tại

- React + TypeScript + Vite, giao diện tiếng Việt, responsive và có accessible names/`aria-live`.
- Camera chỉ được xin quyền sau khi bấm “Bật camera”; xử lý denied, thiếu/bận/ngắt camera và dừng mọi track khi tắt/unmount.
- Tracking tay và thân trên chạy local, vẽ đầu/vai/khuỷu/cổ tay và tạo khung thích ứng theo tay.
- V3 `16 × 128` là runtime demo mặc định. V5 bootstrap `16 × 185` giữ nguyên V3 và chỉ cho nhánh context có giới hạn xử lý cụm `Uống–Ăn–Trường học–Nói–Đâu`; V4.2 và V5 đều nằm ở nút thử nghiệm cho tới khi vượt paired A/B camera độc lập.
- 80 đoạn idle thật ở biên clip tạo lớp `Không ký hiệu`; top-1 idle hoặc confidence/margin thấp luôn trả `uncertain`, không được thêm vào câu.
- Chế độ nhận dạng thường không nén hoặc gửi 16 ảnh khi model local sẵn sàng; server chỉ dùng dự phòng. V3, V4.2 và V5 chạy ONNX ngay trong browser.
- Hold-to-sign bằng pointer/touch hoặc Space, clip 0,65–3 giây, queue giới hạn, lấy đúng 16 frame theo thời lượng và mật độ chuyển động.
- Crop vuông, resize `224×224`, encode WebP/JPEG; ưu tiên Web Worker + OffscreenCanvas và fallback canvas khi không hỗ trợ.
- FastAPI với `GET /health`, `GET /metadata`, `WS /ws/inference`; validate UUID/schema/MIME/base64/kích thước và decode bằng Pillow.
- Một inference slot; request đến khi slot bận nhận `busy` thay vì nằm chờ.
- Transcript trong bộ nhớ gồm thêm thủ công, cooldown 1 giây, hoàn tác, xóa và copy có fallback.
- Adapter PyTorch MViTv2-S và ONNX tách khỏi mock, giữ nguyên frontend/protocol khi đổi runtime.
- Model thật trả top-3/confidence; UI phân biệt rõ mock, AI thật và label chưa xác minh.
- Pipeline tải/xác minh SHA256, giải nén Unicode an toàn, tạo split theo nhóm filename và chọn common-20 từ ViSignLanguage-Video.
- Chế độ **Thu dữ liệu AI** dùng riêng 30 nhãn bán hàng `sales-30` cộng lớp negative, không phụ thuộc danh sách output của model `common-20` đang chạy.
- Thu dữ liệu có phiên **Tự động**: đếm ngược, quay 2,1 giây, kiểm tra tối thiểu 8/16 frame tay, tự lưu và chuyển lượt; tự dừng khi đủ quota của tay đang chọn hoặc khi lưu lỗi.
- Quota `sales-30` mặc định là 50 mẫu tay phải và 50 mẫu tay trái cho mỗi từ. Kế hoạch scale-up V5/common-20 cũ được giữ làm tài liệu legacy và không quyết định quota của bộ mới.
- Mỗi mẫu thu có thể gắn khoảng cách, ánh sáng và loại hành động negative; pipeline frozen-camera báo cáo riêng theo từng điều kiện.
- Chế độ **Tự động (beta)** chỉ khởi động sau nhiều frame có landmark bàn tay thật, lọc rung bằng cửa sổ trung vị, chuẩn hóa chuyển động theo thời gian để ổn định ở 15–30 FPS, giữ pre-roll/post-roll theo mili giây và chờ trạng thái nghỉ trước khi nhận từ tiếp theo. Pose cổ tay/khuỷu chỉ duy trì một ký hiệu đã bắt đầu khi tay bị che, không còn tự kích hoạt clip chỉ có cơ thể; người dùng vẫn xác nhận trước khi thêm từ.

“Giữ để ký” vẫn là luồng kiểm soát tốt nhất. “Tự động” là beta vì lớp idle hiện mới bao phủ trạng thái đứng yên ở biên clip, chưa đủ các cử động đời thường như chỉnh tóc/kính hoặc quay người.

Phân tích regression V3/V4.2 và số liệu trước/sau sửa nằm tại
[`docs/V3_V4_2_REGRESSION.md`](docs/V3_V4_2_REGRESSION.md). Quy trình paired
release gate nằm tại [`docs/FROZEN_CAMERA_EVAL.md`](docs/FROZEN_CAMERA_EVAL.md).
Kế hoạch dữ liệu candidate tiếp theo nằm tại
[`docs/V5_DEVELOPMENT.md`](docs/V5_DEVELOPMENT.md).

## Kiến trúc

```text
apps/web                 camera → MediaPipe → V3 demo / V4.2 + V5 experimental → UI
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

### Thu mẫu webcam để cải thiện AI

`./scripts/run_onnx_local.sh` bật sẵn chế độ thu dữ liệu local. Trên web, chọn
**Thu dữ liệu AI**, chọn một nhãn `sales-30` và tay thực hiện, quay một lượt rồi
bấm **Lưu mẫu vào máy**. Mỗi mẫu tạo một MP4 `224×224` và một JSON metadata tại:

```text
ml/data/collected/sales30/<tu>/<right|left>/
```

Mục tiêu mặc định là 50 mẫu tay phải và 50 mẫu tay trái cho mỗi từ, tổng cộng
3.000 mẫu positive. Lớp `Không ký hiệu` được thu riêng và không thuộc 30 nhãn.
Mẫu chỉ tồn tại trong bộ nhớ cho đến khi người dùng bấm lưu; nút **Bỏ mẫu**
không tạo tệp. Thư mục thu thập bị Git ignore.

### Model common-20 legacy và lần train sales-30

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

Sau khi health check đạt, mở `http://localhost:8080`. Dừng bằng `Ctrl+C`, sau đó `docker compose down` nếu cần xóa container/network do Compose tạo.

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
| `INFERENCE_BACKEND` | `mock` | `mock`, `pytorch` hoặc `onnx` |
| `MODEL_VERSION` | `mock-common-20-v1` | Phiên bản trả trong response/metadata |
| `ONNX_MODEL_PATH` | rỗng | Model bắt buộc khi backend là ONNX |
| `PYTORCH_MODEL_PATH` | rỗng | Checkpoint bắt buộc khi backend là PyTorch |
| `PYTORCH_DEVICE` | `auto` | `auto`, `cpu` hoặc `cuda`; không dùng MPS |
| `LABEL_MAP_PATH` | rỗng | JSON/CSV theo đúng output index của model |
| `LABELS_VERIFIED` | `false` | Chỉ đặt `true` sau khi mapping đã được xác minh |
| `CONFIDENCE_THRESHOLD` | `0.70` | Reject top-1 thấp |
| `MARGIN_THRESHOLD` | `0.15` | Reject margin top1–top2 thấp |
| `ALLOWED_ORIGINS` | localhost `5173`, `8080` | Origin HTTP/WebSocket được phép |
| `MAX_FRAME_BYTES` | `262144` | Giới hạn bytes sau decode cho mỗi frame |
| `MAX_MESSAGE_BYTES` | `6291456` | Giới hạn toàn bộ WebSocket message |
| `COLLECTION_ENABLED` | `false` | Cho phép API/UI lưu mẫu webcam có xác nhận |
| `COLLECTION_DIR` | `ml/data/collected/sales30` | Thư mục local chứa MP4 và metadata của bộ mới |
| `COLLECTION_TARGET_PER_HAND` | `50` | Mục tiêu số mẫu cho mỗi từ và mỗi tay |
| `VITE_INFERENCE_WS_URL` | `ws://localhost:8000/ws/inference` | WebSocket URL lúc Vite build/start |
| `VITE_INFERENCE_HTTP_URL` | `http://localhost:8000` | Metadata URL lúc Vite build/start |

Vite đọc biến từ shell hoặc `apps/web/.env.local`. Docker Compose đọc `.env` ở root và truyền URL frontend thành build args. Không đặt secret vào file env được commit.

## Runtime ONNX tùy chọn

Sau khi checkpoint ViSignLanguage common-20 đã được train, đánh giá và export:

```bash
.venv/bin/pip install -e 'services/inference[onnx,test]'
./scripts/run_onnx_local.sh
```

Script mặc định đọc gói đã xác minh tại
`ml/artifacts/visignlanguage_common20/`. Giữ `model.onnx` và
`model.onnx.data` cạnh nhau vì file `.data` chứa trọng số của mô hình.

Adapter yêu cầu một input float `[1,C,T,H,W]` và một logits output float `[1,num_classes]`; dtype, rank, dimension cố định và số class được kiểm tra ngay khi khởi động. Preprocess dùng RGB, 16 frame `224×224`, ImageNet normalization, softmax và top 3. Với CSV, thứ tự dòng phải đúng thứ tự output của model; `source_class_id` vẫn được giữ làm ID nguồn chính thức và không bị giả định là số liên tiếp. Với JSON có thể dùng array theo output index hoặc object có key index liên tiếp từ 0. Service fail-fast nếu artifact, label map, interface output hoặc runtime không hợp lệ.

## Camera và quyền riêng tư

`getUserMedia` chỉ hoạt động trong secure context: `localhost` được phép khi phát triển; mọi hostname/IP khác cần HTTPS. Ứng dụng không dùng `MediaRecorder`, không ghi frame/base64 vào console hoặc telemetry, không lưu video ở chế độ nhận dạng và giải phóng `ImageBitmap`/canvas/MediaStreamTrack sau khi dùng. Khi landmark V4 sẵn sàng, chế độ nhận dạng chỉ dùng tọa độ tay/thân trên trong bộ nhớ browser và không gửi ảnh lên server. Trong chế độ **Thu dữ liệu AI**, 16 frame chỉ được ghi thành MP4 local sau thao tác xác nhận **Lưu mẫu vào máy**; metadata không chứa base64.

## Việc còn lại trước public demo dịch ra tiếng Việt

- Dataset mới đã có license CC BY 4.0 và mapping 100 nhãn tiếng Việt; cần giữ attribution khi phát hành.
- Nguồn không có signer ID, nên split local không chứng minh khả năng tổng quát hóa sang người ký chưa thấy.
- Đã có idle biên clip nhưng chưa có đủ negative đời thường; auto mode vẫn beta và bắt buộc bước xác nhận.
- Landmark V4 mới được kiểm định với một người ký trong cùng buổi; cần bộ camera đóng băng nhiều khoảng cách/ánh sáng và người ký mới để đo generalization.
- Đã benchmark ONNX và thấy tracking khoảng 15 FPS với camera hiện tại; vẫn cần đo end-to-end P50/P95/cold start trên nhiều thiết bị.
- Cần benchmark/tinh chỉnh motion gate tự động với nhiều tốc độ ký và thiết bị camera hơn.

Không commit video, dataset, checkpoint, model binary, credential hay generated build output. Xem [PROJECT_PLAN.md](PROJECT_PLAN.md), [docs/VISIGNLANGUAGE_VIDEO.md](docs/VISIGNLANGUAGE_VIDEO.md) và [docs/AI_RUNTIME.md](docs/AI_RUNTIME.md) để biết lộ trình, nơi train/inference và điều kiện go/no-go.
