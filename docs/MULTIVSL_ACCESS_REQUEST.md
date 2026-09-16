# Yêu cầu truy cập Multi-VSL đầy đủ

Địa chỉ được công bố trong bài báo WACV 2025:

- To: `son.dn22597@sis.hust.edu.vn`
- CC: `lenp@soict.hust.edu.vn`, `huy.hoangquang@hust.edu.vn`
- GitHub follow-up: [Issue #1 - Full dataset release](https://github.com/Etdihatthoc/Multi-VSL_WACV_2025/issues/1)

## Email tiếng Việt

**Tiêu đề:** Xin quyền truy cập full dataset, glossary và điều khoản sử dụng Multi-VSL

Kính gửi anh Sơn và nhóm tác giả Multi-VSL,

Tôi đang phát triển VSign, một prototype nhận dạng ký hiệu VSL rời rạc từ webcam và chuyển kết quả thành văn bản tiếng Việt. Tôi đã tích hợp checkpoint MViTv2-S 1.000 lớp được nhóm công bố và xác minh pipeline inference trên các video demo.

Để tiếp tục đánh giá/fine-tune đúng nhãn và đúng official split, nhờ nhóm hỗ trợ:

1. Quy trình xin quyền truy cập full Multi-VSL 84.764 video.
2. Glossary đầy đủ ánh xạ class ID `0–999` sang gloss tiếng Việt; nếu có, xin thêm tên tiếng Anh và biến thể vùng miền.
3. Xác nhận các CSV train/validation/test trong GitHub là official signer-independent split cuối cùng.
4. License hoặc Data Use Agreement cho dataset, video demo và checkpoint, bao gồm quyền dùng cho nghiên cứu/prototype và điều kiện public demo.
5. Quy định về trích dẫn, lưu trữ, bảo mật, thời hạn giữ dữ liệu và việc phân phối model đã fine-tune.

Thông tin mục đích sử dụng: `[điền mục đích học thuật/phi thương mại/thương mại]`. Dataset và checkpoint sẽ được giữ trong private storage, không commit vào Git và không phân phối lại nếu chưa được cho phép.

Xin cảm ơn nhóm tác giả.

Trân trọng,  
`[Họ tên]`  
`[Đơn vị / dự án]`  
`[Email]`

## English version

**Subject:** Request for full Multi-VSL dataset, gloss mapping, and usage terms

Dear Son and the Multi-VSL authors,

I am developing VSign, a prototype that recognizes isolated Vietnamese Sign Language signs from a webcam and presents the result as Vietnamese text. I have integrated the published 1,000-class MViTv2-S checkpoint and verified the inference pipeline on the public demo videos.

To evaluate and fine-tune the model using the correct labels and official split, could you please provide:

1. The access procedure for the complete Multi-VSL dataset of 84,764 videos.
2. The complete mapping from class IDs `0–999` to Vietnamese glosses, plus English names and regional variants if available.
3. Confirmation that the train/validation/test CSV files on GitHub are the final official signer-independent splits.
4. The dataset/checkpoint license or Data Use Agreement, including research/prototype use and public-demo conditions.
5. Citation, storage, security, retention, and fine-tuned-model redistribution requirements.

Intended use: `[academic/non-commercial/commercial - complete as appropriate]`. The data and checkpoints will remain in private storage and will not be committed or redistributed without permission.

Thank you for your work and support.

Best regards,  
`[Name]`  
`[Institution / project]`  
`[Email]`
