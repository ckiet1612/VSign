# A/B camera đóng băng: V3 và V4.2

Bộ này là release gate độc lập cho model demo. Mỗi video nguồn được phát lại
qua cả V3 và V4.2, cùng chỉ số frame, rồi báo cáo riêng **Giữ để ký** và
**Tự động**. Cấm dùng video, feature, prediction, confusion hoặc threshold từ
bộ này để train, early-stop, calibrate hay điều chỉnh model.

Runtime web mặc định là V3. V4.2 chỉ được nâng thành mặc định khi báo cáo
`release_gate` trả `runtime_decision: v4_2`; nếu không, V3 tiếp tục là demo và
V4.2 chỉ nằm ở nút thử nghiệm.

## Ma trận thu cố định

- 20 từ × 3 lượt = 60 positive clip.
- 30 negative clip: đứng yên, đưa/rút tay, chỉnh tóc/kính, chạm mặt, quay
  người, chuyển động ngẫu nhiên, chồng hai tay và ký từ ngoài common-20.
- Bao phủ gần/chuẩn/xa, tay trái/phải và normal/low/side light.
- Chỉ loại clip hỏng kỹ thuật trước khi xem bất kỳ dự đoán nào.
- Đây phải là clip mới, không nằm trong 207 clip train/development hiện có.

## Quy trình

1. Lịch 90 lượt đã được tạo và xáo trộn tại
   `ml/data/evaluation/frozen_camera_v4/capture_plan.csv`. Không đổi lịch sau
   khi bắt đầu thu. Khởi động backend vào thư mục riêng:

   ```bash
   COLLECTION_ENABLED=true \
   COLLECTION_DIR=ml/data/evaluation/frozen_camera_v4/raw \
   COLLECTION_TARGET_PER_HAND=3 \
   PYTHONPATH="services/inference:." \
   .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

2. Mở web, vào **Thu dữ liệu AI** và làm lần lượt theo `order` trong CSV.
   Web lưu toàn bộ 8–42 frame nguồn của lượt thu, không chỉ 16 frame đã chọn.
   Kiểm tra đủ và không trùng:

   ```bash
   PYTHONPATH=. .venv/bin/python -m ml.scripts.audit_frozen_camera_capture
   ```

3. Khóa checksum của 90 video, metadata, capture plan, hai model/label và hai
   MediaPipe model. Threshold và luật pass/fail cũng được khóa ở bước này:

   ```bash
   PYTHONPATH=. .venv/bin/python -m ml.scripts.freeze_ab_camera_evaluation \
     --output ml/data/evaluation/frozen_camera_v4/ab_manifest.json
   ```

   Lệnh cố ý từ chối ghi đè manifest. Nếu cần chạy một đợt thu mới, dùng thư
   mục/manifest mới; không sửa bộ đã xem kết quả. Bước này cũng đối chiếu SHA256
   với toàn bộ `ml/data/collected/webcam` và từ chối nếu clip release bị sao
   chép từ bộ train/development.

4. Chạy paired A/B trực tiếp từ cùng video nguồn:

   ```bash
   PYTHONPATH=. .venv/bin/python -m ml.scripts.evaluate_landmarks_ab \
     --manifest ml/data/evaluation/frozen_camera_v4/ab_manifest.json \
     --output ml/data/evaluation/frozen_camera_v4/ab_report.json
   ```

Báo cáo JSON và Markdown gồm top‑1, correct-accepted/all, accuracy trong các
lượt accepted, rejection, false accept negative, confusion matrix, breakdown
từng từ và số/sources bị hút về “Đâu” cho cả hai chế độ.

## Cổng đã đăng ký trước

Trong từng chế độ, V4.2 phải không kém V3 về top‑1, correct-accepted/all và
accepted accuracy; không cao hơn V3 về rejection, false accept và tỷ lệ hút về
“Đâu”; false accept V4.2 tối đa 5%; đồng thời phải có ít nhất một cải thiện
nghiêm ngặt. Thiếu negative hoặc bất kỳ điều kiện nào thì quyết định là V3.

## Trạng thái

Pipeline và lịch thu đã sẵn sàng. Thư mục `raw` hiện chưa có đủ bộ camera mới,
vì 90 hành động phải do người dùng thực hiện trước webcam. 207 clip webcam cũ
đã được dùng trong phát triển nên chỉ được dùng để chẩn đoán regression, tuyệt
đối không có quyền chọn runtime.
