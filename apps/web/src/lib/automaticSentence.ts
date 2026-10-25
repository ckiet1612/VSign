export const SENTENCE_PAUSE_MS = 1800;

export interface SentenceDraft {
  id: number;
  words: string[];
  sentence: string;
  status: "collecting" | "composing" | "draft" | "review";
  warning: string;
  compositionWarning?: string;
}

export interface SentenceRequest {
  id: number;
  revision: number;
  words: string[];
}

export interface SentenceCapture {
  id: number;
}

interface DraftTiming {
  revision: number;
  lastChangeAt: number;
  canCompose: boolean;
}

export class AutomaticSentence {
  drafts: SentenceDraft[] = [];
  private words: string[] = [];
  private owners: number[] = [];
  private timing = new Map<number, DraftTiming>();
  private captures = new Map<number, { draftId: number; ended: boolean }>();
  private nextId = 0;
  private nextCaptureId = 0;
  private forceNewDraft = false;

  reset(): void {
    this.drafts = [];
    this.words = [];
    this.owners = [];
    this.timing.clear();
    this.captures.clear();
    this.forceNewDraft = false;
  }

  private create(now: number): SentenceDraft {
    const draft: SentenceDraft = {
      id: this.nextId++, words: [], sentence: "", status: "collecting", warning: "",
    };
    this.drafts.push(draft);
    this.timing.set(draft.id, {
      revision: 0, lastChangeAt: now, canCompose: false,
    });
    return draft;
  }

  private current(now: number): SentenceDraft {
    return this.drafts.at(-1) ?? this.create(now);
  }

  private changed(draft: SentenceDraft, now: number, canCompose = false): void {
    const timing = this.timing.get(draft.id)!;
    timing.revision += 1;
    timing.lastChangeAt = now;
    timing.canCompose = canCompose;
    draft.sentence = "";
    draft.compositionWarning = "";
    draft.status = draft.warning ? "review" : "collecting";
  }

  activity(now: number): SentenceCapture {
    // Pauses never split the draft: every recognized word so far is normalized together.
    // Only a recognition context change starts a new one.
    const current = this.forceNewDraft ? this.create(now) : this.current(now);
    this.forceNewDraft = false;
    this.changed(current, now);
    const capture = { id: this.nextCaptureId++ };
    this.captures.set(capture.id, { draftId: current.id, ended: false });
    return capture;
  }

  finish(capture: SentenceCapture, now: number): void {
    const owner = this.captures.get(capture.id);
    if (!owner || owner.ended) return;
    owner.ended = true;
    const timing = this.timing.get(owner.draftId)!;
    timing.lastChangeAt = Math.max(timing.lastChangeAt, now);
  }

  accept(capture: SentenceCapture, words: string[], now: number): void {
    const owner = this.captures.get(capture.id);
    if (!owner) return;
    if (!owner.ended) this.finish(capture, now);
    this.sync(words, now, owner.draftId);
    this.captures.delete(capture.id);
  }

  sync(words: string[], now: number, draftId?: number): void {
    if (JSON.stringify(words) === JSON.stringify(this.words)) return;
    if (!words.length) { this.reset(); return; }
    const appended = this.words.every((word, index) => words[index] === word);
    const shortened = words.every((word, index) => this.words[index] === word);
    if (!appended && shortened) {
      const affected = new Set(this.owners.slice(words.length));
      this.words = [...words];
      this.owners = this.owners.slice(0, words.length);
      for (const draft of this.drafts) {
        if (!affected.has(draft.id)) continue;
        draft.words = words.filter((_, index) => this.owners[index] === draft.id);
        this.changed(draft, now, draft.words.length > 0);
      }
      return;
    }
    if (!appended) this.reset();
    const current = this.drafts.find(item => item.id === draftId) ?? this.current(now);
    this.owners.push(...words.slice(this.words.length).map(() => current.id));
    this.words = [...words];
    current.words = words.filter((_, index) => this.owners[index] === current.id);
    this.changed(current, now, current.words.length > 0);
  }

  /** Close a capture that produced no word, without flagging its draft. */
  skip(capture: SentenceCapture, now: number): void {
    const owner = this.captures.get(capture.id);
    if (!owner) return;
    if (!owner.ended) this.finish(capture, now);
    this.captures.delete(capture.id);
    const draft = this.drafts.find(item => item.id === owner.draftId);
    if (draft) this.changed(draft, now, draft.words.length > 0);
  }

  missing(message: string, now: number, capture?: SentenceCapture): void {
    const owner = capture ? this.captures.get(capture.id) : null;
    if (capture && !owner) return;
    if (capture && owner && !owner.ended) this.finish(capture, now);
    const current = owner ? this.drafts.find(item => item.id === owner.draftId)! : this.current(now);
    current.warning = message;
    this.changed(current, now, current.words.length > 0);
    if (capture) this.captures.delete(capture.id);
  }

  skipPending(now: number): void {
    for (const id of [...this.captures.keys()]) this.skip({ id }, now);
  }

  cancelPending(message: string, now: number): void {
    for (const id of [...this.captures.keys()]) this.missing(message, now, { id });
  }

  /** Recognition paused without changing model, e.g. a dropped connection: keep the drafts and recompose the one cut off. */
  interrupted(message: string, now: number): void {
    this.cancelPending(message, now);
    for (const draft of this.drafts) {
      if (draft.status === "composing") this.changed(draft, now, draft.words.length > 0);
    }
  }

  contextChanged(message: string, now: number): void {
    this.cancelPending(message, now);
    for (const draft of this.drafts) {
      if (!draft.words.length && !draft.warning) continue;
      if (draft.status === "composing" || draft === this.drafts.at(-1)) {
        draft.warning = message;
        this.changed(draft, now);
      }
    }
    this.forceNewDraft = this.drafts.length > 0;
  }

  prepare(now: number, blocked: boolean): SentenceRequest | null {
    if (blocked) return null;
    const current = this.drafts.find(item => item.words.length &&
      (item.status === "collecting" || item.status === "review") &&
      this.timing.get(item.id)!.canCompose &&
      ![...this.captures.values()].some(capture => capture.draftId === item.id) &&
      now - this.timing.get(item.id)!.lastChangeAt >= SENTENCE_PAUSE_MS);
    if (!current) return null;
    this.timing.get(current.id)!.canCompose = false;
    current.status = "composing";
    return { id: current.id, revision: this.timing.get(current.id)!.revision, words: [...current.words] };
  }

  valid(request: SentenceRequest): boolean {
    return this.timing.get(request.id)?.revision === request.revision &&
      this.drafts.find(item => item.id === request.id)?.status === "composing";
  }

  resolve(request: SentenceRequest, sentence: string, warnings: string[] = []): boolean {
    if (!this.valid(request)) return false;
    const current = this.drafts.find(item => item.id === request.id)!;
    current.sentence = sentence;
    current.compositionWarning = warnings.join(" · ");
    current.status = current.warning || current.compositionWarning ? "review" : "draft";
    return true;
  }

  fail(request: SentenceRequest, message: string): void {
    if (!this.valid(request)) return;
    const current = this.drafts.find(item => item.id === request.id)!;
    this.changed(current, this.timing.get(current.id)!.lastChangeAt);
    current.compositionWarning = message;
    current.status = "review";
  }
}
