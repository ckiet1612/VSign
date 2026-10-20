import { describe, expect, it } from "vitest";
import type { PredictionMessage } from "@contracts";
import { AutoTranscriptInsertion } from "./autoTranscriptInsertion";

const prediction: PredictionMessage = {
  type: "prediction", sequence: 7, status: "ok", label: "Mua", confidence: 0.95,
  top_k: [{ label: "Mua", confidence: 0.95 }], model_version: "sales30-v3",
};
const context = "recognize:manual:ready:server:v3";

function registered() {
  const gate = new AutoTranscriptInsertion();
  gate.setMode("automatic");
  gate.register(7, gate.beginCapture(context, true));
  return gate;
}

describe("AutoTranscriptInsertion", () => {
  it("defaults to manual insertion", () => {
    const gate = new AutoTranscriptInsertion();
    expect(gate.beginCapture(context, true)).toBeNull();
    gate.register(7, null);
    expect(gate.consume(prediction, context, true)).toBeNull();
  });

  it("consumes each new eligible capture exactly once", () => {
    const gate = registered();
    expect(gate.consume({ ...prediction, sequence: 6 }, context, true)).toBeNull();
    expect(gate.consume(prediction, context, true)).toBe("Mua");
    expect(gate.consume(prediction, context, true)).toBeNull();
  });

  it("does not retroactively opt in a capture started in manual mode", () => {
    const gate = new AutoTranscriptInsertion();
    const capture = gate.beginCapture(context, true);
    gate.setMode("automatic");
    gate.register(7, capture);
    expect(gate.consume(prediction, context, true)).toBeNull();
  });

  it("invalidates old capture tokens even if encoding finishes after re-enabling", () => {
    const gate = new AutoTranscriptInsertion();
    gate.setMode("automatic");
    const capture = gate.beginCapture(context, true);
    gate.setMode("manual");
    gate.setMode("automatic");
    gate.register(7, capture);
    expect(gate.consume(prediction, context, true)).toBeNull();
  });

  it("does not revive queued requests after disabling and re-enabling", () => {
    const gate = registered();
    gate.setMode("manual");
    gate.setMode("automatic");
    expect(gate.consume(prediction, context, true)).toBeNull();
  });

  it("keeps opted-in requests when the same mode is selected again", () => {
    const gate = registered();
    gate.setMode("automatic");
    expect(gate.consume(prediction, context, true)).toBe("Mua");
  });

  it.each(["uncertain", "no_hands", "bad_framing", "busy", "error"] as const)(
    "rejects %s without allowing the same sequence to be retried as ok", (status) => {
      const gate = registered();
      expect(gate.consume({ ...prediction, status, label: null }, context, true)).toBeNull();
      expect(gate.consume(prediction, context, true)).toBeNull();
    },
  );

  it("rejects a reply from a different context", () => {
    const gate = registered();
    expect(gate.consume(prediction, "recognize:manual:off:server:v3", true)).toBeNull();
    expect(gate.consume(prediction, context, true)).toBeNull();
  });

  it("invalidates captures and requests when a context is cancelled", () => {
    const gate = registered();
    const capture = gate.beginCapture(context, true);
    gate.invalidate();
    gate.register(8, capture);
    expect(gate.consume(prediction, context, true)).toBeNull();
    expect(gate.consume({ ...prediction, sequence: 8 }, context, true)).toBeNull();
    gate.register(9, gate.beginCapture(context, true));
    expect(gate.consume({ ...prediction, sequence: 9 }, context, true)).toBe("Mua");
  });

  it("drops requests rejected by the queue or transport", () => {
    const gate = registered();
    gate.discard(7);
    expect(gate.consume(prediction, context, true)).toBeNull();
  });

  it("requires eligibility both at capture start and reply time", () => {
    const gate = new AutoTranscriptInsertion();
    gate.setMode("automatic");
    gate.register(7, gate.beginCapture(context, false));
    expect(gate.consume(prediction, context, true)).toBeNull();
    gate.register(7, gate.beginCapture(context, true));
    expect(gate.consume(prediction, context, false)).toBeNull();
    expect(gate.consume(prediction, context, true)).toBeNull();
  });

  it.each([null, "", "  "])("does not insert an empty label %s", (label) => {
    expect(registered().consume({ ...prediction, label }, context, true)).toBeNull();
  });
});
