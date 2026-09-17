# Train sales-30 miễn phí trên Kaggle

Full MViTv2-S training cần CUDA và được thiết kế chạy trên Kaggle Notebook miễn
phí. Dataset đầu vào là
`nguyenanfms/vsl-vietnamese-sign-language-v2`, version `8`, CC BY 4.0.

1. Tạo Kaggle Notebook mới và chọn accelerator GPU.
2. Attach dataset `VSL - Vietnamese Sign Language (Cropped)`, version `8`.
3. Upload hoặc clone repository VSign vào notebook.
4. Bật Internet cho lần đầu tải Kinetics-400 pretrained weights.
5. Chạy từ root repository:

```bash
pip install -r ml/requirements.txt
python -m ml.scripts.run_sales30_kaggle \
  --epochs 12 \
  --batch-size 2 \
  --num-workers 2
```

Dataset attach tại `/kaggle/input` là read-only và không cần Kaggle token trong
notebook. Runner tự tìm canonical tree, giữ nguyên source test, tạo validation
từ source train, train bằng CUDA, đánh giá test đúng một lần và export vào:

```text
/kaggle/working/vsign-sales30-artifacts/
```

Tải toàn bộ thư mục output về sau khi hoàn tất. Các file chính gồm `model.onnx`,
`labels.json`, `test_metrics.json`, `training/best.pt` và
`artifact_manifest.json`. Kết quả vẫn là `development-only` vì dataset không có
signer ID đầy đủ; chưa được xem là production release gate.
