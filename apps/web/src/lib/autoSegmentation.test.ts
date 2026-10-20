import { describe, expect, it } from "vitest";
import {
  AutomaticSignSegmenter,
  landmarkMotion,
  SPECULATE_AFTER_MS,
  type AutomaticSegmentUpdate,
} from "./autoSegmentation";
import {
  emptyLandmarkFrame,
  HAND_GLOBAL_OFFSET,
  HAND_PRESENCE_OFFSET,
  POSE_COORDINATE_OFFSET,
  POSE_PRESENCE_OFFSET,
} from "./landmarkFeatures";

function handFrame(x: number, y = 0.5): number[] {
  const frame = emptyLandmarkFrame();
  for (let point = 0; point < 21; point += 1) {
    frame[point * 3] = x + point * 0.001;
    frame[point * 3 + 1] = y;
  }
  frame[HAND_GLOBAL_OFFSET] = x;
  frame[HAND_GLOBAL_OFFSET + 1] = y;
  frame[HAND_PRESENCE_OFFSET] = 1;
  return frame;
}

function armPoseFrame(x: number): number[] {
  const frame = emptyLandmarkFrame();
  for (let point = 7; point <= 10; point += 1) {
    const offset = POSE_COORDINATE_OFFSET + point * 3;
    frame[offset] = x;
    frame[offset + 1] = 0.5;
    frame[POSE_PRESENCE_OFFSET + point] = 1;
  }
  return frame;
}

function runCompleteSign(frameIntervalMs: number): number[][] | null {
  const segmenter = new AutomaticSignSegmenter();
  segmenter.reset(true);
  let timestamp = 0;
  for (; timestamp < 300; timestamp += frameIntervalMs) {
    segmenter.push(emptyLandmarkFrame(), timestamp);
  }
  const movementStartedAt = timestamp;
  let sequence: number[][] | null = null;
  for (; timestamp - movementStartedAt < 850; timestamp += frameIntervalMs) {
    const elapsed = timestamp - movementStartedAt;
    const update = segmenter.push(
      handFrame(0.2 + (elapsed / 1000) * 0.5),
      timestamp,
    );
    sequence = update.sequence ?? sequence;
  }
  for (let index = 0; index < 30 && !sequence; index += 1) {
    const update = segmenter.push(handFrame(0.625), timestamp);
    sequence = update.sequence ?? sequence;
    timestamp += frameIntervalMs;
  }
  return sequence;
}

describe("automatic sign segmentation", () => {
  it("đo chuyển động từ các điểm ổn định trên bàn tay", () => {
    expect(landmarkMotion(handFrame(0.3), handFrame(0.32))).toBeCloseTo(0.02);
    expect(landmarkMotion(emptyLandmarkFrame(), handFrame(0.3))).toBe(0.05);
  });

  it("tiếp tục đo chuyển động bằng khuỷu/cổ tay pose khi bàn tay bị che", () => {
    expect(landmarkMotion(armPoseFrame(0.3), armPoseFrame(0.34))).toBeCloseTo(
      0.04,
    );
  });

  it("không kết thúc sớm khi tay chi tiết bị che nhưng pose vẫn liên tục", () => {
    const segmenter = new AutomaticSignSegmenter();
    segmenter.reset(true);
    let timestamp = 0;
    segmenter.push(emptyLandmarkFrame(), timestamp);
    for (let index = 0; index < 18; index += 1) {
      timestamp += 35;
      segmenter.push(handFrame(0.2 + index * 0.018), timestamp);
    }
    for (let index = 0; index < 10; index += 1) {
      timestamp += 35;
      const update = segmenter.push(armPoseFrame(0.55 + index * 0.018), timestamp);
      expect(update.sequence).toBeNull();
      expect(update.phase).toBe("capturing");
    }
  });

  it("không tạo ký hiệu khi không thấy tay", () => {
    const segmenter = new AutomaticSignSegmenter();
    segmenter.reset(true);
    for (let index = 0; index < 100; index += 1) {
      const update = segmenter.push(emptyLandmarkFrame(), index * 30);
      expect(update.sequence).toBeNull();
    }
    expect(segmenter.phase).toBe("waiting");
  });

  it("không bắt đầu khi chỉ cơ thể và cánh tay chuyển động", () => {
    const segmenter = new AutomaticSignSegmenter();
    segmenter.reset(true);
    for (let index = 0; index < 80; index += 1) {
      const update = segmenter.push(
        armPoseFrame(0.2 + index * 0.02),
        index * 35,
      );
      expect(update.sequence).toBeNull();
      expect(update.phase).toBe("waiting");
    }
  });

  it("bỏ qua một frame tay nhiễu thay vì thu nhầm", () => {
    const segmenter = new AutomaticSignSegmenter();
    segmenter.reset(true);
    for (let index = 0; index < 12; index += 1) {
      segmenter.push(emptyLandmarkFrame(), index * 35);
    }
    segmenter.push(handFrame(0.3), 420);
    for (let index = 0; index < 20; index += 1) {
      const update = segmenter.push(emptyLandmarkFrame(), 455 + index * 35);
      expect(update.sequence).toBeNull();
    }
    expect(segmenter.phase).toBe("waiting");
  });

  it("giữ hành vi nhất quán ở cả 15 FPS và 30 FPS", () => {
    expect(runCompleteSign(33)).toHaveLength(16);
    expect(runCompleteSign(67)).toHaveLength(16);
  });

  it("không cắt ở một khoảng dừng ngắn giữa ký hiệu", () => {
    const segmenter = new AutomaticSignSegmenter();
    segmenter.reset(true);
    let timestamp = 0;
    for (let index = 0; index < 12; index += 1) {
      segmenter.push(emptyLandmarkFrame(), timestamp);
      timestamp += 40;
    }
    for (let index = 0; index < 18; index += 1) {
      const update = segmenter.push(handFrame(0.2 + index * 0.014), timestamp);
      expect(update.sequence).toBeNull();
      timestamp += 40;
    }
    for (let index = 0; index < 13; index += 1) {
      const update = segmenter.push(handFrame(0.438), timestamp);
      expect(update.sequence).toBeNull();
      timestamp += 40;
    }
    let resumed = false;
    for (let index = 0; index < 6; index += 1) {
      const update = segmenter.push(handFrame(0.438 + index * 0.014), timestamp);
      resumed ||= update.phase === "capturing";
      expect(update.sequence).toBeNull();
      timestamp += 40;
    }
    expect(resumed).toBe(true);
  });

  it("luôn kết thúc một chuyển động liên tục ở giới hạn an toàn", () => {
    const segmenter = new AutomaticSignSegmenter();
    segmenter.reset(true);
    let timestamp = 0;
    let sequence: number[][] | null = null;
    segmenter.push(emptyLandmarkFrame(), timestamp);
    for (let index = 0; index < 120 && !sequence; index += 1) {
      timestamp += 35;
      const update = segmenter.push(handFrame(0.2 + index * 0.012), timestamp);
      sequence = update.sequence ?? sequence;
    }
    expect(sequence).toHaveLength(16);
    expect(timestamp).toBeLessThan(3_500);
  });

  it("giữ pre-roll, tự kết thúc khi tay đứng yên và lấy đúng 16 frame", () => {
    const segmenter = new AutomaticSignSegmenter();
    segmenter.reset(true);
    let timestamp = 0;
    for (let index = 0; index < 20; index += 1) {
      segmenter.push(emptyLandmarkFrame(), timestamp);
      timestamp += 30;
    }
    let sequence: number[][] | null = null;
    for (let index = 0; index < 24; index += 1) {
      const update = segmenter.push(handFrame(0.2 + index * 0.015), timestamp);
      sequence = update.sequence ?? sequence;
      timestamp += 30;
    }
    for (let index = 0; index < 30 && !sequence; index += 1) {
      const update = segmenter.push(handFrame(0.545), timestamp);
      sequence = update.sequence ?? sequence;
      timestamp += 30;
    }
    expect(sequence).toHaveLength(16);
    expect(segmenter.phase).toBe("waiting");
    expect(
      sequence?.some((frame) => frame[HAND_PRESENCE_OFFSET] > 0.5),
    ).toBe(true);
    expect(sequence?.every((frame) => frame[HAND_PRESENCE_OFFSET] > 0.5)).toBe(
      true,
    );
  });

  it("loại frame trống ở cuối khi tay rời khỏi camera", () => {
    const segmenter = new AutomaticSignSegmenter();
    segmenter.reset(true);
    let timestamp = 0;
    segmenter.push(emptyLandmarkFrame(), timestamp);
    for (let index = 0; index < 20; index += 1) {
      timestamp += 50;
      segmenter.push(handFrame(0.2 + index * 0.02), timestamp);
    }
    let sequence: number[][] | null = null;
    for (let index = 0; index < 20; index += 1) {
      timestamp += 50;
      const update = segmenter.push(emptyLandmarkFrame(), timestamp);
      sequence = update.sequence ?? sequence;
    }
    expect(sequence).toHaveLength(16);
    expect(sequence?.every((frame) => frame[HAND_PRESENCE_OFFSET] > 0.5)).toBe(
      true,
    );
  });

  it("không phát lại một đoạn ngắn ngay sau ký hiệu đã kết thúc", () => {
    const segmenter = new AutomaticSignSegmenter();
    segmenter.reset(true);
    let timestamp = 0;
    segmenter.push(emptyLandmarkFrame(), timestamp);
    for (let index = 0; index < 25; index += 1) {
      timestamp += 40;
      segmenter.push(handFrame(0.2 + index * 0.014), timestamp);
    }
    let emitted = false;
    for (let index = 0; index < 26; index += 1) {
      timestamp += 40;
      const update = segmenter.push(handFrame(0.55), timestamp);
      emitted ||= Boolean(update.sequence);
    }
    expect(emitted).toBe(true);
    for (let index = 0; index < 10; index += 1) {
      timestamp += 40;
      const update = segmenter.push(handFrame(0.3 + index * 0.03), timestamp);
      expect(update.sequence).toBeNull();
    }
  });

  it.each([33, 50, 67])("thu đủ 6 ký hiệu nghỉ 1 giây ở nhịp frame %i ms", (interval) => {
    const segmenter = new AutomaticSignSegmenter();
    segmenter.reset(true);
    let timestamp = 0;
    const emitted: number[][][] = [];
    const push = (x: number) => {
      const update = segmenter.push(handFrame(x), timestamp);
      if (update.sequence) emitted.push(update.sequence);
      timestamp += interval;
    };
    while (timestamp < 800) push(0.2);
    for (let sign = 0; sign < 6; sign += 1) {
      expect(segmenter.phase).toBe("waiting");
      const start = timestamp;
      const from = sign % 2 ? 0.7 : 0.2;
      const direction = sign % 2 ? -1 : 1;
      while (timestamp - start < 1000) {
        push(from + direction * 0.5 * ((timestamp - start) / 1000));
      }
      const restingAt = timestamp;
      const stop = sign % 2 ? 0.2 : 0.7;
      while (timestamp - restingAt < 1000) push(stop);
      expect(emitted).toHaveLength(sign + 1);
    }
    expect(emitted.every((sequence) => sequence.length === 16)).toBe(true);
  });

  it("không thu lặp một chuyển động dài cho đến khi quan sát khoảng nghỉ thật", () => {
    const segmenter = new AutomaticSignSegmenter();
    segmenter.reset(true);
    let emitted = 0;
    segmenter.push(handFrame(0.2), 0);
    for (let index = 1; index <= 240; index += 1) {
      const update = segmenter.push(handFrame(0.2 + index * 0.02), index * 50);
      emitted += Number(Boolean(update.sequence));
      if (emitted) expect(update.phase).not.toBe("waiting");
    }
    expect(emitted).toBe(1);
    expect(segmenter.phase).toBe("rearming");
    for (let index = 241; index <= 248; index += 1) {
      segmenter.push(handFrame(5), index * 50);
    }
    expect(segmenter.phase).toBe("waiting");
  });

  it("không báo sẵn sàng khi reset yêu cầu người ký nghỉ tay", () => {
    const segmenter = new AutomaticSignSegmenter();
    segmenter.reset(true, true);
    expect(segmenter.phase).toBe("rearming");
    for (let index = 0; index < 40; index += 1) {
      const update = segmenter.push(handFrame(0.2 + index * 0.025), index * 50);
      expect(update.sequence).toBeNull();
      expect(update.phase).not.toBe("capturing");
      if (index >= 2) expect(update.phase).toBe("rearming");
    }
    for (let index = 40; index < 49; index += 1) {
      segmenter.push(handFrame(1.175), index * 50);
    }
    expect(segmenter.phase).toBe("waiting");
  });
});

describe("provisional segments (start inference as the hands come to rest)", () => {
  function sign(segmenter: AutomaticSignSegmenter, start: number, pauseMs: number) {
    const updates: Array<AutomaticSegmentUpdate & { at: number }> = [];
    let timestamp = start;
    const push = (x: number) => {
      updates.push({ ...segmenter.push(handFrame(x), timestamp), at: timestamp });
      timestamp += 33;
    };
    while (timestamp < start + 300) push(0.2);
    const moveFrom = timestamp;
    while (timestamp < moveFrom + 850) push(0.2 + ((timestamp - moveFrom) / 1000) * 0.5);
    const restFrom = timestamp;
    while (timestamp < restFrom + pauseMs) push(0.625);
    return { updates, restFrom, end: timestamp };
  }

  it("emits once after a short rest and confirms that exact segment at the end", () => {
    const segmenter = new AutomaticSignSegmenter();
    segmenter.reset(true);
    segmenter.setSpeculation(true);
    const { updates, restFrom } = sign(segmenter, 0, 1200);
    const provisional = updates.filter((update) => update.provisional);
    expect(provisional).toHaveLength(1);
    // Median motion smoothing adds a frame or two before the rest is seen.
    expect(provisional[0].at - restFrom).toBeGreaterThanOrEqual(SPECULATE_AFTER_MS);
    expect(provisional[0].at - restFrom).toBeLessThan(SPECULATE_AFTER_MS + 150);
    const final = updates.find((update) => update.sequence)!;
    expect(final.confirmedProvisional).toBe(provisional[0].provisional!.id);
    expect(final.sequence).toEqual(provisional[0].provisional!.sequence);
    expect(final.sourceWindow).toEqual(provisional[0].provisional!.sourceWindow);
    // The result is available ~0.5 s before the sign is declared finished.
    expect(final.at - provisional[0].at).toBeGreaterThan(400);
  });

  it("cancels the provisional segment when the hands move again and re-speculates later", () => {
    const segmenter = new AutomaticSignSegmenter();
    segmenter.reset(true);
    segmenter.setSpeculation(true);
    const first = sign(segmenter, 0, 260);
    const firstId = first.updates.find((update) => update.provisional)!.provisional!.id;
    let timestamp = first.end;
    const after: AutomaticSegmentUpdate[] = [];
    for (let index = 0; index < 12; index += 1, timestamp += 33) {
      after.push(segmenter.push(handFrame(0.625 - index * 0.03), timestamp));
    }
    expect(after.some((update) => update.provisionalCancelled === firstId)).toBe(true);
    for (let index = 0; index < 40; index += 1, timestamp += 33) {
      after.push(segmenter.push(handFrame(0.265), timestamp));
    }
    const second = after.find((update) => update.provisional)!.provisional!;
    expect(second.id).toBeGreaterThan(firstId);
    const final = after.find((update) => update.sequence)!;
    expect(final.confirmedProvisional).toBe(second.id);
  });

  it("does nothing when speculation is off, keeping landmark segments unchanged", () => {
    const off = new AutomaticSignSegmenter();
    off.reset(true);
    const { updates } = sign(off, 0, 1200);
    expect(updates.some((update) => update.provisional || update.confirmedProvisional)).toBe(false);
    const final = updates.find((update) => update.sequence)!;
    // Without speculation the segment still runs through the whole rest and post-roll.
    expect(final.sourceWindow!.endAt).toBe(final.at);
  });
});
