# Nguồn chính: ViSignLanguage-Video

Ngày chuyển nguồn: 2026-09-10  
Hugging Face: [star092304/ViSignLanguage-Video](https://huggingface.co/datasets/star092304/ViSignLanguage-Video)  
Revision đã audit: `906306d7cc9c684b034bc8e96494ce9a99bc1bfc`  
License khai báo: `CC-BY-4.0`

## Trạng thái local

- `dataset.zip`: 824 MiB, SHA256 `cdfec1080e8b75cf10a972a4d7cf54fcfa4bf1b874002d28eae8405188a2a308`.
- Archive: 8.364 video MP4 và một `label_mapping.pkl` chỉ chứa primitive `str → int`.
- Train có nhãn: 3.875 video, 100 từ, 2.806 nhóm video gốc.
- Public test: 1.630 video không có nhãn.
- Private test: 2.859 video không có nhãn.
- Độ phân giải train được công bố: 224×224; mỗi clip thường có 16–30 frame.
- Common-20: 989 video, gồm 799 train, 90 validation và 100 test.

Các artifact dữ liệu nằm ở `ml/data/raw/visignlanguage-video/` và bị Git ignore.

## Common-20

Danh sách theo đúng output index của model:

1. Chào
2. Cảm ơn
3. Xin lỗi
4. Tôi
5. Đi
6. Uống
7. Ăn
8. Nhà
9. Trường học
10. Bệnh viện
11. Giúp
12. Đồng ý
13. Nói
14. Nghe
15. Mua
16. Đâu
17. Nhìn
18. Cho
19. Biết
20. Có thể

Nguồn đã có nhãn tiếng Việt trực tiếp, nên không còn blocker glossary như Multi-VSL.

## Audit và xử lý lỗi nguồn

- Checksum local khớp SHA256 do Hugging Face công bố.
- ZIP không có absolute path, `..` path traversal hoặc symlink.
- Trình `unzip` mặc định trên macOS làm hỏng tên thư mục tiếng Việt. Pipeline dùng Python `zipfile`, chuẩn hóa từng path segment về Unicode NFC và giải nén qua thư mục tạm.
- CSV `dataset_metadata.csv` có 828/3.875 dòng mà tên label bị lỗi Unicode, ví dụ `Bàn tay` thành `BÖn tay`. Filename vẫn duy nhất và đúng; pipeline lấy label chuẩn từ thư mục archive rồi đối chiếu với `label_mapping.pkl`. CSV chỉ cung cấp FPS, frame count, kích thước và duration.
- Pickle không được load bằng `pickle.load` thông thường. Restricted unpickler chặn toàn bộ global/class và sau đó chỉ chấp nhận dict `str → int` liên tiếp `0..99`.
- Các biến thể filename như `127824.mp4`, `127824_1.mp4`, `127824_2.mp4` luôn nằm cùng split để tránh leakage do augmentation/copy.
- Nguồn không cung cấp signer ID. Split 80/10/10 theo nhóm filename là split phát triển tái lập, không phải bằng chứng signer-independent.

## Tái tạo dữ liệu

```bash
.venv/bin/pip install -r ml/requirements.txt
.venv/bin/hf download star092304/ViSignLanguage-Video dataset.zip \
  --local-dir ml/data/raw/visignlanguage-video

.venv/bin/python -m ml.scripts.prepare_visignlanguage_video \
  --archive ml/data/raw/visignlanguage-video/dataset.zip \
  --metadata ml/vendor/ViSignLanguage-Video/dataset_metadata.csv \
  --output-root ml/data/raw/visignlanguage-video
```

Đầu ra:

```text
manifest.csv                 # 100 lớp
label_map.json               # 100 output labels
audit.json
common20_manifest.csv        # 20 lớp, label_id được remap 0..19
common20_label_map.json
common20_audit.json
dataset/                     # video đã giải nén
```

## Train và inference

- Train thử/smoke test: Google Colab GPU.
- Train chính: NVIDIA L4 trên Compute Engine tại Singapore; input 16 frame 224×224, khởi tạo từ Kinetics-400 và fine-tune 20 output.
- Inference local: Mac CPU để kiểm tra tích hợp, không dùng làm SLA.
- Inference demo: Cloud Run GPU L4 tại Singapore hoặc máy NVIDIA chạy Docker trong LAN.

Backend đang chạy tại thời điểm chuyển nguồn vẫn là checkpoint Multi-VSL 1.000 class. Nó được giữ làm baseline legacy; không đổi label map của checkpoint cũ sang 20 từ mới vì như vậy sẽ tạo kết quả sai. Chỉ chuyển UI/backend sang ViSignLanguage sau khi checkpoint common-20 đạt evaluation gate và được export.

## Attribution

Khi phát hành model/demo, ghi nguồn `star092304/ViSignLanguage-Video`, liên kết dataset trên Hugging Face và giữ thông báo license CC BY 4.0. Dataset card cho biết dữ liệu bắt nguồn từ AI Challenge CV của PTIT; cần giữ attribution này trong data card/model card.
