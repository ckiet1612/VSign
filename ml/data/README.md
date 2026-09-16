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
