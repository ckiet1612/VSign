# Train và inference AI cho VSign

## Runtime đang dùng

Runtime demo mặc định đã được rollback về
`landmark-keyframe-v3-personalized`. `unified-landmark-v4.2-personalized` vẫn
chạy được bằng nút **V4.2 thử nghiệm**, nhưng không được chọn làm mặc định trước
khi vượt paired A/B trên bộ camera độc lập.

`guarded-landmark-v5-bootstrap` cũng đã có ở nút **V5 thử nghiệm**. Model nhận
`16 × 185`: giữ nguyên 128 feature và toàn bộ trọng số V3, rồi ghép 57 feature
ngữ cảnh thân trên. Residual chỉ sửa 5 logits `Uống`, `Ăn`, `Trường học`,
`Nói`, `Đâu`, bị chặn ở `±1,25`, và tắt hoàn toàn nếu thiếu hai vai hoặc top-1
V3 nằm ngoài nhóm này. Vì vậy 15 lớp ổn có đường suy luận đúng V3.

V3 nhận chuỗi `16 × 128` gồm tọa độ 21 điểm của tối đa hai tay và hai presence
bit. V4.2 nhận chuỗi `16 × 183` feature:

- hình dáng hai bàn tay quanh cổ tay: `2 × 21 × xyz`;
- vị trí hai cổ tay tương đối trung điểm/chiều rộng hai vai;
- 11 điểm đầu, mắt, miệng, vai, khuỷu tay và cổ tay tương đối hai vai;
- vector hướng xyz và khoảng cách giữa hai cổ tay; khi hand landmark bị che,
  đặc trưng này dùng cổ tay pose và giữ mask nguồn thay vì bịa hand landmark;
- mask riêng cho từng tay và từng điểm pose; điểm bị mất luôn bằng 0 kèm mask
  0, không được nội suy thành tọa độ giả;
- nhánh keyframe học thời điểm quyết định, nhánh trajectory học vận tốc và thứ
  tự chuyển động trên toàn chuỗi.

Tay được ghép vào slot trái/phải bằng cổ tay pose, nên hai tay bắt chéo không
làm đổi slot chỉ vì thứ tự theo trục x. Khi một tay che tay kia như ký hiệu
“Trường học”, pose khuỷu/cổ tay vẫn giữ chuyển động trong chuỗi. Auto
segmentation cũng không kết thúc sớm ở các frame chỉ còn pose và lấy mẫu dày
hơn quanh chuyển động mạnh, nhưng vẫn giữ đầu/cuối và quỹ đạo đầy đủ.

## Dữ liệu và kết quả hiện tại

- 207 MP4 webcam đã xác nhận, được trích lại bằng cùng Hand/Pose Landmarker mà
  browser sử dụng.
- Tay chi tiết xuất hiện trung vị 9/16 frame; pose xuất hiện 16/16 frame trong
  các clip thu. Pose giữ ngữ cảnh cho 1.387 frame bị mất tay chi tiết.
- 80 đoạn idle thật được lấy từ biên đầu/cuối clip, lọc theo chuyển động, rồi
  thêm thành lớp thứ 21 `Không ký hiệu`. Idle giữ cùng split với video nguồn để
  tránh leakage.
- ViSignLanguage bổ sung 541 group train và 119 group validation: common-20
  đa người được cân bằng với 302 mẫu train thuộc cả 80 lớp ngoài phạm vi.
- Split phát triển kết hợp: 769 train / 178 validation, trong đó 364/98 là
  idle/OOV. Checkpoint epoch 48 đạt 90,4% validation thường, 91,0% khi lật
  trái–phải và 91,0% khi che một tay ở giữa chuỗi; local-only validation vẫn
  100%, public validation 85,7%.
- Khi mean logits hai view như browser, accuracy validation là 91,0%. Ngưỡng
  manual giữ 95% positive đúng với false-accept negative 4,1%; auto giữ 93,8%
  với false-accept 3,1%.
- Bốn mẫu validation `Trường học` đều đúng khi xóa một tay ở frame 5–10;
  confidence thấp nhất 83,9%. Đây vẫn là stress test phát triển, không thay
  thế kiểm thử webcam đóng băng.
- ONNX 1,8 MB; benchmark native CPU batch-1 trên Mac M1: median 0,144 ms, P95
  0,535 ms. MediaPipe tracking, không phải ONNX, là phần chi phối FPS camera.
- V5 bootstrap 1,3 MB; native CPU batch-1 median 0,202 ms, P95 0,566 ms. Trên
  41 clip validation development, top-1 giữ 100%; xác suất đúng trung bình của
  5 lớp mục tiêu tăng 91,51% → 93,56% và 15 lớp còn lại giữ đúng 94,73%.
  Dữ liệu này thuộc cùng nguồn development local nên không phải release metric.

### Regression V3 → V4.2 đã xác định

V4.2 được train bằng pose MediaPipe `IMAGE`, trong khi web cũ phục vụ pose bằng
`VIDEO` và giữ lại 120 ms. Trên chính một clip “Uống”, feature train dự đoán
“Uống” 98,6% nhưng đường phục vụ cũ dự đoán “Đâu” 79,6%. Tách biến cho thấy
hand `VIDEO` + pose `IMAGE` vẫn dự đoán “Uống” 98,4%; vì vậy hand tracking nhanh
được giữ nguyên, pose chuyển về `IMAGE` trên CPU và refresh khoảng 60 ms. Pose
CPU cũng khớp delegate đã tạo feature train/A/B; trình duyệt không còn tự ưu
tiên pose GPU vì sai khác nhỏ bị khuếch đại sau chuẩn hóa theo vai.

Chạy lại 207 clip camera development trên cùng nguồn video cho kết quả chẩn
đoán sau sửa: V4.2 top‑1 100% ở Giữ và 99,5% ở Tự động, accepted-correct/all
99,5% và 97,1%, số lỗi hút về “Đâu” là 0 ở cả hai chế độ. V3 tương ứng đạt
97,1%/95,2% top‑1 và 96,6%/89,9% accepted-correct/all. Vì 207 clip này đã tham
gia train, các số chỉ xác nhận nguyên nhân kỹ thuật; chúng không được dùng chọn
runtime hoặc tuyên bố chất lượng phát hành.

Các số trên chỉ là kiểm thử phát triển của một người/cùng buổi. Không dùng
chúng để tuyên bố chất lượng cho người ký mới. Bộ camera thật đóng băng vẫn là
cổng quyết định và tuyệt đối không được dùng để train/chọn threshold.

## Train và inference chạy ở đâu

| Việc | Nơi chạy hiện tại | Khi nào cần GPU |
| --- | --- | --- |
| Trích landmark V4, tạo idle, train/export V4/V5 | Mac M1 CPU local | Không cần GPU với vài trăm chuỗi landmark. |
| Inference demo V3 / thử nghiệm V4.2 và V5 | Browser của người dùng: MediaPipe + ONNX Runtime Web | Không cần server/GPU; tọa độ ở trong browser. |
| Fallback video MViTv2-S | FastAPI local hoặc server | Mac CPU chậm 3,2–3,8 giây/lượt; L4 phù hợp hơn. |
| Fine-tune video/mô hình nhiều người quy mô lớn | Colab để spike; Compute Engine L4 Singapore cho run tái lập | Cần NVIDIA CUDA. |
| Deploy fallback video | Cloud Run GPU L4 Singapore | Chỉ bật/warm khi demo cần fallback. |

Máy Mac 8 GB phù hợp cho V4 và kiểm thử web. Colab bị ngắt phiên nên checkpoint
phải lưu Drive; không dùng Colab làm môi trường release dài hạn. Mô hình V4
không cần Colab.

## Tái tạo V4 trên Mac CPU

```bash
.venv/bin/pip install -r ml/requirements.txt
.venv/bin/python -m ml.scripts.extract_landmarks_v4
.venv/bin/python -m ml.scripts.build_idle_landmarks_v4
.venv/bin/python -m ml.scripts.extract_public_landmarks_v4
.venv/bin/python -m ml.scripts.train_landmarks_v4 \
  --supplement-dataset ml/data/processed/landmarks_v4/public_balanced_trainval.npz
```

Đầu ra:

- feature gốc: `ml/data/processed/landmarks_v4/collected_common20.npz`;
- feature 21 lớp: `ml/data/processed/landmarks_v4/collected_common20_idle.npz`;
- public train/validation: `ml/data/processed/landmarks_v4/public_balanced_trainval.npz`;
- public test auxiliary đóng băng: `ml/data/processed/landmarks_v4/public_balanced_test.npz`;
- checkpoint/metrics: `ml/artifacts/landmark_v4/`;
- browser: `apps/web/public/models/vsign-landmark-v4.onnx` và labels;
- MediaPipe local: `hand_landmarker.task` và `pose_landmarker_lite.task`.

Train script chọn checkpoint bằng loss tổng hợp validation thường + mirrored +
occluded. ONNX export được so logits với PyTorch và benchmark trước khi copy vào
web.

## Luồng realtime

```text
Camera
  ├─ Hand Landmarker VIDEO ~ theo frame camera
  └─ Pose Lite IMAGE ~60 ms, khớp feature lúc train V4.2
          ↓
shoulder-relative V4 + masks → ring buffer → pre-roll + gesture + post-roll
          ↓
Unified keyframe/trajectory ONNX (browser)
          ↓
idle/top-1/threshold/margin gate → uncertain hoặc top-3 → người dùng xác nhận
```

Ở V5, nhánh keyframe V3 vẫn quyết định chính. Context chỉ được đi qua cổng
focus/pose rồi cộng một residual hữu hạn; nó không thể thay thế toàn bộ bộ phân
loại như V4.2.

Auto mode giữ 650 ms pre-roll và 240 ms post-roll, chuẩn hóa tốc độ chuyển động
theo thời gian rồi lọc trung vị để không phụ thuộc FPS. Chỉ nhiều frame có
landmark bàn tay thật mới được mở clip; pose cổ tay/khuỷu chỉ duy trì clip đã
mở khi hai tay che nhau. Sau cooldown, bộ thu phải thấy một nhịp nghỉ trước khi
nhận từ tiếp theo. Chuỗi được lấy mẫu thích ứng theo chuyển động. Nếu `Không ký hiệu` đứng đầu,
hoặc confidence/margin thấp, kết quả là `uncertain` và không thể thêm vào câu.

### Chạy model ngay khi tay vừa dừng (chỉ áp dụng cho route server RGB)

Khi tay đứng yên được 150 ms (`SPECULATE_AFTER_MS`), bộ tách lượt cắt ra một đoạn
tạm, theo đúng cách nó sẽ cắt khi kết thúc lượt. Đoạn tạm được gửi lên server ngay.

- Nếu tay cử động lại, đoạn tạm bị huỷ. Request đã gửi vẫn chạy cho xong, nhưng
  kết quả bị bỏ qua.
- Nếu lượt ký kết thúc trên chính khoảng nghỉ đó (420 ms đứng yên + 240 ms
  post-roll), đoạn cuối cùng là đúng đoạn tạm. Kết quả đã nhận được giữ sẵn và
  được thêm vào câu ngay, không gửi request mới.
- Kết quả của đoạn tạm được giữ cho đến khi xác nhận. Trạng thái "đang xử lý",
  việc thêm từ vào câu và các sự kiện câu chỉ chạy sau khi xác nhận.
- Đoạn tạm không tính vào giới hạn 2 lượt chờ, để không tạm dừng thu giữa chừng
  lượt đang ký.
- Lượt bị cắt vì chạm mốc 3 s vẫn đi theo đường cũ.
- Route landmark trong trình duyệt không dùng đoạn tạm.

Từ lúc dừng tay đến lúc có kết quả, thời gian giảm từ khoảng 1,05 s xuống khoảng
0,66 s, vì model chạy trong lúc chờ xác nhận. Khoảng nghỉ cần giữa hai từ không đổi.

Clip giờ chỉ kèm khoảng 150 ms đứng yên ở cuối, thay vì khoảng 660 ms như trước.
Đã thử nối thêm 510 ms khung đứng yên vào clip thật, mỗi nhóm 100 clip, và so quyết
định của model trên clip ngắn (mới) với clip dài (cũ):

| Nhóm | Quyết định giống nhau | Nhận đúng (mới / cũ) |
|---|---|---|
| Personal | 100/100 | 97 / 97 |
| Đứng | 100/100 | 98 / 98 |
| Ngồi (Như) | 88/100 | 85 / 79 |

Ô "Chờ sau khi ký" trong bảng thời gian xử lý cho biết thời gian còn phải chờ
sau khi lượt được xác nhận.

## Cổng chất lượng còn thiếu

1. Thu thêm negative camera thật: chỉnh tóc/kính, quay người, đưa tay vào/rút
   tay khỏi khung, cử động ngẫu nhiên và hai tay chồng nhau. OOV public hiện
   đã phủ đủ 80 lớp ngoài common-20 nhưng không thay thế hành động đời thường.
2. Đóng băng một bộ camera riêng; không train, không early-stop và không chỉnh
   threshold từ bộ đó.
3. Đo confusion, false accept negative, FPS, cold start và end-to-end P50/P95.
4. Chỉ nâng candidate nếu nó không kém V3 ở mọi metric đã khóa của cả hai chế độ,
   có cải thiện nghiêm ngặt và false accept negative không quá 5%.

Auxiliary public test 119 group đã được khóa trước train và chưa đạt release
gate camera (74,4% accepted-positive, 11,25% false-accept ở V4.2). Nó hữu ích
để chỉ ra domain shift nhưng không được gọi là camera test; bộ camera thật ở
trên vẫn là nguồn quyết định phát hành.

Mô hình video ViSignLanguage common-20 vẫn là baseline group-safe 98%/97,98%
macro-F1 trên 100 clip test. Nguồn không có signer ID, vì vậy không gọi metric
đó là signer-independent.
