# Development set V5

Mục tiêu V5 chỉ còn hai vấn đề camera đã quan sát:

- `Ăn` và `Nói` thường đúng nhưng confidence/margin thấp;
- `Uống` khó nhận và nhầm với `Ăn` hoặc `Trường học`.

Các từ còn lại không cần quay lại. V3 đã học từ 207 clip cũ của đủ 20 từ được
khóa nguyên vẹn trong V5 để tránh làm hỏng các lớp đang ổn.

## V5 bootstrap đã hoàn thành

Candidate `guarded-landmark-v5-bootstrap` đã được train và gắn vào nút
**V5 thử nghiệm** trên web. V3 vẫn là runtime demo mặc định.

- Input `16 × 185`: nguyên khối V3 `128` feature + `57` feature ngữ cảnh thân
  trên của V4;
- toàn bộ trọng số V3 bị khóa;
- nhánh ngữ cảnh chỉ được sửa logits của `Uống`, `Ăn`, `Trường học`, `Nói`,
  `Đâu`, tối đa `±1,25`;
- nếu thiếu pose hai vai, hoặc V3 đang chọn một trong 15 từ ổn, output V5 bằng
  đúng output V3;
- bootstrap dùng 207 clip development local đã có. Không dùng frozen camera,
  public test hay 84 clip sắp thu.

Trên split development 41 clip, V3 và V5 đều đạt top-1 100%. Xác suất đúng
trung bình của 5 từ mục tiêu tăng từ 91,51% lên 93,56%; xác suất của 15 từ ổn
giữ nguyên 94,73%. Đây chỉ là kiểm tra bảo vệ regression trên dữ liệu đã biết,
không phải kết quả release và không thay thế A/B camera độc lập.

Tái tạo candidate trên Mac CPU:

```bash
.venv/bin/python -m ml.scripts.train_landmarks_v5
```

Artifact nằm ở `ml/artifacts/landmark_v5/`; bản ONNX cho browser nằm ở
`apps/web/public/models/vsign-landmark-v5.onnx`.

## Mở rộng lên 100 video thật mỗi từ

Quota mới được tính theo công thức:

```text
public train + public validation + webcam local = 100 video / từ
```

Public `test` không được tính và không bao giờ đi vào extractor/train. Extractor
đã đọc 889 video public train/validation; 14 clip không có bất kỳ frame nào
phát hiện được bàn tay nên bị loại khỏi train và quota. Cùng 207 video webcam
local, mỗi từ hiện có 27–76 video hợp lệ; còn thiếu tổng cộng **918 video** để
đủ đúng 100 cho cả 20 từ.

Lịch đầy đủ nằm tại
`ml/data/development/v5/capture_plan_100_each.csv`. Target hiển thị trên web
khác nhau theo từng từ/tay vì đã trừ phần public hiện có. Có thể tạo lại lịch
sau một đợt thu bằng:

```bash
.venv/bin/python -m ml.scripts.generate_v5_scaleup_plan --force
```

Không nhân bản một clip nhiều lần để gọi là 100 video. Data augmentation chỉ
được dùng trong train và không làm tăng bộ đếm video thật.

## Thu liên tục không cần giữ nút

1. Chạy backend bằng `./scripts/run_onnx_local.sh`, mở web và bật camera.
2. Vào **Thu dữ liệu AI**, chọn từ, tay, khoảng cách và ánh sáng.
3. Bấm **Tự động beta** một lần.
4. Mỗi lượt web đếm ngược 3–2–1, quay 2,1 giây, kiểm tra có đủ hình tay rồi tự
   lưu local. Sau khi lưu, lượt kế tiếp tự bắt đầu.
5. Chỉ ký một lần khi hiện “Đang quay”; giữ tay nghỉ giữa hai lượt.
6. Chuyển về **Giữ để quay mẫu** để dừng. Phiên cũng tự dừng khi tay đang chọn
   đạt quota, để tránh ghi thừa và cho phép đổi tay/từ.

Một lượt có dưới 8/16 frame tay bị loại tự động và quay lại; negative
`Không ký hiệu` không áp dụng điều kiện này. Nếu lưu lỗi, phiên dừng thay vì
gửi lặp. Khi đang chạy tự động, nhãn/tay/điều kiện bị khóa để metadata không
đổi giữa một lượt.

Nên thu theo block 8–12 lượt rồi chủ động đổi khoảng cách hoặc ánh sáng. Không
đánh dấu “xa/thiếu sáng” nếu điều kiện thực tế chưa thay đổi.

## Lịch thu tập trung cũ

`ml/data/development/v5/capture_plan.csv` có 84 lượt:

- Uống: 18;
- Ăn, Nói, Trường học: 12 mỗi từ;
- Đâu: 6 hard-negative cho lỗi hút nhãn;
- Không ký hiệu: 24, đủ 8 loại hành động negative.

Mỗi cụm phủ tay trái/phải, gần/chuẩn/xa, ba điều kiện sáng và tốc độ tự nhiên,
hơi chậm, hơi nhanh. Thực hiện trọn động tác, không cố bắt chước “hoàn hảo”.

Đây là **development data**, được phép dùng train V5. Nó hoàn toàn tách khỏi
`ml/data/evaluation/frozen_camera_v4`; không sao chép clip giữa hai nơi.

## Thu dữ liệu tập trung cũ

Từ root repo, chạy backend bằng thư mục riêng:

```bash
COLLECTION_ENABLED=true \
COLLECTION_DIR=ml/data/development/v5/raw \
COLLECTION_TARGET_PER_HAND=9 \
PYTHONPATH="services/inference:." \
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Mở web, vào **Thu dữ liệu AI** và làm theo cột `order`. Kiểm tra tiến độ:

```bash
PYTHONPATH=. .venv/bin/python -m ml.scripts.audit_frozen_camera_capture \
  --plan ml/data/development/v5/capture_plan.csv \
  --raw-dir ml/data/development/v5/raw
```

Lịch 84 lượt này được giữ để truy vết thí nghiệm trước. Run scale-up hiện tại
dùng lịch 918 lượt ở trên.

## Trích feature và train sau khi đủ quota

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

Train script bỏ clip trùng path, mặc định loại clip supplement có 0 frame tay
và từ chối chạy nếu còn bất kỳ từ nào dưới 100. Sau train phải A/B V3/V5 trên
cùng clip camera khóa, tách riêng Giữ để ký và Tự động. V5 không được thành mặc
định nếu không vượt V3 theo release gate.
