import { describe, expect, it } from "vitest";
import { calculateAdaptiveFraming, smoothCropRegion } from "./adaptiveFraming";

function handAround(x: number, y: number, size: number) {
  return [
    { x: x - size / 2, y: y - size / 2 },
    { x: x + size / 2, y: y + size / 2 },
    { x: x + size / 3, y: y - size / 3 },
  ];
}

describe("adaptive framing", () => {
  it("tự phóng người đứng xa nhưng vẫn tạo crop vuông theo pixel", () => {
    const framing = calculateAdaptiveFraming(
      [handAround(0.5, 0.48, 0.05)],
      1280,
      720,
    );
    expect(framing?.distance).toBe("too-far");
    expect(framing?.crop.height).toBeCloseTo(0.6);
    expect(framing!.crop.width * 1280).toBeCloseTo(
      framing!.crop.height * 720,
    );
  });

  it("giữ crop trong khung khi hai tay dang rộng", () => {
    const framing = calculateAdaptiveFraming(
      [handAround(0.12, 0.45, 0.11), handAround(0.88, 0.45, 0.11)],
      1280,
      720,
    );
    expect(framing).not.toBeNull();
    expect(framing!.crop.x).toBeGreaterThanOrEqual(0);
    expect(framing!.crop.x + framing!.crop.width).toBeLessThanOrEqual(1);
    expect(framing!.crop.y).toBeGreaterThanOrEqual(0);
    expect(framing!.crop.y + framing!.crop.height).toBeLessThanOrEqual(1);
  });

  it("không tạo crop khi chưa thấy tay", () => {
    expect(calculateAdaptiveFraming([], 1280, 720)).toBeNull();
  });

  it("làm mượt crop để khung AI không giật", () => {
    const crop = smoothCropRegion(
      { x: 0.1, y: 0.1, width: 0.5, height: 0.8 },
      { x: 0.3, y: 0.2, width: 0.7, height: 1 },
      0.5,
    );
    expect(crop.x).toBeCloseTo(0.2);
    expect(crop.y).toBeCloseTo(0.15);
    expect(crop.width).toBeCloseTo(0.6);
    expect(crop.height).toBeCloseTo(0.9);
  });
});
