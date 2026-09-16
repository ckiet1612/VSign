import { describe, expect, it } from "vitest";
import {
  V5_TARGET_PER_LABEL,
  v5CollectionTargetsFor,
} from "./v5CollectionPlan";

describe("V5 collection targets", () => {
  it("uses only the local quota needed after public train/validation", () => {
    expect(V5_TARGET_PER_LABEL).toBe(100);
    expect(v5CollectionTargetsFor("Uống", 50)).toEqual({
      right: 39,
      left: 39,
    });
    expect(v5CollectionTargetsFor("Trường học", 50)).toEqual({
      right: 17,
      left: 17,
    });
  });

  it("falls back for the negative class", () => {
    expect(v5CollectionTargetsFor("Không ký hiệu", 12)).toEqual({
      right: 12,
      left: 12,
    });
  });
});
