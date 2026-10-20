export interface ReferenceSign {
  label: string;
  file: string;
}

export const REFERENCE_SIGNS: readonly ReferenceSign[] = [
  { label: "Chào", file: "01-chao.mp4" },
  { label: "Tôi", file: "02-toi.mp4" },
  { label: "Muốn", file: "03-muon.mp4" },
  { label: "Mua", file: "04-mua.mp4" },
  { label: "Cho", file: "05-cho.mp4" },
  { label: "Xem", file: "06-xem.mp4" },
  { label: "Thử", file: "07-thu.mp4" },
  { label: "Siêu thị", file: "08-sieu-thi.mp4" },
  { label: "Có", file: "09-co.mp4" },
  { label: "Cần", file: "10-can.mp4" },
  { label: "Điện thoại", file: "11-dien-thoai.mp4" },
  { label: "Laptop", file: "12-laptop.mp4" },
  { label: "Tivi", file: "13-tivi.mp4" },
  { label: "Tủ lạnh", file: "14-tu-lanh.mp4" },
  { label: "Máy giặt", file: "15-may-giat.mp4" },
  { label: "Nồi cơm điện", file: "16-noi-com-dien.mp4" },
  { label: "Gạo", file: "17-gao.mp4" },
  { label: "Sữa", file: "18-sua.mp4" },
  { label: "Cà phê", file: "19-ca-phe.mp4" },
  { label: "Mới", file: "20-moi.mp4" },
  { label: "Cũ", file: "21-cu.mp4" },
  { label: "Rẻ", file: "22-re.mp4" },
  { label: "Đắt", file: "23-dat.mp4" },
  { label: "Sử dụng", file: "24-su-dung.mp4" },
  { label: "Mua bán", file: "25-mua-ban.mp4" },
  { label: "Ngân hàng", file: "26-ngan-hang.mp4" },
  { label: "Cung cấp", file: "27-cung-cap.mp4" },
  { label: "Thay đổi", file: "28-thay-doi.mp4" },
  { label: "Từ chối", file: "29-tu-choi.mp4" },
  { label: "Cảm ơn", file: "30-cam-on.mp4" },
] as const;

const REFERENCE_VIDEO_REVISION = "20261009-1";

export function referenceVideoFor(label: string): string | null {
  const sign = REFERENCE_SIGNS.find((item) => item.label === label);
  return sign
    ? `${import.meta.env.BASE_URL}reference-videos/sales30/${sign.file}?v=${REFERENCE_VIDEO_REVISION}`
    : null;
}
