import { describe, expect, it } from "vitest";
import {
  initialTranscriptState,
  transcriptReducer,
} from "./transcript";

describe("transcriptReducer", () => {
  it("thêm, cooldown, hoàn tác và xóa", () => {
    const first = transcriptReducer(initialTranscriptState, {
      type: "add",
      label: "xin chào",
      at: 1_000,
    });
    const cooledDown = transcriptReducer(first, {
      type: "add",
      label: "xin chào",
      at: 1_500,
    });
    expect(cooledDown).toBe(first);

    const repeated = transcriptReducer(first, {
      type: "add",
      label: "xin chào",
      at: 2_001,
    });
    expect(repeated.words).toEqual(["xin chào", "xin chào"]);

    const undone = transcriptReducer(repeated, { type: "undo" });
    expect(undone.words).toEqual(["xin chào"]);
    expect(transcriptReducer(undone, { type: "clear" })).toEqual(
      initialTranscriptState,
    );
  });
});
