# Kiểm tra lỗi và chuẩn bị test camera Sales30

## Phạm vi đã triển khai

Các công cụ này không sửa model, ngưỡng, dữ liệu cũ, frontend đang phục vụ hay
bộ ghép câu. Chúng truy vết lỗi, kiểm tra đầu vào và chặn việc dùng dữ liệu
train/validation cũ làm test camera mới. Chưa có cải thiện độ chính xác được
chứng minh sau bước này.

Model hiện hành: `sales30-mvitv2s-personal-v1-head-epoch29`, Core ML,
confidence `0.70`, margin `0.15`. Checkpoint v3 vẫn là bản dự phòng.

## Hàng đợi kiểm định

Xem `docs/reports/2026-10-10-recognition-remediation/final-audit/review_queue.csv`.
Ưu tiên `Mua`, `Muốn`, `Sử dụng`, `Rẻ`, sau đó các từ thường không xác định.
Mỗi dòng tách `wrong_accept` với `uncertain`, nhãn đã được chấp nhận với top 1
thô; clip ngồi có nguồn, checksum, thời điểm bắt đầu/kết thúc và lần lặp.

Người hiểu VSL cần xem toàn clip và video nguồn, không chỉ contact sheet:

1. `label_review`: cử chỉ có đúng nhãn, cách ký và vùng/ngữ cảnh đã thống nhất?
2. `segment_review`: có đúng một lần ký, đủ đầu/cuối, không chứa lần ký bên cạnh?
3. `crop_review`: tay, mặt, thân liên quan có nằm trong khung gửi model?
4. Điền `reviewer` và `review_notes`, kể cả trường hợp chưa chắc chắn.

Giữ nguyên clip nguồn. Nếu cần sửa nhãn/đoạn cắt, tạo dataset candidate riêng,
có manifest ánh xạ trước/sau; không sửa validation/test hiện có. Technical audit
không tự điền phê duyệt nội dung VSL.

Chạy lại với thư mục báo cáo mới:

```bash
cd "/Users/macbook/Documents/Personal Library/VSign"
.venv-coreml/bin/python -m ml.scripts.audit_sales30_errors \
  --output-dir docs/reports/sales30-error-audit-rerun
```

## Kiểm tra đầu vào frontend

`probe_sales30_frontend` chọn một clip lỗi ngồi/từ trong 10 từ ưu tiên, kiểm
checksum, giải mã cùng 16 frame và gọi trực tiếp `frameEncoder.ts` của Vite
qua Chromium. So sánh worker/crop giữa, luồng chính/crop giữa và worker/toàn
khung; cả ba gửi WebSocket thật tới model đang chạy. Không sửa module encoder.

Đây là probe có chủ đích, không phải tỷ lệ chính xác đại diện. Nó không kiểm
cắt cử chỉ tự động, camera thật, tay mới hoặc câu liên tục. Kết quả của mỗi
biến thể nằm trong `frontend-input-probe.json` của báo cáo.

```bash
env PYTHONPATH=services/inference:. \
  VSIGN_PLAYWRIGHT_FROM=/Users/macbook/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json \
  .venv-coreml/bin/python -m ml.scripts.probe_sales30_frontend \
  --output docs/reports/frontend-input-probe-rerun.json
```

Cần backend 8000 và Vite 5173 đang chạy. PNG trung gian nằm trong thư mục tạm
và được dọn sau probe. Báo cáo chỉ giữ hash và reply, không giữ lại các PNG.

## Bộ test phiên mới

Đã chuẩn bị `ml/data/evaluation/sales30_coreml_camera_v1/`:

- `protocol.json`: model/hash/ngưỡng, kế hoạch, denylist, thời điểm bắt đầu.
- `annotations.csv`: danh sách 760 vị trí cần quay và điền kiểm định.
- `raw/`: chỉ MP4 + JSON mới, chưa có dữ liệu.
- `readiness.json`: trạng thái ban đầu, thiếu 760/760 mẫu.

Kế hoạch: 2 người khác nhau, mỗi người 2 phiên riêng; mỗi phiên 5 clip/từ
trên đủ 30 từ, tổng 600 positive. Mỗi phiên thêm 5 clip cho từng loại trong
8 negative, tổng 160: đứng yên, tay vào/ra, sửa tóc/kính, chạm mặt, quay thân,
chuyển động ngẫu nhiên, chồng tay và ký ngoài bộ 30 từ. Khoảng cách và ánh sáng
của từng vị trí được ghi trong CSV. Tay phải/trái là tay ký thực tế, không
ép người ký đổi tay chỉ để đủ kế hoạch.

Đây là test phiên quay mới, không phải mặc nhiên test người hoàn toàn mới.
Manifest train hiện còn `person=unknown`; công cụ sẽ giữ
`unseen_signer_verified=false` khi chưa có đủ danh tính lịch sử.
Không được dùng bộ này để train hoặc chọn checkpoint. Một model candidate
cần train/development khác; sau khi xem kết quả test nhiều lần, cần test mới
để xác nhận độc lập cho lần sửa tiếp theo.

### Thu riêng, không ghi vào personal-100 cũ

Nhân viên vận hành có thể dùng màn hình thu hiện có trên cặp server riêng.
Khách hàng tại quầy không cần thao tác web. Các lệnh dưới đây chỉ dành cho
phiên thu và **chưa được chạy** trong lần triển khai này. Kiểm tra cổng 8002,
5174 còn trống trước khi mở, không dừng backend 8000/frontend 5173.

Terminal backend, đổi `A1` thành `A2`, `B1`, `B2` cho từng phiên:

```bash
cd "/Users/macbook/Documents/Personal Library/VSign"
env INFERENCE_PORT=8002 \
  COLLECTION_DIR="$PWD/ml/data/evaluation/sales30_coreml_camera_v1/capture-inbox/A1" \
  bash scripts/run_coreml_local.sh
```

Terminal frontend:

```bash
cd "/Users/macbook/Documents/Personal Library/VSign/apps/web"
env VITE_INFERENCE_HTTP_URL=http://localhost:8002 \
  VITE_INFERENCE_WS_URL=ws://localhost:8002/ws/inference \
  npm run dev -- --host 127.0.0.1 --port 5174 --strictPort
```

Màn hình thu cũ vẫn dùng batch `personal-100`, quota 100/từ. Đường dẫn
`COLLECTION_DIR` mới tách hoàn toàn batch này khỏi batch train cũ; chưa có
quota 5 theo kế hoạch trong UI. Nhân viên đặt nhãn/điều kiện, theo dõi đếm
và dừng sau số cần thu. Mỗi phiên khởi tạo session mới, thực hiện ở thời điểm
riêng; không chỉ đổi UUID trên clip cũ.

Chỉ chuyển **bản sao** các cặp MP4/JSON mới đã chọn vào `raw/`, giữ nguyên
bản gốc trong inbox. Điền đường dẫn video tương đối với `raw/` vào cột
`video` đúng vị trí của `annotations.csv`, và điền `signer_id`, `label_review`,
`segmentation_review`, `reviewed_by`. Hai cột review chỉ là `approved` sau
khi người kiểm định thực sự xem clip. `signer_slot`/`session_slot` biểu diễn
lịch thu, không phải danh tính thật; điều kiện/nhãn trong metadata phải khớp
kế hoạch. Negative `other_sign` cần là cử chỉ ngoài 30 từ, không gán một từ
được hỗ trợ thành Không ký hiệu.

Audit và khóa bộ test:

```bash
cd "/Users/macbook/Documents/Personal Library/VSign"
.venv-coreml/bin/python -m ml.scripts.prepare_sales30_camera_evaluation audit
.venv-coreml/bin/python -m ml.scripts.prepare_sales30_camera_evaluation freeze
```

Exit `2` nghĩa là chưa đủ điều kiện, không tạo `frozen_manifest.json`. Công
cụ kiểm tra đủ vị trí, hash/phiên không trùng dữ liệu đã dùng, 2 người/4 phiên
khác nhau, video 224x224 giải mã được và khớp metadata, ít nhất 16 frame,
thời điểm mới, review hoàn tất. Video/JSON thừa trong `raw/` không bị bỏ qua
âm thầm. Không ghi đè báo cáo/manifest đã khóa.

Hash và timestamp không chống được mọi hình thức quay lại/nén lại clip cũ;
người vận hành phải xác nhận nguồn quay mới và danh tính. Công cụ chưa có
pipeline đo độ chính xác trên frozen set mới, vì chưa có clip để xác minh
pipeline đó. Chưa cho phép training/promotion từ readiness trống.

## Bước tiếp theo bắt buộc

Hoàn tất kiểm định các clip ưu tiên và quay test phiên mới. Sau đó mới chọn
thử nghiệm preprocessing/dataset/model candidate, benchmark trước/sau trên
cùng đầu vào, giữ checkpoint cũ và đánh giá camera thực tế. Không hạ ngưỡng
để che lỗi nhận nhầm; AI ghép câu không được tự sửa từ model đoán sai thành
từ nó cho là hợp ngữ cảnh.
