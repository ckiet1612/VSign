# Regression chất lượng V3 → V4.2

Ngày chẩn đoán: 2026-09-11.

## Kết luận

Regression không nằm ở ONNX inference hay tốc độ hand tracking. V4.2 được
train với Pose Landmarker ở `RunningMode.IMAGE`, nhưng web và evaluator ban đầu
dùng pose `RunningMode.VIDEO` rồi tái sử dụng pose 120 ms. Sai khác hệ tọa độ
pose sau chuẩn hóa theo vai đủ lớn để model kéo nhiều ký hiệu tay phải về
“Đâu”.

Bản sửa giữ Hand Landmarker ở GPU/`VIDEO` để tracking tay có độ trễ thấp, đổi
riêng Pose Landmarker sang CPU/`IMAGE` và refresh khoảng 60 ms. CPU là delegate
đã tạo feature train và A/B; sai khác pose GPU/CPU không còn bị khuếch đại sau
chuẩn hóa theo vai. Không thay trọng số, không train lại và không chỉnh
threshold từ kết quả đánh giá.

## Bằng chứng tách biến

Cùng clip camera `Uống/right/20260910T212004Z-3159be22e7.mp4` và cùng V4.2:

| Hand | Pose | Refresh pose | Top-1 |
|---|---|---:|---|
| IMAGE | IMAGE | mỗi frame | Uống 98,63% |
| VIDEO | IMAGE | mỗi frame | Uống 98,40% |
| VIDEO | IMAGE | mỗi 2 frame (~60–70 ms) | Uống 97,00% |
| VIDEO | VIDEO | mỗi frame | Đâu 77,98% |
| VIDEO | VIDEO | mỗi 2 frame | Đâu 62,08% |

Việc đổi hand IMAGE/VIDEO gần như không ảnh hưởng kết quả; đổi pose làm đảo
nhãn. Hai view gốc/mirror đều từng dự đoán “Đâu”, nên mirror ensemble không
phải nguyên nhân.

## Paired diagnostic trên 207 clip camera lịch sử

Mỗi model nhận cùng video và cùng các chỉ số frame. Hai chế độ được báo cáo
riêng. `Correct accepted / all` là số mẫu vừa được hệ thống chấp nhận vừa đúng,
chia cho toàn bộ positive; nó không che rejection như accuracy chỉ trên các
mẫu accepted.

### Trước sửa

| Chế độ | Model | Top-1 | Correct accepted / all | Accuracy khi accepted | Rejection | Hút sai về Đâu |
|---|---|---:|---:|---:|---:|---:|
| Giữ | V3 | 97,1% | 96,6% | 98,5% | 1,9% | 0 |
| Giữ | V4.2 | 85,0% | 78,3% | 92,6% | 15,5% | 16 |
| Tự động | V3 | 96,1% | 87,4% | 97,3% | 10,1% | 0 |
| Tự động | V4.2 | 72,9% | 58,0% | 92,3% | 37,2% | 20 |

Nguồn bị hút về “Đâu” tập trung ở `Biết`, `Nghe`, `Uống`, `Ăn`, `Đồng ý` và
hầu hết là clip tay phải.

### Sau sửa pose contract

| Chế độ | Model | Top-1 | Correct accepted / all | Accuracy khi accepted | Rejection | Hút sai về Đâu |
|---|---|---:|---:|---:|---:|---:|
| Giữ | V3 | 97,1% | 96,6% | 98,5% | 1,9% | 0 |
| Giữ | V4.2 | 100,0% | 99,5% | 100,0% | 0,5% | 0 |
| Tự động | V3 | 95,2% | 89,9% | 97,9% | 8,2% | 0 |
| Tự động | V4.2 | 99,5% | 97,1% | 100,0% | 2,9% | 0 |

Hai lượt replay Tự động dùng pose timing khác nhau trước/sau sửa, nên số V3
Tự động có thể thay đổi nhẹ dù trọng số V3 không đổi. Đây là đúng hành vi của
paired test: trong mỗi lượt, V3 và V4.2 luôn nhận cùng đoạn/cùng chỉ số frame.

## Giới hạn và quyết định runtime

207 clip trên từng tham gia train/development V3/V4.2 và không có negative.
Vì vậy chúng chỉ xác nhận regression kỹ thuật, không được dùng để chọn model,
train, calibrate hoặc chỉnh threshold. Báo cáo chi tiết nằm tại:

- `ml/data/evaluation/training_webcam_ab_diagnostic/report.json` (trước sửa)
- `ml/data/evaluation/training_webcam_ab_diagnostic/report_pose_image_fix.json`
  (sau sửa)

V3 được khôi phục làm runtime demo mặc định. V4.2 ở chế độ thử nghiệm cho đến
khi bộ camera mới 60 positive + 30 negative được khóa checksum và vượt toàn bộ
cổng trong `docs/FROZEN_CAMERA_EVAL.md` ở cả Giữ và Tự động.

Smoke test camera trực tiếp sau khi đồng bộ pose vẫn cho thấy V4.2 kém ổn định
hơn V3: “Nói” có thể bị hút về “Đâu” và việc chuyển sang V4.2 làm tái xuất hiện
lỗi ở các từ khác. Quan sát này không được lượng hóa và không dùng để train hay
chỉnh threshold; nó chỉ củng cố quyết định vận hành an toàn là giữ V3 cho demo.
