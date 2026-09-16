import { describe, expect, it } from "vitest";
import {
  MAX_CAPTURE_MS,
  MIN_CAPTURE_MS,
  motionWeightedSampleIndices,
  uniformSample,
  validateCaptureDuration,
} from "./sampling";

describe("uniformSample", () => {
  it("luôn trả đúng 16 frame và giữ hai đầu clip", () => {
    const source = Array.from({ length: 39 }, (_, index) => index);
    const sampled = uniformSample(source, 16);
    expect(sampled).toHaveLength(16);
    expect(sampled[0]).toBe(0);
    expect(sampled.at(-1)).toBe(38);
    expect(sampled).toEqual([...sampled].sort((a, b) => a - b));
  });

  it("lặp đều frame khi nguồn ít hơn 16", () => {
    expect(uniformSample(["a", "b", "c"], 16)).toHaveLength(16);
  });
});

describe("motionWeightedSampleIndices", () => {
  it("giữ hai đầu, đúng thứ tự và luôn lấy chuyển động mạnh nhất", () => {
    const motion = new Array<number>(50).fill(0.01);
    motion[31] = 1;
    const sampled = motionWeightedSampleIndices(50, 16, motion);
    expect(sampled).toHaveLength(16);
    expect(sampled[0]).toBe(0);
    expect(sampled.at(-1)).toBe(49);
    expect(sampled).toContain(31);
    expect(new Set(sampled).size).toBe(16);
    expect(sampled).toEqual([...sampled].sort((a, b) => a - b));
  });

  it("quay về lấy mẫu đều khi không có chuyển động", () => {
    expect(motionWeightedSampleIndices(39, 16, new Array(39).fill(0))).toEqual(
      Array.from({ length: 16 }, (_, index) => Math.round((index * 38) / 15)),
    );
  });
});

describe("validateCaptureDuration", () => {
  it("từ chối clip quá ngắn", () => {
    expect(validateCaptureDuration(MIN_CAPTURE_MS - 1)).toEqual({
      valid: false,
      message: expect.stringContaining("Giữ lâu hơn"),
    });
  });

  it("chấp nhận clip trong khoảng cho phép", () => {
    expect(validateCaptureDuration(MAX_CAPTURE_MS).valid).toBe(true);
  });
});
