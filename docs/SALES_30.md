# Bộ từ bán hàng sales-30

`sales-30` là bộ nhãn mục tiêu mới cho thu thập dữ liệu và lần huấn luyện kế
tiếp. Model V3/V4/V5 hiện tại vẫn là checkpoint `common-20`; không được thay
file label map của các checkpoint đó bằng danh sách này vì index output không
khớp và sẽ làm sai kết quả dự đoán.

## 30 nhãn rời rạc

Danh sách chuẩn và thứ tự class nằm tại
`contracts/v1/sales30.labels.json`:

```text
Chào, Tôi, Muốn, Mua, Cho, Xem, Thử, Siêu thị, Có, Cần,
Điện thoại, Laptop, Tivi, Tủ lạnh, Máy giặt, Nồi cơm điện, Gạo, Sữa,
Cà phê, Mới, Cũ, Rẻ, Đắt, Sử dụng, Mua bán, Ngân hàng, Cung cấp,
Thay đổi, Từ chối,
Cảm ơn
```

Cả 30 nhãn đều có thư mục chính xác trong bộ công khai Kaggle
`nguyenanfms/vsl-vietnamese-sign-language-v2` version 8, license CC BY 4.0.
Pipeline chỉ dùng video canonical đã crop của VSL-472, không dùng Multi-VSL,
QIPEDC, raw video hay dữ liệu augmented. Video nguồn không được lưu trong Git;
manifest phải giữ nguyên test split của nguồn và đánh dấu development-only khi
không truy được signer cho toàn bộ clip.

## 20 ý định khách hàng

Các câu dưới đây là đầu ra câu tự nhiên mà tầng nối tiếp bằng AI có thể tạo từ
chuỗi từ rời rạc. AI được phép bổ sung hư từ như “này”, “nào”, “tiền”, “bằng”,
“thế nào” để câu tiếng Việt tự nhiên hơn.

1. Chào.
2. Điện thoại này đắt không?
3. Laptop này rẻ không?
4. Cho tôi xem tivi.
5. Tôi muốn mua tủ lạnh.
6. Tôi muốn thử máy giặt.
7. Nồi cơm điện này mới.
8. Điện thoại này cũ.
9. Siêu thị có gạo không?
10. Siêu thị có sữa không?
11. Cho tôi cà phê.
12. Tôi cần laptop.
13. Siêu thị có cung cấp máy giặt không?
14. Tôi muốn thanh toán qua ngân hàng.
15. Siêu thị có mua bán điện thoại cũ không?
16. Tôi muốn thay đổi tivi.
17. Tôi từ chối mua sản phẩm này.
18. Máy giặt sử dụng thế nào?
19. Cho tôi xem nồi cơm điện rẻ.
20. Cảm ơn.

## Trạng thái tích hợp

- API metadata trả riêng `labels` của model suy luận và `collection_labels`
  của `sales-30`.
- Màn hình **Thu dữ liệu AI** chỉ cho chọn 30 nhãn mới cộng với lớp negative
  `Không ký hiệu`.
- Mỗi nhãn đặt mục tiêu mặc định 50 mẫu tay phải và 50 mẫu tay trái; dữ liệu
  được lưu riêng tại `ml/data/collected/sales30/`.
- Video mẫu `common-20` chỉ hiện cho các nhãn trùng và vẫn được đánh dấu là
  tài sản legacy. Nhãn mới chưa có video tham chiếu sẽ hiện trạng thái chưa có
  mẫu.
- Chỉ chuyển runtime nhận dạng sang `sales-30` sau khi checkpoint 30 lớp đã
  được train, đánh giá và export cùng label map này.
