# Sales30 seated-v3 trên Kaggle

Gói này chứa dữ liệu người quay riêng tư. Tạo **Kaggle Dataset private**, không
publish video hay checkpoint. Không cần attach lại VSL-472 vì gói đã có đúng
1.760 clip đứng đã được ghim checksum và giữ nguyên split cũ.

## Đầu vào

| Nguồn | Train | Validation | Test | Tổng |
| --- | ---: | ---: | ---: | ---: |
| Đứng, giữ nguyên | 1.265 | 144 | 351 | 1.760 |
| Ngồi, hai đợt | 1.160 | 600 | 0 | 1.760 |
| Tổng | 2.425 | 744 | 351 | 3.520 |

HA: 600 clip, Nhi: 560 clip, Như: 600 clip. HA/Nhi vào train, Như vào validation.
Nhi thiếu 27 **Cung cấp**, 28 **Thay đổi**; không có mẫu giả/thay thế. Mọi lớp đều
có mẫu train/validation/test nhờ dữ liệu đứng và các signer còn lại.

## Chuẩn bị lại tại máy local

Chạy từ root repository VSign:

```bash
.venv/bin/python -m ml.scripts.prepare_sales30_seated_v3
```

Đầu ra mặc định:

```text
artifacts/sales30_seated_v3_kaggle/
  vsign_sales30_seated_v3.zip
  sales30_seated_v3.ipynb
  README_KAGGLE.md
  bundle_report.json
  SHA256SUMS.txt
```

Nếu đã có ZIP, chọn `--output-dir artifacts/sales30_seated_v3_kaggle_r2`; không
ghi đè gói cũ. Manifest và audit tại `ml/data/combined/sales30_seated_v3/` chỉ
được dùng lại nếu nội dung giống hệt; dữ liệu thay đổi cần version mới.

Script kiểm tra nhãn/id, SHA256 của mọi clip, group/hash leakage giữa split,
coverage theo người và checkpoint khởi tạo. Nó chỉ đóng gói allowlist, không
copy `.env`, frontend/backend, video nguồn hoặc checkpoint `last.pt` cũ.

## Chạy trên Kaggle

1. Upload ZIP thành Dataset **private** và attach vào notebook.
2. Import `sales30_seated_v3.ipynb`, chọn accelerator GPU; bật Internet cho
   cell cài PyAV/PyYAML/Pillow nếu chúng chưa có.
3. Chạy các cell setup, dependencies và smoke. Setup hỗ trợ cả ZIP nguyên tệp
   và thư mục Kaggle đã tự giải nén, không hardcode owner/slug của dataset.
4. Kiểm tra `bundle_verified`, `manifest_ready` với 3.520 dòng và
   `gpu_smoke_ok` với input `[1,3,16,224,224]`, output `[1,30]` hữu hạn.
5. Khi chủ động bắt đầu training, chạy cell train; cuối cùng tải ZIP kết quả
   hoặc Save Version với output. Lưu run ở `/kaggle/working/runs/sales30-seated-v3/`.

Notebook là các cell Python hoàn chỉnh, không cần clone repo hoặc token Kaggle.
Giữ torch/torchvision CUDA được Kaggle cài sẵn, không dùng `ml/requirements.txt`
cũ để hạ phiên bản chúng. Model dùng `pretrained=False` rồi nạp **state_dict**
từ `baseline/training/best.pt` (seated-v2 best epoch 5); optimizer/scheduler/
scaler/history đều mới. Run mặc định 6 epoch, lr `2e-5`, batch 2, accumulation 4.

Lệnh tương đương, sau khi notebook đã setup vào working:

```bash
python /kaggle/working/VSign-seated-v3/tmp/train_sales30_seated.py \
  --root /kaggle/working/VSign-seated-v3 \
  --dataset-version seated-v3 \
  --baseline /kaggle/working/VSign-seated-v3/baseline/training/best.pt \
  --output-dir /kaggle/working/runs/sales30-seated-v3 \
  --drive-output-dir /kaggle/working/runs/sales30-seated-v3 \
  --epochs 6 --learning-rate 2e-5 --batch-size 2 --num-workers 2
```

Không có auto-resume cho v3. Run không rỗng sẽ dừng; muốn tiếp tục phải dùng
`--resume /kaggle/working/runs/sales30-seated-v3/last.pt` và có `best.pt`,
`run_identity.json` cùng thư mục. Resume phải khớp version, manifest hash,
baseline hash, labels và epochs/lr; best epoch/score phải khớp history của
last.pt. Mọi output không rỗng phải có cùng run identity. Không thay schedule
khi resume và không dùng checkpoint v2.

## Giới hạn bằng chứng

- Đây là cùng ba người đã quay đợt 9 từ, không phải ba signer mới.
- Như đã dùng để chọn model seated-v2. Validation v3 là dữ liệu phát triển,
  không phải tập đánh giá người hoàn toàn chưa thấy hoặc seated test độc lập.
- Validation mới có 744 clip, không so trực tiếp với điểm cũ trên 324 clip:
  phải đánh giá v2 và v3 trên cùng tập cố định để kết luận cải thiện.
- Giữ nguyên 351 standing test; chọn epoch bằng validation macro-F1, không
  dùng test để tune. Script đánh giá standing test sau khi chọn best epoch.
- Chưa có bằng chứng CUDA/training/camera mới chỉ vì đóng gói local thành công.
- Không đổi runtime, export/ghi đè ONNX cũ hoặc công bố production acceptance.
  Sau training, kiểm tra theo từng từ và camera A/B cố định trước khi triển khai.
