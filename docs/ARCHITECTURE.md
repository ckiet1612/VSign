# Kiến trúc increment local

Frontend giữ camera và transcript trong trình duyệt. Khi inference server kết nối, capture hook dùng khung vuông cố định ở giữa và chọn đều 16 mốc thời gian để khớp preprocessing lúc train, sau đó resize/encode ảnh và gửi message contract v1. Chế độ thu dữ liệu Sales30 dùng cùng pipeline RGB này; model landmark trong browser giữ crop thích ứng và motion-weighted sampling làm fallback khi server không sẵn sàng. `sequence` tăng đơn điệu theo session; reducer chỉ nhận prediction trùng sequence đang chờ.

Tracking có hai nhánh riêng: kết quả MediaPipe gốc dùng cho feature, presence
mask, crop và điều kiện thu; `TrackingDisplayFilter` chỉ cung cấp điểm để vẽ.
Nhánh hiển thị dùng lọc One Euro thích ứng và ghép từng tay theo quỹ đạo cổ
tay/handedness để giữ màu khi detector đảo thứ tự. Khi mất detection, chỉ giữ
điểm đã quan sát và làm mờ tối đa 150 ms, không dựng thêm ngón hoặc tính điểm
giữ tạm là detection mới. Vòng vẽ chạy bằng animation-frame riêng nên điểm hết
hạn cả khi video tạm dừng. Thời gian hiển thị tính từ lúc detector trả kết quả;
timestamp capture vẫn giữ nguyên. Tắt camera, tháo overlay hoặc lỗi detector
xóa lịch sử hiển thị; thay đổi này không đổi model, ngưỡng hay preprocessing.

Chế độ thêm từ độc lập với cách thu ký hiệu và mặc định là thủ công. Khi người
dùng bật tự động, mỗi lượt mới mang token generation/context từ lúc bắt đầu thu;
token chỉ dùng một lần khi nhận phản hồi hợp lệ, trước khi FIFO gửi request tiếp
theo. Đổi lựa chọn thêm từ hoặc hủy context làm mất hiệu lực token cũ, kể cả clip
chưa encode xong. Chỉ nhận `ok` của model thật với nhãn thuộc label map đã xác
minh và đúng `model_version`; không thêm idle hoặc phản hồi của luồng thu dữ liệu.
Transcript giữ cooldown 1 giây, hoàn tác/xóa/sao chép và không tự gọi API câu.

Inference service kiểm tra origin, message schema, số frame, MIME, base64, byte size, pixel dimensions và decode ảnh trước khi giữ inference slot. Slot duy nhất không có queue: request hợp lệ đến khi slot bị khóa nhận ngay `busy`. Công việc decode/model chạy ngoài event loop; một exception chỉ tạo response `error`, không log raw payload và không đóng WebSocket nếu kết nối còn dùng được.

`InferenceBackend` là biên thay thế runtime:

- `MockInferenceBackend`: mặc định, deterministic và chỉ dùng candidate display labels chưa xác minh.
- `ONNXInferenceBackend`: được tạo duy nhất khi `INFERENCE_BACKEND=onnx`; preprocess `[1,C,T,H,W]`, ImageNet normalization, softmax/top 3 và reject theo confidence/margin.

`POST /sentence/compose` chỉ nhận tối đa 30 từ thuộc vocabulary Sales30. Server dùng OpenAI Responses khi có đủ `OPENAI_API_KEY` + `OPENAI_MODEL`; lỗi provider hoặc thiếu cấu hình đều rơi về composer cục bộ và không làm gián đoạn nhận diện.

Frontend và inference service không lưu video camera. Việc tải/chuẩn bị
ViSignLanguage-Video chạy tách biệt trong `ml/scripts/` và chỉ ghi vào
`ml/data/raw/`, là thư mục bị Git ignore. Runtime chỉ được nhận một label map khi
hash, số lớp và phiên bản preprocessing của nó khớp checkpoint tương ứng.
