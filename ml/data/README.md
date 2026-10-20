# Dữ liệu VSign

Nguồn train chính là
[`star092304/ViSignLanguage-Video`](https://huggingface.co/datasets/star092304/ViSignLanguage-Video),
revision `906306d7cc9c684b034bc8e96494ce9a99bc1bfc`, license được khai báo
CC BY 4.0. Không commit video, dữ liệu camera hoặc model artifact. `raw/`,
`private/`, cache, video và checkpoint đều bị `.gitignore` loại trừ.

Chuẩn bị dữ liệu bằng pipeline đã ghim checksum:

```bash
.venv/bin/hf download star092304/ViSignLanguage-Video dataset.zip \
  --local-dir ml/data/raw/visignlanguage-video
.venv/bin/python -m ml.scripts.prepare_visignlanguage_video \
  --archive ml/data/raw/visignlanguage-video/dataset.zip \
  --metadata ml/vendor/ViSignLanguage-Video/dataset_metadata.csv \
  --output-root ml/data/raw/visignlanguage-video
```

Các đầu ra chính:

- `raw/visignlanguage-video/manifest.csv` và `label_map.json`: toàn bộ 100 lớp.
- `raw/visignlanguage-video/common20_manifest.csv` và
  `common20_label_map.json`: 20 từ demo, output ID `0..19`.
- `raw/visignlanguage-video/audit.json` và `common20_audit.json`: checksum,
  thống kê split và kiểm tra group leakage.
- `raw/visignlanguage-video/dataset/`: video giải nén an toàn, tên thư mục được
  chuẩn hóa Unicode NFC.

`dataset_metadata.csv` chỉ được dùng cho FPS, số frame, kích thước và thời
lượng; 828 dòng label trong CSV bị lỗi Unicode. Label chuẩn lấy từ thư mục video
và `label_mapping.pkl` qua restricted unpickler. Nguồn không có signer ID, vì
vậy split hiện tại chỉ được gọi là group-safe, không phải signer-independent.

Các schema trong `templates/` và công cụ import Multi-VSL được giữ để tái lập
baseline legacy; chúng không phải đầu vào train của model common-20 mới. Xem
`docs/VISIGNLANGUAGE_VIDEO.md` để biết audit và attribution đầy đủ.

## Sales-30 từ VSL-472 công khai

Model sales-30 mới chỉ dùng dataset Kaggle công khai
`nguyenanfms/vsl-vietnamese-sign-language-v2`, version `8`, license CC BY 4.0.
Pipeline chỉ tải cây video canonical
`processed/processed/frame_splited/{train,test}/{label}`; không dùng Multi-VSL,
raw videos hay dữ liệu augmented.

```bash
.venv/bin/python -m ml.scripts.audit_sales30_sources
.venv/bin/python -m ml.scripts.download_sales30_sources \
  --audit ml/data/raw/sales30/source_audit.json \
  --output-root ml/data/raw/sales30
.venv/bin/python -m ml.scripts.build_sales30_manifest \
  --output-root ml/data/raw/sales30
.venv/bin/python -m ml.scripts.audit_sales30_manifest \
  ml/data/raw/sales30/manifest.csv \
  --data-root ml/data/raw/sales30/media
```

`download_index.json` ghim SHA256 cho từng clip. `manifest.csv` giữ nguyên source
test và tách validation ổn định từ source train. Do nguồn không có signer ID đầy
đủ, `readiness.json` luôn đánh dấu split là `development-only`; đây là baseline
train, chưa phải bằng chứng production.

## Video ngồi: 21 từ còn lại

Script `ml/scripts/split_seated_sales30.py` nhận ZIP có thư mục người quay,
khôi phục tên UTF-8 bị ZIP đánh dấu sai encoding và bỏ qua `__MACOSX`/resource
fork. Nhãn được đối chiếu với `contracts/v1/sales30.labels.json`; số thứ tự
`10..30` phải khớp tên từ. Các tên viết liền, có dấu/gạch nối, `tv` và `cafe`
đều được hỗ trợ. `Hoài Anh` được quy về signer ID `HA`, không phải người mới.

Chạy tại thư mục gốc VSign, kiểm tra dữ liệu trước:

```bash
.venv/bin/python -m ml.scripts.split_seated_sales30 \
  --source-zip '/Users/macbook/Downloads/21 từ còn lại.zip' \
  --audit-only
```

ZIP hiện có 61 video: HA 21, Nhi 19, Như 21. `coverage.json` ghi rõ Nhi thiếu
27 **Cung cấp** và 28 **Thay đổi**; không tạo mẫu thay thế. Với 20 lần lặp mỗi
video, số clip dự kiến là 1.220. Kiểm tra mốc cắt mà chưa encode:

```bash
.venv/bin/python -m ml.scripts.split_seated_sales30 \
  --source-zip '/Users/macbook/Downloads/21 từ còn lại.zip' \
  --dry-run
```

Nếu đã có báo cáo `dry_run/`, thêm `--force` để chạy lại bước này; nó chỉ ghi
lại báo cáo thử, không ghi đè clip thật ở thư mục đầu ra chính.

Tách toàn bộ:

```bash
.venv/bin/python -m ml.scripts.split_seated_sales30 \
  --source-zip '/Users/macbook/Downloads/21 từ còn lại.zip'
```

Đầu ra mặc định nằm ở `ml/data/collected/sales30_seated_remaining21/`:

- `clips/<nhãn>/<người>_rep01.mp4` đến `rep20.mp4`: H.264/yuv420p, không audio.
- `manifest.csv`: người, nhãn, SHA256 nguồn/clip, timestamp, kích thước và filter xoay.
- `video_reports.json`: mốc cắt và thời lượng từng video.
- `coverage.json`: số video theo người, nhãn và từ thiếu.
- `summary.json`: số video/clip và cấu hình lần chạy.
- `dry_run/`: manifest/timestamp thử, tách riêng khỏi kết quả encode.

Video nguồn giải nén nằm trong thư mục cùng cấp
`sales30_seated_remaining21_sources/`; ZIP gốc không thay đổi. Cache nguồn chỉ
được dùng lại khi nội dung trùng ZIP. Không xuất ZIP vào thư mục seated cũ,
không ghi đè clip/báo cáo sẵn có trừ khi chủ động dùng `--force`. Khi đổi cấu
hình nên dùng `--output-root` mới; `--force` không xóa các clip ngoài manifest.
Không ghi qua symlink, kể cả khi dùng `--force`. Báo cáo coverage từ lần audit
chỉ được dùng lại không ghi đè nếu nội dung khớp lần chạy tiếp theo.

Hoài Anh mặc định xoay pixel 90 độ ngược kim đồng hồ về khung ngang. Đổi sang
`--ha-rotation cw` nếu preview cần chiều ngược lại. Nhi/Như được xoay theo
metadata của từng video, không áp dụng cấu hình đợt trước; clip xuất có rotation
metadata bằng 0. Với `--source-root`, chế độ mặc định vẫn là `legacy`; dùng
`--orientation-mode metadata` khi xử lý thư mục của đợt mới. Có thể giới hạn
thử nghiệm bằng `--person HA --limit 1 --output-root <thư-mục-mới>`.

`--repetitions` mặc định 20. Đây là **giả định số lần thực hiện**, không phải bộ
đếm ký hiệu: thuật toán chọn các điểm ít chuyển động và xuất đúng số đoạn yêu
cầu. Nếu bản gốc không có đúng 20 lần, cần sửa tham số hoặc mốc cắt. Phải xem
lại clip để kiểm tra chiều quay và động tác đầy đủ trước khi dùng để train.
Script này không chia train/test, không thay model và không chứng minh chất
lượng nhận dạng hay khả năng tổng quát hóa sang người ký mới.

## Chuẩn bị seated-v3 cho Kaggle

Sau khi đã xem lại clip của cả hai đợt, chạy:

```bash
.venv/bin/python -m ml.scripts.prepare_sales30_seated_v3
```

Script gộp 540 clip ngồi cũ, 1.220 clip mới và 1.760 clip đứng thành
`combined/sales30_seated_v3/manifest.csv` cùng `audit.json`. Train 2.425,
validation 744, standing test 351 giữ nguyên. HA/Nhi train, Như validation;
Nhi vẫn thiếu Cung cấp/Thay đổi. Mỗi clip được kiểm tra SHA256; group/hash
không được đi qua hai split. Manifest v2 và clip gốc không thay đổi.

ZIP, notebook và báo cáo nằm trong `artifacts/sales30_seated_v3_kaggle/` ở
root repo. Gói chỉ chứa allowlist cần cho fine-tune, lấy trọng số khởi tạo từ
`ml/artifacts/sales30_seated_v2/training/best.pt`, không nạp optimizer cũ và
không tự resume `last.pt`. Upload thành Kaggle Dataset **private**. Hướng dẫn
và các cell đầy đủ ở `ml/notebooks/SALES30_SEATED_V3_KAGGLE.md` và
`ml/notebooks/sales30_seated_v3.ipynb`.

Chuẩn bị riêng manifest mà không đóng ZIP:

```bash
.venv/bin/python tmp/train_sales30_seated.py --root "$PWD" \
  --dataset-version seated-v3 --prepare-only
```

Đây vẫn là dữ liệu phát triển: Như đã dùng cho validation seated-v2 và dữ liệu
đứng thiếu signer ID đầy đủ. Không đổi model runtime trước khi đánh giá v2/v3
trên cùng dữ liệu camera cố định. Bước chuẩn bị không thực hiện training.
# Đợt thu cá nhân personal-100

Web thu tự động 100 mẫu/từ bằng tay thuận; đợt mới nằm riêng tại
`ml/data/collected/sales30/batches/personal-100/`. Tiến độ chỉ tính clip đã lưu
của đợt này, không cộng hoặc thay thế mẫu legacy/seated/standing.
Metadata giữ `expected_label`, tay, điều kiện quay, `session_id` và mã lượt thu.
Nhãn do người thu chọn; không đợi model đoán đúng mới lưu. Không auto fine-tune
hoặc auto chia các lượt liên tiếp vào train/validation/test. Khi chuẩn bị train,
audit clip/nhãn và chọn split theo buổi/người ký, giữ dữ liệu test cũ ngoài train
và lưu model candidate riêng. Cơ chế chống trùng dựa trên `sample_key` và hash
payload; lỗi lưu tạm dừng, không tự retry. Dữ liệu thu không commit vào Git.
