# Giai đoạn AI thật: Multi-VSL MViTv2-S

## Trạng thái hiện tại

VSign đã có backend `pytorch` chạy checkpoint **MViTv2-S 1–1000 class** từ repository chính thức [Multi-VSL WACV 2025](https://github.com/Etdihatthoc/Multi-VSL_WACV_2025). Luồng camera → 16 frame → FastAPI → model → top-3 đã chạy end-to-end.

Checkpoint local hiện dùng:

- File: `ml/artifacts/source/mvitv2_s_multivsl1000.pth` (không commit Git).
- SHA-256: `d186740b6ec37ffadae19001ab4d96efb8d048b029710fd82f804f82115398d0`.
- Kiến trúc: `torchvision.models.video.mvit_v2_s`, 1 view, 16 frame, 224×224, 1.000 output.
- Label hiện tại: `Ký hiệu #0000` … `Ký hiệu #0999`; đây là output index kỹ thuật, **không phải bản dịch tiếng Việt**.

Smoke test ngày 2026-09-10 trên Mac Apple Silicon CPU, 10 video từ sample công khai: top-1 `9/10`, top-5 `9/10`, compute latency trung bình `1.223 giây/clip`. Đây chỉ là kiểm tra tích hợp trên mẫu nhỏ, không phải accuracy chính thức hoặc đánh giá webcam thực tế.

## Chạy inference local

Yêu cầu Python 3.9–3.11 cho bộ dependency đã được kiểm chứng:

```bash
python3 -m venv .venv
.venv/bin/pip install -e 'services/inference[pytorch,test]'
.venv/bin/pip install -r ml/requirements.txt
.venv/bin/python -m ml.scripts.generate_class_id_labels \
  ml/artifacts/source/multivsl1000_class_ids.json --class-count 1000
./scripts/run_ai_local.sh
```

Trong terminal khác:

```bash
cd apps/web
npm install
npm run dev
```

Kiểm tra runtime:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/metadata
```

Backend chỉ hỗ trợ `cpu` và `cuda`. Không dùng MPS cho checkpoint này vì Conv3D không chạy ổn định với runtime PyTorch đã kiểm chứng. `PYTORCH_DEVICE=auto` chọn CUDA khi có, nếu không dùng CPU.

Trên Linux host có NVIDIA Container Toolkit, chạy cùng image GPU dự kiến cho demo/cloud:

```bash
docker compose -f docker-compose.yml -f docker-compose.ai.yml up --build
```

Lệnh này mount read-only `ml/artifacts/source` vào container; checkpoint không bị copy vào image. File override GPU không dùng được trên Docker Desktop của Mac không có NVIDIA GPU.

## Checkpoint và dữ liệu

Checkpoint/dataset không được commit hoặc đóng vào Docker image. Trước khi tải, train hoặc triển khai công khai phải xác nhận license/DUA với chủ sở hữu Multi-VSL; repository công khai hiện không cung cấp file LICENSE ở root. Sau khi nhận checkpoint hợp lệ, đặt nó ở đường dẫn mặc định bên trên hoặc truyền `PYTORCH_MODEL_PATH=/absolute/path/model.pth`.

Chạy smoke test có thể lặp lại:

```bash
.venv/bin/python -m ml.scripts.verify_multivsl_checkpoint \
  ml/artifacts/source/mvitv2_s_multivsl1000.pth \
  ml/data/raw/official-sample \
  --max-samples 10 \
  --device cpu
```

## Train ở đâu

| Giai đoạn | Nơi chạy | Lý do |
| --- | --- | --- |
| Chuẩn hóa manifest/glossary, unit test | Máy local | Không cần GPU; dễ kiểm tra dữ liệu và signer leakage. |
| Smoke test 1–10 clip | Mac/local CPU | Xác minh checkpoint và pipeline; hiện khoảng 1,2 giây compute/clip. |
| Fine-tune 20 từ thông dụng | Máy Linux có NVIDIA CUDA, khuyến nghị GPU 16–24 GB VRAM (L4, A10 hoặc tương đương) | Video transformer tốn RAM/VRAM; cần batch, augmentation và validation lặp lại. |
| Train/baseline toàn bộ 1.000 lớp | Cloud GPU có persistent storage; ưu tiên A100/L40S hoặc cụm nhiều GPU sau khi đo baseline | Không phù hợp laptop; dữ liệu lớn và nhiều vòng thử nghiệm. |

Nơi chạy cụ thể có thể là GPU workstation nội bộ hoặc cloud như RunPod, Lambda, GCP Vertex AI, AWS SageMaker/EC2. Không khóa nhà cung cấp ở giai đoạn này. Dataset nằm trong object storage/private volume cùng region với GPU; checkpoint và log metric lưu vào artifact registry/private bucket.

Phương án GCP trong kế hoạch đã được đối chiếu với tài liệu hiện hành: [Compute Engine có G2/L4 tại Singapore](https://docs.cloud.google.com/compute/docs/regions-zones/gpu-regions-zones) và [Cloud Run hỗ trợ L4 tại `asia-southeast1`](https://docs.cloud.google.com/run/docs/configuring/services/gpu), với mức tối thiểu 4 CPU/16 GiB RAM cho L4. Vẫn cần kiểm tra quota và giá ngay trước khi tạo tài nguyên.

Chưa nên fine-tune 20 từ cho đến khi có đủ ba đầu vào: quyền dùng full dataset, glossary chính thức `class_id → gloss_vi`, và danh sách class ID của 20 từ. Split phải theo signer, không random theo video. Ngoài Multi-VSL cần thu thêm validation webcam đúng bối cảnh sản phẩm để đo domain shift.

## Chạy inference ở đâu

| Môi trường | Nơi chạy | Vai trò |
| --- | --- | --- |
| Phát triển hiện tại | Backend FastAPI trên máy local, CPU | Chứng minh luồng AI thật và debug camera. |
| Demo có ít người dùng | Một Linux GPU VM/container với NVIDIA L4/T4/A10 | Giảm latency; model load một lần, một inference worker/GPU. |
| Production | Dịch vụ GPU autoscale sau API gateway, model/artifact private | Theo dõi P50/P95, error rate, GPU memory, queue và model version. |
| Trình duyệt/Cloudflare Worker | Không chạy model MViTv2-S ở đây | Frontend chỉ thu và gửi frame; model video lớn cần runtime GPU/server. |

Web có thể host bằng static hosting/CDN. Biến `VITE_INFERENCE_HTTP_URL` và `VITE_INFERENCE_WS_URL` trỏ đến FastAPI qua HTTPS/WSS. Frame camera không lưu mặc định; nếu bật lưu để cải thiện model phải có consent và retention policy riêng.

## Cổng chất lượng tiếp theo

1. Nhận glossary chính thức và xác minh mapping 1.000 output index.
2. Chọn chính xác 20 class ID thông dụng; lúc đó đổi label map và `LABELS_VERIFIED=true` để bật ghép câu.
3. Đánh giá checkpoint trên full test split theo signer/view và một negative webcam set.
4. Calibrate `CONFIDENCE_THRESHOLD`/`MARGIN_THRESHOLD`; mức `0.70/0.15` hiện chỉ là mặc định kỹ thuật.
5. Benchmark GPU end-to-end gồm decode, network và queue; đặt SLO trước public demo.
