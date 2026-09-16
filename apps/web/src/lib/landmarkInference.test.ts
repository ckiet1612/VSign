import { describe, expect, it } from "vitest";
import {
  averageLogitViews,
  flattenLandmarkBatch,
  flattenLandmarkSequence,
  mirrorLandmarkSequence,
  predictionFromLogits,
  selectFocusedExpertLogits,
  weightedLogitEnsemble,
} from "./landmarkInference";
import {
  emptyLandmarkFrame,
  HAND_PRESENCE_OFFSET,
  LANDMARK_FEATURE_DIM,
  POSE_PRESENCE_OFFSET,
} from "./landmarkFeatures";

function detectedFrame(): number[] {
  const frame = emptyLandmarkFrame();
  frame[HAND_PRESENCE_OFFSET] = 1;
  return frame;
}

describe("landmark inference helpers", () => {
  it("tạo tensor đúng kích thước", () => {
    const sequence = Array.from({ length: 16 }, detectedFrame);
    const flattened = flattenLandmarkSequence(sequence);
    expect(flattened).toHaveLength(16 * LANDMARK_FEATURE_DIM);
    expect(flattenLandmarkBatch([sequence, sequence])).toHaveLength(
      2 * 16 * LANDMARK_FEATURE_DIM,
    );
  });

  it("lật trái-phải và giữ thứ tự hai bàn tay nhất quán", () => {
    const frame = detectedFrame();
    frame[0] = 0.2;
    frame[63] = 0.7;
    frame[HAND_PRESENCE_OFFSET + 1] = 1;
    const mirrored = mirrorLandmarkSequence(
      Array.from({ length: 16 }, () => frame),
    );
    expect(mirrored[0][0]).toBeCloseTo(-0.7);
    expect(mirrored[0][63]).toBeCloseTo(-0.2);
    expect(
      mirrored[0].slice(HAND_PRESENCE_OFFSET, HAND_PRESENCE_OFFSET + 2),
    ).toEqual([1, 1]);
  });

  it("lấy trung bình logits của các góc nhìn", () => {
    expect(averageLogitViews([4, 2, 2, 4], 2, 2)).toEqual([3, 3]);
  });

  it("ưu tiên model khung hình chính nhưng chuẩn hóa thang logits", () => {
    const combined = weightedLogitEnsemble([
      { logits: [10, 8, 6], weight: 0.35 },
      { logits: [1, 5, 0], weight: 0.65 },
    ]);
    expect(combined[1]).toBeGreaterThan(combined[0]);
  });

  it("chỉ cho chuyên gia Trường học can thiệp khi kết quả đủ rõ", () => {
    const labels = ["Chào", "Trường học", "Ăn"];
    expect(
      selectFocusedExpertLogits(
        [5, 1, 0],
        [0, 5, 1],
        labels,
        ["Chào", "Trường học"],
        { confidence: 0.5, margin: 0.16 },
      ),
    ).toEqual([0, 5, 1]);
    expect(
      selectFocusedExpertLogits(
        [5, 1, 0],
        [0, 1, 5],
        labels,
        ["Chào", "Trường học"],
        { confidence: 0.5, margin: 0.16 },
      ),
    ).toEqual([5, 1, 0]);
  });

  it("trả no_hands khi quá ít frame phát hiện tay", () => {
    const prediction = predictionFromLogits(
      [5, 1],
      ["Chào", "Cảm ơn"],
      Array.from({ length: 16 }, emptyLandmarkFrame),
      7,
    );
    expect(prediction.status).toBe("no_hands");
    expect(prediction.label).toBeNull();
  });

  it("không coi frame chỉ có vai và cánh tay là frame bàn tay", () => {
    const poseOnly = emptyLandmarkFrame();
    for (let point = 5; point <= 10; point += 1) {
      poseOnly[POSE_PRESENCE_OFFSET + point] = 1;
    }
    const prediction = predictionFromLogits(
      [8, 1],
      ["Chào", "Cảm ơn"],
      Array.from({ length: 16 }, () => poseOnly),
      8,
    );
    expect(prediction.status).toBe("no_hands");
  });

  it("nhận kết quả rõ và giữ top 3", () => {
    const prediction = predictionFromLogits(
      [5, 1, 0, -1],
      ["Chào", "Cảm ơn", "Cho", "Biết"],
      Array.from({ length: 16 }, detectedFrame),
      9,
    );
    expect(prediction.status).toBe("ok");
    expect(prediction.label).toBe("Chào");
    expect(prediction.top_k).toHaveLength(3);
  });

  it("dùng ngưỡng nghiêm hơn cho chế độ tự động", () => {
    const prediction = predictionFromLogits(
      [2, 1.6],
      ["Uống", "Ăn"],
      Array.from({ length: 16 }, detectedFrame),
      10,
      { confidence: 0.62, margin: 0.24 },
    );
    expect(prediction.status).toBe("uncertain");
  });

  it("biến lớp Không ký hiệu thành uncertain thay vì thêm vào câu", () => {
    const prediction = predictionFromLogits(
      [1, 0, 6],
      ["Uống", "Ăn", "Không ký hiệu"],
      Array.from({ length: 16 }, detectedFrame),
      11,
    );
    expect(prediction.status).toBe("uncertain");
    expect(prediction.label).toBeNull();
    expect(prediction.top_k.map((item) => item.label)).not.toContain("Không ký hiệu");
  });
});
