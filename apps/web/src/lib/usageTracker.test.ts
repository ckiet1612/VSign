import { describe, expect, it } from "vitest";
import { USAGE_IDLE_MS, UsageTracker } from "./usageTracker";

const local = { channel: "same_screen" as const, displayId: null };
const counter = { channel: "counter" as const, displayId: "d1" };

describe("UsageTracker", () => {
  it("summarises a conversation as counts and labels only", () => {
    const tracker = new UsageTracker();
    const start = Date.parse("2026-10-23T03:00:00Z");
    tracker.note({ type: "word", label: "Tôi" }, counter, start);
    tracker.note({ type: "word", label: "Muốn" }, counter, start + 1000);
    tracker.note({ type: "uncertain" }, counter, start + 2000);
    tracker.note({ type: "undo", by: "customer", label: "Muốn" }, counter, start + 3000);
    tracker.note({ type: "reply", voice: true }, counter, start + 4000);
    tracker.note({ type: "failed" }, counter, start + 4500);
    const summary = tracker.end(start + 5000)!;
    expect(summary).toMatchObject({
      channel: "counter", display_id: "d1", words: 2, uncertain: 1, failed: 1, staff_undos: 0, customer_undos: 1,
      replies: 1, voice_replies: 1, labels: { Tôi: 1, Muốn: 1 }, undone_labels: { Muốn: 1 },
      started_at: "2026-10-23T03:00:00.000Z", ended_at: "2026-10-23T03:00:05.000Z",
    });
    expect(summary.id).toMatch(/^[0-9a-f-]{36}$/);
    expect(tracker.end()).toBeNull();
  });

  it("starts a new conversation after a long pause or when the counter changes", () => {
    const tracker = new UsageTracker();
    tracker.note({ type: "word", label: "Chào" }, local, 0);
    expect(tracker.expire(USAGE_IDLE_MS)).toBeNull();
    const idle = tracker.note({ type: "word", label: "Gạo" }, local, USAGE_IDLE_MS + 1);
    expect(idle).toMatchObject({ words: 1, labels: { Chào: 1 } });
    // The idle conversation ends at its last event, not when the next customer arrives.
    expect(idle?.ended_at).toBe(new Date(0).toISOString());
    const switched = tracker.note({ type: "word", label: "Sữa" }, counter, USAGE_IDLE_MS + 2);
    expect(switched).toMatchObject({ channel: "same_screen", labels: { Gạo: 1 } });
    expect(tracker.expire(2 * USAGE_IDLE_MS + 3)).toMatchObject({ channel: "counter", labels: { Sữa: 1 } });
  });
});
