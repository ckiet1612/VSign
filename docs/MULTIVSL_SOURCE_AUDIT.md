# Audit nguồn Multi-VSL

Ngày kiểm tra: 2026-09-10  
Repository: [Etdihatthoc/Multi-VSL_WACV_2025](https://github.com/Etdihatthoc/Multi-VSL_WACV_2025)  
Commit đã kiểm tra: `943eed8954f761e02e76b17b8b2322bb5243615c`

## Kết quả có thể sử dụng ngay

- CSV công khai mô tả `84.764` video, `1.000` class ID từ `0` đến `999`, và `30` signer.
- Official center-view split không bị signer leakage:
  - Train: `20.161` video, 21 signer, đủ 1.000 lớp.
  - Validation: `3.713` video, 4 signer, đủ 1.000 lớp.
  - Test: `4.538` video, 5 signer, đủ 1.000 lớp.
- Checkpoint MViTv2-S 1.000 class đã được VSign load và chạy đúng kiến trúc.
- Thông số nguồn khớp pipeline VSign: 16 frame, 224×224, ImageNet normalization, PyTorch 2.0.

Source snapshot được clone local tại `ml/vendor/Multi-VSL_WACV_2025` và bị Git ignore. Audit lặp lại bằng:

```bash
.venv/bin/python -m ml.scripts.audit_multivsl_source \
  ml/vendor/Multi-VSL_WACV_2025 \
  --output ml/data/raw/multivsl-source-audit.json
```

## Phần nguồn chưa cung cấp

- Không có bảng đầy đủ `class_id → gloss tiếng Việt/tiếng Anh` trong repository hoặc CSV annotation. Các CSV chỉ có filename và số label.
- Không có `LICENSE`, `LICENSE.md`, `LICENSE.txt` hoặc `COPYING` ở root repository.
- Google Drive được README gọi là “Video data” nhưng nội dung công khai là demo, không phải đủ 84.764 video. [Issue #1 - Full dataset release](https://github.com/Etdihatthoc/Multi-VSL_WACV_2025/issues/1) vẫn chưa có phản hồi từ tác giả tại thời điểm audit.
- Supplementary PDF chỉ nêu một số ví dụ rời rạc: `#1 grass`, `#3 grandparent`, `#134 chance`, `#183 unfamiliar`, `#199 brush one's teeth`, `#359 pass the ball`, `#519 yam`, `#700 mane of hair`. Đây không phải glossary đầy đủ và không đủ để chọn 20 từ demo.

Ngày 2026-09-10, chủ dự án xác nhận nhóm tác giả đã cho phép sử dụng. Kiểm tra Drive đã đăng nhập vẫn chỉ thấy `Videos_demo` gồm 50 video/47 class ID; chưa thấy full video hoặc glossary. Chi tiết và lệnh strict import nằm tại [MULTIVSL_ACCESS_STATUS.md](MULTIVSL_ACCESS_STATUS.md).

## Quyết định kỹ thuật

1. Giữ checkpoint hiện tại cho kiểm thử class ID và đo domain shift.
2. Không tự dịch hoặc đoán nghĩa của 1.000 class ID.
3. Không fine-tune “20 từ thông dụng” trước khi tác giả cung cấp glossary và full dataset.
4. Không phân phối lại checkpoint/video hoặc public demo trước khi xác nhận license/DUA.
5. Dùng official split theo signer thay vì tự random video.

Email/yêu cầu truy cập đã được chuẩn bị tại [MULTIVSL_ACCESS_REQUEST.md](MULTIVSL_ACCESS_REQUEST.md).
