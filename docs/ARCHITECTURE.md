# Kiến trúc increment local

Frontend giữ camera và transcript hoàn toàn trong trình duyệt. Khi người dùng thả nút, capture hook chọn đúng 16 mốc thời gian, resize/encode ảnh và gửi một message contract v1. `sequence` tăng đơn điệu theo session; reducer chỉ nhận prediction trùng sequence đang chờ.

Inference service kiểm tra origin, message schema, số frame, MIME, base64, byte size, pixel dimensions và decode ảnh trước khi giữ inference slot. Slot duy nhất không có queue: request hợp lệ đến khi slot bị khóa nhận ngay `busy`. Công việc decode/model chạy ngoài event loop; một exception chỉ tạo response `error`, không log raw payload và không đóng WebSocket nếu kết nối còn dùng được.

`InferenceBackend` là biên thay thế runtime:

- `MockInferenceBackend`: mặc định, deterministic và chỉ dùng candidate display labels chưa xác minh.
- `ONNXInferenceBackend`: được tạo duy nhất khi `INFERENCE_BACKEND=onnx`; preprocess `[1,C,T,H,W]`, ImageNet normalization, softmax/top 3 và reject theo confidence/margin.

Frontend và inference service không lưu video camera. Việc tải/chuẩn bị
ViSignLanguage-Video chạy tách biệt trong `ml/scripts/` và chỉ ghi vào
`ml/data/raw/`, là thư mục bị Git ignore. Runtime chỉ được nhận một label map khi
hash, số lớp và phiên bản preprocessing của nó khớp checkpoint tương ứng.
