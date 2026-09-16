# VSign - Kế hoạch MVP nhận dạng 20 từ VSL gần real-time

## Trạng thái triển khai (2026-09-11)

- **P2 vertical slice web:** đã hoàn thành luồng camera, 16 frame, WebSocket, top-3, transcript và mock fallback.
- **P1a inference legacy:** checkpoint Multi-VSL MViTv2-S 1.000 class vẫn chạy để giữ vertical slice hoạt động, nhưng không còn là nguồn model đích.
- **P0 nguồn mới hoàn thành:** đã tải và xác minh `star092304/ViSignLanguage-Video` revision `906306d`: 8.364 video, trong đó 3.875 video train có nhãn thuộc 100 lớp. License được khai báo CC BY 4.0. Pipeline đã tạo split group-safe và common-20 gồm 989 video.
- **P1b V4.2 cá nhân hóa (thử nghiệm):** đã xác định regression là train–serving skew của pose MediaPipe (`IMAGE` lúc train nhưng `VIDEO` lúc web). Runtime đã khớp lại pose `IMAGE` mỗi ~60 ms, vẫn giữ hand `VIDEO` nhanh. Trên 207 clip development, lỗi hút về “Đâu” giảm về 0; vì các clip này từng dùng train, kết quả chỉ là chẩn đoán, không phải release gate.
- **Runtime demo hiện tại:** V3 đã được khôi phục làm mặc định; smoke test trực tiếp xác nhận V4.2 kém ổn định hơn và chỉ còn lựa chọn thử nghiệm không khuyến nghị. Chỉ paired A/B camera mới có quyền nâng một candidate mới.
- **Bước đang làm tiếp:** scale-up development V5 lên đúng 100 video thật hợp lệ cho từng từ. Public train/validation đóng góp 875 clip dùng được sau khi loại 14 clip không thấy tay; cùng 207 clip webcam hiện có, kế hoạch còn 918 lượt. Web đã có phiên thu tự động đếm ngược → quay → kiểm tra → tự lưu. Khi đủ quota mới train candidate, sau đó thu bộ release độc lập và A/B riêng Giữ/Tự động trước khi đổi model demo.

Chi tiết nguồn, audit và common-20: [docs/VISIGNLANGUAGE_VIDEO.md](docs/VISIGNLANGUAGE_VIDEO.md). Phân chia nơi train/inference: [docs/AI_RUNTIME.md](docs/AI_RUNTIME.md).

## 1. Mục tiêu

Xây dựng web app dùng camera để nhận dạng **ký hiệu VSL rời rạc** và chuyển kết quả thành từ tiếng Việt gần real-time. Bản demo đầu tiên ưu tiên độ ổn định với 20 từ thông dụng và một webcam chính diện.

> Giới hạn cần nói rõ: ViSignLanguage-Video là tập nhận dạng từng từ, chưa phải dữ liệu dịch hội thoại liên tục. MVP nhận dạng từng ký hiệu rồi nối thành chuỗi từ; đây không phải bản dịch câu VSL tự nhiên.

## 2. Cơ sở dữ liệu và các quyết định ban đầu

ViSignLanguage-Video cung cấp 3.875 video train có nhãn thuộc 100 từ tiếng Việt, độ phân giải 224×224, cùng 4.489 video public/private test không có nhãn. Nguồn không cung cấp signer ID hoặc official labeled validation/test split. VSign tạo split phát triển theo nhóm filename gốc để các biến thể `_1/_2/_3` không rò sang tập khác.

Các quyết định cho MVP:

- Dùng **camera chính diện** khi suy luận vì người dùng web thường chỉ có một webcam.
- Giữ các biến thể của cùng filename gốc trong một split; không random từng file augmentation độc lập.
- Bắt đầu với 20 từ có sẵn nhãn tiếng Việt và ưu tiên số mẫu đủ dùng.
- Có lớp kiểm soát `unknown/idle` từ dữ liệu âm tự thu; nếu không, softmax luôn ép mọi cử động thành một từ hợp lệ.
- Không lưu video camera mặc định. Chỉ lưu khi người dùng chủ động đồng ý cho mục đích đánh giá/cải thiện mô hình.

Mapping 100 nhãn tiếng Việt đã có trong archive và license được khai báo CC BY 4.0. Rủi ro dữ liệu chính còn lại là không có signer metadata, phân bố lớp lệch (6–74 clip/lớp) và 828 dòng metadata có label Unicode lỗi; pipeline đã dùng tên thư mục + mapping trong archive làm nguồn chuẩn.

## 3. Phạm vi MVP

### Có trong MVP

- Xin quyền camera, kiểm tra tư thế và vùng ký hiệu.
- Hai chế độ:
  - **Giữ để ký**: người dùng giữ nút/phím Space, thực hiện một ký hiệu, thả để nhận dạng. Đây là luồng demo chính vì khớp với dữ liệu isolated-word.
  - **Tự động (beta)**: phát hiện bắt đầu/kết thúc dựa trên chuyển động tay và khoảng nghỉ.
- Hiển thị từ dự đoán, độ tin cậy và top 3 gợi ý.
- Thêm từ đã xác nhận vào transcript; cho phép hoàn tác, xóa và sao chép.
- Trạng thái rõ ràng: chưa thấy đủ hai tay, đang thu, đang nhận dạng, không chắc chắn, mất kết nối.
- Không nhận kết quả khi confidence/margin không đạt ngưỡng; hiển thị “Chưa nhận ra, vui lòng thử lại”.

### Chưa có trong MVP

- Dịch hội thoại VSL liên tục thành câu tiếng Việt hoàn chỉnh.
- Nhận dạng bảng chữ cái/ngón tay nếu các lớp này không có trong common-20.
- Tài khoản, lịch sử cloud, cộng tác hoặc lưu video mặc định.
- Chạy hoàn toàn offline trên điện thoại.
- Hỗ trợ nhiều biến thể vùng miền khi chưa có dữ liệu/đánh giá tương ứng.

## 4. Bộ từ demo đề xuất

Common-20 đã chốt theo output index: **Chào, Cảm ơn, Xin lỗi, Tôi, Đi, Uống, Ăn, Nhà, Trường học, Bệnh viện, Giúp, Đồng ý, Nói, Nghe, Mua, Đâu, Nhìn, Cho, Biết, Có thể**.

Bộ này có 989 video: 799 train, 90 validation và 100 test. Mỗi lớp có mặt ở cả ba split theo nhóm filename; label ID common-20 được remap liên tiếp `0..19`, đồng thời giữ `source_label_id` để truy nguyên về mapping 100 lớp.

## 5. Trải nghiệm người dùng

First viewport là bề mặt làm việc, không phải landing page:

1. Khung camera lớn với guide đặt đầu, vai và tay.
2. Nút “Giữ để ký” ngay dưới camera; Space là phím tắt.
3. Kết quả hiện cạnh camera: từ lớn, confidence, top 3 và nút “Thêm vào câu”.
4. Transcript nằm bên dưới hoặc panel phải trên desktop; trên mobile nằm dưới camera.
5. Thanh trạng thái cho biết ánh sáng, khoảng cách, tay có nằm trong khung và kết nối inference.

Quy tắc giao diện:

- Chỉ commit một từ sau 2-3 cửa sổ dự đoán ổn định hoặc khi người dùng xác nhận.
- Cooldown chống lặp cùng một từ khoảng 0,8-1,2 giây.
- Không dùng màu đơn độc để truyền đạt confidence/trạng thái.
- Có hướng dẫn ngắn về quyền riêng tư ngay cạnh nút bật camera.

## 6. Kiến trúc đề xuất

```text
Web React/TypeScript
  camera + pose/motion gate + ring buffer
                 |
                 | WebSocket: frame batch + timestamp
                 v
FastAPI inference service
  validate -> crop/resize/normalize -> model -> calibration
                 |
                 v
prediction {label, confidence, top_k, status, model_version}
                 |
                 v
UI stabilizer -> user confirmation -> transcript
```

### Web

- React + TypeScript + Vite.
- `getUserMedia` cho webcam; Canvas/Worker để resize và nén frame, tránh khóa UI.
- Ring buffer 2,5-3 giây. Chỉ gửi 16 frame đã sample, không stream video nguyên bản liên tục.
- WebSocket cho phiên inference; HTTP `/health`, `/metadata` và upload-video dùng cho debug.
- HTTPS là bắt buộc ngoài `localhost` để camera hoạt động.

### AI service

- Python, FastAPI, PyTorch; export ONNX/TensorRT sau khi baseline đúng.
- Runtime hiện tại: checkpoint Multi-VSL 1.000 class chỉ là baseline legacy. Model đích là MViTv2-S common-20, input 16 frame 224×224, khởi tạo từ Kinetics-400.
- So sánh thêm một model nhẹ (VideoMAE-Small hoặc RGB/pose TCN). Chọn model cuối theo macro F1 của split phát triển và accuracy trên bộ webcam người mới.
- Một worker GPU cho MVP; giới hạn queue và trả `busy` thay vì để request treo.
- Phiên bản hóa `model`, `label_map`, preprocessing và threshold cùng một artifact.

### AI được train và chạy inference ở đâu

#### Phương án mặc định

| Giai đoạn | Nơi chạy | Cấu hình mục tiêu | Vai trò |
| --- | --- | --- | --- |
| Phát triển local | MacBook Pro M1, RAM 8 GB hiện tại | CPU, batch 1 | Làm web, data audit, unit test và kiểm tra inference trên vài clip. PyTorch MPS hiện không hỗ trợ Conv3D của model này. |
| Model spike | Google Colab | Một GPU được cấp theo phiên | Xác minh notebook, preprocessing và train thử trên 2-5 lớp/ít epoch. Không coi là môi trường train tái lập vì GPU, thời lượng và khả năng giữ phiên không được đảm bảo. |
| Train chính | [Google Compute Engine](https://docs.cloud.google.com/compute/docs/regions-zones/gpu-regions-zones), region `asia-southeast1` (Singapore) | `g2-standard-8`, 1 NVIDIA L4 24 GB, 8 vCPU, 32 GB RAM; disk/cache điều chỉnh sau data audit | Fine-tune 20 lớp, evaluation, calibration và ONNX export. Có VM/persistent storage do dự án kiểm soát nên job dài không phụ thuộc notebook session. |
| Inference local | MacBook M1 qua PyTorch CPU; ONNX chỉ dùng sau khi export/đối chiếu thành công | Batch 1 | Debug end-to-end; latency đo ở đây không phải SLA production. |
| Inference web demo | [Cloud Run GPU](https://docs.cloud.google.com/run/docs/configuring/services/gpu), region `asia-southeast1` (Singapore) | 1 NVIDIA L4, tối thiểu 4 vCPU/16 GiB RAM, một model worker/container | Nhận 16 frame qua WebSocket, chạy model và trả prediction. Gần người dùng ở Việt Nam hơn các region Mỹ/Âu và có thể scale về 0 khi không dùng. |

Luồng mặc định:

```text
ViSignLanguage-Video CC BY 4.0 -> Cloud Storage private (Singapore)
                                |
                                v
Compute Engine L4 training -> model artifact/versioned metrics
                                |
                                v
Artifact Registry -> Cloud Run L4 inference (Singapore)
                                ^
                                |
                    Web app HTTPS từ trình duyệt
```

#### Vì sao không train chính trên máy hiện tại

Máy hiện tại là Apple M1 với 8 GB unified memory và phù hợp để chạy pipeline nhỏ, unit test và inference CPU batch-1. Conv3D của checkpoint không chạy được trên MPS với runtime đã kiểm chứng. Video transformer còn phải giữ nhiều frame, activation và optimizer state; 8 GB không đủ dư địa an toàn để fine-tune MViTv2-S ổn định, và hệ CUDA/TensorRT dự kiến dùng khi deploy cũng không có trên máy này. Train chính trên NVIDIA L4 giúp môi trường gần với inference production và dễ tái lập hơn.

#### Quản lý dữ liệu và artifact

- Raw video, manifest group-safe và checkpoint đặt trong bucket private; không commit vào Git. Dataset local hiện dùng cho audit, sau đó đồng bộ bucket bằng checksum.
- Bucket, VM train, Artifact Registry và Cloud Run đặt cùng region Singapore khi điều khoản dữ liệu cho phép để giảm truyền dữ liệu và latency.
- Mỗi run ghi `git commit`, config, seed, label map hash, preprocessing version, metrics và checkpoint URI.
- VM train được tắt ngay sau job; chỉ giữ persistent disk khi còn cần cache. Có script tạo/xóa hạ tầng để tránh tài nguyên GPU chạy quên.
- Cloud Run để `min-instances=0` khi phát triển nhằm giảm chi phí. Trước buổi demo đặt `min-instances=1`, warm model và chạy smoke test; sau demo trả về 0. Scale-to-zero có cold start nên không dùng cho phiên trình diễn mà không warm trước.
- WebSocket client phải tự reconnect. Cloud Run hỗ trợ WebSocket nhưng kết nối vẫn chịu request timeout; MVP không giữ state quan trọng trên container, vì transcript nằm ở trình duyệt.

#### Phương án thay thế

- **Demo offline/không tin cậy Internet:** dùng PC/laptop NVIDIA có tối thiểu khoảng 8 GB VRAM và chạy cùng Docker inference image trong LAN. Nếu chỉ có Mac M1 8 GB, cần benchmark model ONNX/Core ML nhẹ hơn trước khi cam kết latency.
- **Prototype chi phí thấp:** Colab có thể train thử 20 lớp nếu phiên đủ dài, nhưng phải resume từ checkpoint lưu ngoài runtime; không chọn cho release vì tài nguyên thay đổi theo thời điểm.
- **Khi chưa cần GPU production:** benchmark ONNX CPU. Chỉ chuyển inference sang CPU nếu vẫn đạt P95 ≤ 1.000 ms và không vượt giới hạn concurrency; không giả định trước rằng CPU đủ nhanh.

#### Kiểm tra trước khi chốt cấu hình

1. Chạy cùng 100 clip trên CPU local, L4 PyTorch và L4 ONNX.
2. Đo VRAM peak, thời gian preprocess, model latency, end-to-end P50/P95 và cold start.
3. Thử concurrency 1, 2, 4 và 8 phiên; chọn giới hạn mà latency không vượt SLA.
4. So sánh chi phí cho một buổi demo và một tháng thử nghiệm ở hai chế độ `min-instances=0/1` bằng calculator tại thời điểm deploy.
5. Nếu L4 dư thừa, thử model nhẹ/CPU; nếu thiếu VRAM hoặc throughput, tăng cấu hình sau benchmark thay vì chọn A100 ngay từ đầu.

### Monorepo dự kiến

```text
VSign/
  apps/web/                  # React/TypeScript UI
  services/inference/       # FastAPI + runtime model
  ml/
    configs/                # train/eval/export configs
    data/                    # manifest, không commit video
    scripts/                 # audit, preprocess, train, evaluate
    notebooks/              # chỉ cho khám phá, không là pipeline chính
  contracts/                # schema request/response dùng chung
  tests/
    fixtures/               # clip synthetic/được phép phân phối
    e2e/
  docs/
  docker-compose.yml
  .env.example
```

## 7. Pipeline dữ liệu và mô hình

### 7.1 Data audit

1. Tải `dataset.zip` từ Hugging Face và bắt buộc khớp SHA256 đã ghim.
2. Kiểm tra path traversal/symlink trước khi giải nén; chuẩn hóa tên thư mục Unicode NFC.
3. Lấy mapping 100 lớp từ restricted pickle và label thật từ thư mục video; chỉ dùng CSV cho metadata kỹ thuật vì 828 dòng có label lỗi Unicode.
4. Gom các biến thể `_1/_2/_3` theo filename gốc, rồi chia group-safe train/validation/test bằng seed cố định.
5. Chọn common-20, remap output `0..19` và ghi audit phân bố class/split.

### 7.2 Preprocessing

- Decode clip theo FPS nguồn và sample đều 16 frame.
- Crop vùng thân trên nhất quán với training; resize 224×224 và chuẩn hóa ImageNet.
- Augmentation train: random crop nhẹ, brightness/contrast, rotation nhỏ, temporal jitter và frame drop.
- Không horizontal flip mặc định: lật có thể đổi tay thuận/ý nghĩa và tạo mẫu không hợp lệ; chỉ bật sau khi người có chuyên môn VSL duyệt.
- Bổ sung negative clips: đứng yên, đưa tay vào khung, chỉnh tóc/kính, quay người, cử động ngẫu nhiên, một phần tay ngoài khung.

### 7.3 Training và đánh giá

- Fine-tune classifier 20 từ + cơ chế reject unknown.
- Early stopping theo macro F1 trên validation group-safe; lưu top-1/top-3, ECE/calibration và confusion matrix.
- Calibrate temperature/threshold trên validation, không dùng test để chọn threshold.
- Test phát triển trên group-safe test; kết luận khái quát hóa chỉ dựa trên bộ webcam riêng với người, phòng, camera và ánh sáng khác dataset.
- Export ONNX và kiểm tra sai lệch logits/prediction so với PyTorch trên một tập clip cố định.

### 7.4 Vòng suy luận gần real-time

1. Motion/pose gate phát hiện sẵn sàng.
2. Thu cửa sổ 2,5-3 giây, sample 16 frame.
3. Inference và trả top 3.
4. Áp dụng confidence + margin + quality gates.
5. Majority vote/EMA qua các cửa sổ gần nhau.
6. Commit từ một lần, rồi chờ tay nghỉ/cooldown trước ký hiệu tiếp theo.

## 8. API tối thiểu

```json
{
  "type": "frames",
  "session_id": "uuid",
  "sequence": 12,
  "captured_at": 1788980000000,
  "frames": ["...16 JPEG/WebP frames..."]
}
```

```json
{
  "type": "prediction",
  "sequence": 12,
  "status": "ok",
  "label": "cảm ơn",
  "confidence": 0.91,
  "top_k": [
    {"label": "cảm ơn", "confidence": 0.91},
    {"label": "xin lỗi", "confidence": 0.05},
    {"label": "xin chào", "confidence": 0.02}
  ],
  "model_version": "vsl-common-20-v1"
}
```

Các `status` khác: `uncertain`, `no_hands`, `bad_framing`, `busy`, `error`. Server giới hạn kích thước frame, số frame, FPS và thời gian phiên.

## 9. Chỉ số hoàn thành MVP

### Offline

- Group-safe top-1 ≥ 90% và macro F1 ≥ 0,88 trên common-20.
- Top-3 ≥ 97%.
- Báo cáo per-class recall; không lớp nào dưới 75% nếu không có giải trình và kế hoạch bổ sung dữ liệu.
- False accept trên negative set < 5%.

### Webcam thực tế

- Ít nhất 5 người chưa có trong training, mỗi người 20 từ × 3 lần.
- Top-1 ≥ 85% trong điều kiện demo đã quy định.
- Median latency sau khi kết thúc ký hiệu ≤ 500 ms; P95 ≤ 1.000 ms trên hạ tầng mục tiêu.
- Không commit lặp một ký hiệu trong ≥ 95% lượt thử.
- Tỷ lệ phiên bật camera và nhận được dự đoán đầu tiên ≥ 95% trên Chrome/Edge desktop hiện hành.

Các ngưỡng là mục tiêu go/no-go; cần điều chỉnh sau data/model spike nếu phần cứng mục tiêu khác giả định.

## 10. Lộ trình thực hiện

### P0 - Gỡ chặn dữ liệu (1-2 ngày)

- [x] Ghim nguồn/revision/license/checksum và tải archive.
- [x] Xác minh mapping 100 nhãn tiếng Việt, sửa chiến lược đọc metadata lỗi Unicode.
- [x] Tạo manifest group-safe và common-20 799/90/100.

**Hoàn thành khi:** mọi clip train có label hiển thị được, nguồn/điều khoản được ghi lại và có báo cáo phân bố.

### P1 - Baseline AI (3-5 ngày)

- Hoàn thiện preprocessing tái lập được.
- Spike trên Colab, sau đó fine-tune MViTv2-S 20 lớp trên Compute Engine L4; thêm negative/reject logic.
- Đánh giá, confusion matrix, calibration; export ONNX.

**Hoàn thành khi:** đạt ngưỡng offline hoặc có bảng lỗi cho từng lớp và quyết định bổ sung/đổi lớp.

### P2 - Vertical slice web (3-4 ngày)

- Camera + hold-to-sign + WebSocket inference.
- Kết quả top 3, trạng thái lỗi và transcript cơ bản.
- Docker hóa và chạy local trên MPS/CPU; health check và logging không chứa frame.

**Hoàn thành khi:** một người có thể mở web, ký 20 từ lần lượt và sao chép transcript.

### P3 - Hands-free beta và độ bền (3-4 ngày)

- Motion gate, smoothing, cooldown, unknown rejection.
- Xử lý ánh sáng/khoảng cách/mất kết nối.
- Test webcam với người chưa thấy; tối ưu latency.

**Hoàn thành khi:** đạt tiêu chí webcam hoặc có danh sách lỗi ưu tiên theo dữ liệu thực.

### P4 - Demo release (1-2 ngày)

- Accessibility/responsive/security pass.
- Deploy frontend HTTPS + Cloud Run L4 tại Singapore; cấu hình warm instance cho thời gian demo.
- Runbook, model card, data card và script smoke test.

**Ước lượng:** 2-3 tuần cho một kỹ sư full-time nếu GPU sẵn sàng. Chưa bao gồm thời gian thu và đánh giá thêm dữ liệu với cộng đồng người Điếc.

## 11. Rủi ro và cách giảm thiểu

| Rủi ro | Ảnh hưởng | Giảm thiểu |
| --- | --- | --- |
| CSV có label Unicode lỗi | Gán sai từ khi train | Lấy label từ thư mục archive + mapping, NFC và audit mismatch |
| Dataset isolated khác webcam liên tục | Sai boundary, dự đoán chập chờn | Hold-to-sign là luồng chính; auto mode beta; thu negative/boundary clips |
| Không có signer metadata | Không đo được unseen-signer offline | Group-safe split + webcam test với người chưa thấy; không gọi metric offline là signer-independent |
| Domain shift về người, nền, ánh sáng, camera | Accuracy thực thấp hơn test | Webcam test set; crop/quality gate; bổ sung dữ liệu có consent |
| Mọi cử động bị ép thành một từ | Trải nghiệm nguy hiểm và thiếu tin cậy | Unknown/idle negatives, calibration, margin threshold, cho người dùng xác nhận |
| Biến thể vùng miền VSL | Kết quả không đại diện cho mọi người dùng | Ghi rõ phạm vi dữ liệu; đánh giá với chuyên gia/người dùng mục tiêu; thu dữ liệu đa vùng ở phase sau |
| Video chứa dữ liệu sinh trắc học | Rủi ro quyền riêng tư | Không lưu mặc định; consent riêng; retention ngắn; mã hóa và kiểm soát truy cập |

## 12. Backlog đầu tiên

1. `data-audit`: **xong** — checksum, safe extract, Unicode và class/split report.
2. `label-map`: **xong** — mapping 100 lớp và common-20 có output index cố định.
3. `common-20`: **xong** — manifest group-safe 799/90/100.
4. `baseline-train`: config MViTv2-S, seed cố định, metrics và artifacts.
5. `unknown-set`: hướng dẫn thu, consent và 200-500 negative clips.
6. `inference-contract`: WebSocket schema + mock server.
7. `camera-ui`: permission, guide, hold-to-sign, ring buffer.
8. `vertical-slice`: camera → model → top 3 → transcript.
9. `webcam-eval`: protocol 5 người × 20 từ × 3 lần.
10. `release-gate`: privacy, accessibility, latency và model/data cards.

## 13. Hướng phát triển sau MVP

- Mở từ 20 lên 50 rồi toàn bộ 100 lớp dựa trên confusion và nhu cầu thật.
- Distillation/pose fusion để tạo student nhẹ hơn cho inference.
- Pose + RGB fusion để tăng khả năng khái quát và hỗ trợ edge inference.
- Thu dữ liệu continuous VSL có boundary/gloss/text annotation, sau đó huấn luyện sign-to-gloss sequence và gloss-to-Vietnamese translation.
- Personalization có consent, federated/on-device learning và hỗ trợ biến thể vùng miền.

## 14. Nguồn tham chiếu

- Nguồn chính ViSignLanguage-Video, CC BY 4.0: https://huggingface.co/datasets/star092304/ViSignLanguage-Video
- Nguồn gốc được dataset card dẫn: AI Challenge CV, PTIT: https://aichallenge.ptit.edu.vn/
- PyTorch MPS backend cho Apple silicon: https://docs.pytorch.org/docs/stable/notes/mps.html
- Google Compute Engine - GPU regions/zones: https://docs.cloud.google.com/compute/docs/regions-zones/gpu-regions-zones
- Google Compute Engine - G2/NVIDIA L4: https://docs.cloud.google.com/compute/docs/accelerator-optimized-machines
- Cloud Run GPU và region Singapore: https://docs.cloud.google.com/run/docs/configuring/services/gpu
- Cloud Run WebSocket: https://docs.cloud.google.com/run/docs/triggering/websockets
- Google Colab resource limits: https://research.google.com/colaboratory/faq.html
