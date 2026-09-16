# VSign inference contract

`v1/` là contract version `1.0` dùng chung giữa web và inference service. `inference.ts`, `inference.py`, JSON Schema và examples mô tả cùng một protocol. Request luôn có đúng 16 ảnh JPEG/WebP dạng data URL. Server giữ nguyên `sequence` để client loại kết quả cũ hoặc sai thứ tự.

Giới hạn runtime mặc định: 256 KiB cho mỗi ảnh đã decode và 6 MiB cho toàn bộ WebSocket message. Các example chỉ minh hoạ cấu trúc; chuỗi ảnh rút gọn không phải ảnh hợp lệ để inference.
