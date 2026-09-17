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
