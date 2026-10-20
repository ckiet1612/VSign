import { describe, expect, it } from "vitest";
import * as cameraGeometry from "./cameraGeometry";

const { containedVideoRect, mirroredDisplayPoint } = cameraGeometry;

describe("camera geometry", () => {
  it("giữ toàn bộ khung 16:9 trong vùng xem cao hơn", () => {
    expect(containedVideoRect(960, 600, 1280, 720)).toEqual({
      x: 0,
      y: 30,
      width: 960,
      height: 540,
    });
  });

  it("đổi tọa độ camera sang tọa độ preview đã soi gương", () => {
    const rect = { x: 10, y: 20, width: 800, height: 450 };
    expect(mirroredDisplayPoint({ x: 0.25, y: 0.4 }, rect)).toEqual({
      x: 610,
      y: 200,
    });
  });

  it("chặn landmark ngoài biên để lớp vẽ không tràn", () => {
    const rect = { x: 0, y: 0, width: 100, height: 50 };
    expect(mirroredDisplayPoint({ x: -0.2, y: 1.4 }, rect)).toEqual({
      x: 100,
      y: 50,
    });
  });

  it("tính đúng center-square hiển thị cho camera dọc", () => {
    const centeredSquareRect = (
      cameraGeometry as typeof cameraGeometry & {
        centeredSquareRect?: (rect: {
          x: number;
          y: number;
          width: number;
          height: number;
        }) => { x: number; y: number; width: number; height: number };
      }
    ).centeredSquareRect;
    const videoRect = containedVideoRect(960, 540, 720, 1280);

    expect(centeredSquareRect).toBeTypeOf("function");
    expect(centeredSquareRect!(videoRect)).toEqual({
      x: 328.125,
      y: 118.125,
      width: 303.75,
      height: 303.75,
    });
  });
});
