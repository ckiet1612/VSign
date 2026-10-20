import { describe, expect, it } from "vitest";
import golden from "../../../../contracts/v1/framing_golden.json";
import {
  BODY_FRAMING_VERSION,
  BodyBoxTracker,
  bodyBox,
  drawPlan,
  framingFrame,
  trimSpan,
  type FramingFrame,
} from "./bodyFraming";

interface GoldenCase {
  name: string;
  width: number;
  height: number;
  frames: FramingFrame[];
  expected: { span: [number, number]; box: Record<string, number> | null };
}

function expectBox(actual: Record<string, number> | null, expected: Record<string, number> | null) {
  if (expected === null) {
    expect(actual).toBeNull();
    return;
  }
  expect(actual).not.toBeNull();
  for (const key of ["x", "y", "width", "height"]) {
    expect(actual![key]).toBeCloseTo(expected[key], 9);
  }
}

describe("trim-bodycrop-v1 matches ml/body_framing.py", () => {
  it("uses the same version as the golden file", () => {
    expect(golden.version).toBe(BODY_FRAMING_VERSION);
  });

  for (const testCase of golden.cases as unknown as GoldenCase[]) {
    it(`span and box: ${testCase.name}`, () => {
      expect(trimSpan(testCase.frames, testCase.width, testCase.height)).toEqual(testCase.expected.span);
      expectBox(
        bodyBox(testCase.frames, testCase.width, testCase.height) as Record<string, number> | null,
        testCase.expected.box,
      );
    });
  }

  it("draw plans", () => {
    for (const item of golden.draw_plans) {
      const plan = drawPlan(item.box, item.width, item.height, item.size);
      if (item.expected === null) {
        expect(plan).toBeNull();
        continue;
      }
      const [x, y, width, height] = item.expected.source;
      expect(plan!.source.x).toBeCloseTo(x, 9);
      expect(plan!.source.y).toBeCloseTo(y, 9);
      expect(plan!.source.width).toBeCloseTo(width, 9);
      expect(plan!.source.height).toBeCloseTo(height, 9);
      const destination = plan!.destination;
      expect([destination.x, destination.y, destination.width, destination.height]).toEqual(item.expected.destination);
    }
  });
});

describe("live helpers", () => {
  const shoulders = (t: number) => framingFrame(t, [], Array.from({ length: 33 }, (_, index) => ({
    x: index === 11 ? 0.6 : index === 12 ? 0.4 : 0.5,
    y: 0.5,
    visibility: 0.99,
  })));

  it("packs pose and hand extents in image space", () => {
    const frame = framingFrame(5, [[{ x: 0.2, y: 0.3 }, { x: 0.1, y: 0.5 }, { x: 0.25, y: 0.2 }]], null);
    expect(frame).toEqual({ t: 5, pose: null, hands: [[0.2, 0.3, 0.1, 0.2, 0.25, 0.5]] });
    expect(shoulders(0).pose).toHaveLength(7);
  });

  it("tracks the box over the recent window only", () => {
    const tracker = new BodyBoxTracker();
    expect(tracker.box(100, 100)).toBeNull();
    for (const t of [0, 100, 200]) tracker.push(shoulders(t));
    expect(tracker.box(100, 100)!.width).toBeCloseTo(0.52, 9);
    tracker.push(framingFrame(5_000, [], null));
    expect(tracker.box(100, 100)).toBeNull();
  });
});
