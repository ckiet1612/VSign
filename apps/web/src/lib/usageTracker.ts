import type { ConversationSummaryRequest } from "../../../../contracts/v1/usage";

// A counter left alone this long has a new customer next time, even if nobody pressed "Cuộc hội thoại mới".
export const USAGE_IDLE_MS = 3 * 60_000;
const MAX_COUNT = 5000;

export type UsageEvent =
  | { type: "word"; label: string }
  | { type: "uncertain" }
  | { type: "failed" }
  | { type: "undo"; by: "staff" | "customer"; label: string | undefined }
  | { type: "reply"; voice: boolean };

export interface UsageContext { channel: ConversationSummaryRequest["channel"]; displayId: string | null }

type Open = ConversationSummaryRequest & { lastAt: number };

function id(): string {
  return globalThis.crypto?.randomUUID?.() ?? "10000000-1000-4000-8000-100000000000".replace(/[018]/g, digit =>
    (Number(digit) ^ Math.random() * 16 >> Number(digit) / 4).toString(16));
}

const bump = (value: number) => Math.min(MAX_COUNT, value + 1);

/**
 * Counts one conversation at the counter for the usage report (F08): how many words came through, which ones,
 * how many segments were unclear, undone or answered. It never holds video, sentences or reply text.
 */
export class UsageTracker {
  private open: Open | null = null;

  /** Records an event; returns the previous conversation when it had gone idle and this one starts afresh. */
  note(event: UsageEvent, context: UsageContext, now = Date.now()): ConversationSummaryRequest | null {
    const expired = this.open && now - this.open.lastAt > USAGE_IDLE_MS ? this.end(this.open.lastAt) : null;
    const contextChanged = this.open && (this.open.channel !== context.channel || this.open.display_id !== context.displayId);
    const switched = contextChanged ? this.end(now) : null;
    const open = this.open ??= this.start(context, now);
    open.lastAt = now;
    switch (event.type) {
      case "word":
        open.words = bump(open.words);
        open.labels[event.label] = bump(open.labels[event.label] ?? 0);
        break;
      case "uncertain": open.uncertain = bump(open.uncertain); break;
      case "failed": open.failed = bump(open.failed); break;
      case "undo":
        if (event.by === "staff") open.staff_undos = bump(open.staff_undos);
        else open.customer_undos = bump(open.customer_undos);
        if (event.label) open.undone_labels[event.label] = bump(open.undone_labels[event.label] ?? 0);
        break;
      case "reply":
        open.replies = bump(open.replies);
        if (event.voice) open.voice_replies = bump(open.voice_replies);
        break;
    }
    return expired ?? switched;
  }

  /** The conversation that went idle, if any, so a timer can report it without waiting for the next event. */
  expire(now = Date.now()): ConversationSummaryRequest | null {
    return this.open && now - this.open.lastAt > USAGE_IDLE_MS ? this.end(this.open.lastAt) : null;
  }

  /** Closes the current conversation; null when nothing happened in it. */
  end(now = Date.now()): ConversationSummaryRequest | null {
    const open = this.open;
    this.open = null;
    if (!open) return null;
    const summary: ConversationSummaryRequest = { ...open };
    delete (summary as Partial<Open>).lastAt;
    // Label maps are capped like the server's: the vocabulary is small, anything beyond that is noise.
    const cap = (labels: Record<string, number>) => Object.fromEntries(Object.entries(labels).slice(0, 64));
    const ended = Math.max(now, Date.parse(open.started_at));
    return { ...summary, labels: cap(summary.labels), undone_labels: cap(summary.undone_labels), ended_at: new Date(ended).toISOString() };
  }

  private start(context: UsageContext, now: number): Open {
    return {
      id: id(), started_at: new Date(now).toISOString(), ended_at: new Date(now).toISOString(),
      channel: context.channel, display_id: context.channel === "counter" ? context.displayId : null,
      words: 0, uncertain: 0, failed: 0, staff_undos: 0, customer_undos: 0, replies: 0, voice_replies: 0,
      labels: {}, undone_labels: {}, lastAt: now,
    };
  }
}
