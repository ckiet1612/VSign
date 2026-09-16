export interface ReferenceSign {
  label: string;
  file: string;
}

export const REFERENCE_SIGNS: readonly ReferenceSign[] = [
  { label: "Chào", file: "01-chao.mp4" },
  { label: "Cảm ơn", file: "02-cam-on.mp4" },
  { label: "Xin lỗi", file: "03-xin-loi.mp4" },
  { label: "Tôi", file: "04-toi.mp4" },
  { label: "Đi", file: "05-di.mp4" },
  { label: "Uống", file: "06-uong.mp4" },
  { label: "Ăn", file: "07-an.mp4" },
  { label: "Nhà", file: "08-nha.mp4" },
  { label: "Trường học", file: "09-truong-hoc.mp4" },
  { label: "Bệnh viện", file: "10-benh-vien.mp4" },
  { label: "Giúp", file: "11-giup.mp4" },
  { label: "Đồng ý", file: "12-dong-y.mp4" },
  { label: "Nói", file: "13-noi.mp4" },
  { label: "Nghe", file: "14-nghe.mp4" },
  { label: "Mua", file: "15-mua.mp4" },
  { label: "Đâu", file: "16-dau.mp4" },
  { label: "Nhìn", file: "17-nhin.mp4" },
  { label: "Cho", file: "18-cho.mp4" },
  { label: "Biết", file: "19-biet.mp4" },
  { label: "Có thể", file: "20-co-the.mp4" },
] as const;

const REFERENCE_VIDEO_REVISION = "20260910-2";

export function referenceVideoFor(label: string): string | null {
  const sign = REFERENCE_SIGNS.find((item) => item.label === label);
  return sign
    ? `${import.meta.env.BASE_URL}reference-videos/common20/${sign.file}?v=${REFERENCE_VIDEO_REVISION}`
    : null;
}
