# Trạng thái quyền truy cập Multi-VSL

Ngày cập nhật: 2026-09-10

## Điều đã được xác nhận

- Chủ dự án xác nhận nhóm tác giả đã cho phép sử dụng Multi-VSL.
- VSign tạm coi xác nhận này là đủ để **lưu private, train và đánh giá nội bộ**.
- Không suy diễn thêm quyền công khai video, phân phối lại dataset/checkpoint/model fine-tune hoặc dùng thương mại nếu văn bản cấp quyền chưa nêu rõ các phạm vi đó.

## Artifact hiện nhìn thấy

Tài khoản Google Drive đã đăng nhập chỉ nhìn thấy thư mục `Videos_demo`. Thư mục này khớp bộ đã nhập local:

- 50 video MP4.
- 47 class ID khác nhau.
- 2 signer (`01`, `02`).
- 12 video center, 21 left và 17 right.

Đây là demo/partial set, không phải full set 84.764 video. Chưa nhìn thấy:

1. Link/thư mục chứa full video.
2. Glossary chính thức `class_id 0–999 → gloss/từ tiếng Việt`.
3. Văn bản hoặc tóm tắt phạm vi cấp quyền để xác định quyền public demo/redistribution.

## Đường dẫn private quy ước

Khi có artifact, đặt hoặc mount tại:

```text
ml/data/private/multivsl/videos/
ml/data/private/multivsl/gloss_map.csv
ml/data/private/multivsl/authorization/
```

Toàn bộ `ml/data/private/` đã được Git ignore.

## Import và kiểm tra

Bộ demo hiện tại đã được đối chiếu bằng:

```bash
.venv/bin/python -m ml.scripts.import_multivsl \
  --annotations ml/vendor/Multi-VSL_WACV_2025/data/label_1_1000 \
  --videos ml/data/raw/official-sample \
  --output ml/data/raw/official-sample-manifest.csv \
  --allow-partial
```

Khi nhận full set, chạy strict import, **không** dùng `--allow-partial`:

```bash
.venv/bin/python -m ml.scripts.import_multivsl \
  --annotations ml/vendor/Multi-VSL_WACV_2025/data/label_1_1000 \
  --videos ml/data/private/multivsl/videos \
  --output ml/data/manifests/generated/multivsl-1000.csv

.venv/bin/python -m ml.scripts.validate_gloss_map \
  ml/data/private/multivsl/gloss_map.csv

.venv/bin/python -m ml.scripts.audit_manifest \
  ml/data/manifests/generated/multivsl-1000.csv \
  --data-root ml/data/private/multivsl/videos
```

Strict import chỉ ghi manifest khi mọi video trong chín official split CSV đều có mặt, filename parse được và label trong filename khớp label trong CSV.
