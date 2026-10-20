export const MAX_WAITING_CAPTURES = 2;

export interface AutomaticCaptureTiming {
  captureMs: number;
  encodeMs: number;
}

export interface AutomaticInferenceJob {
  sequence: number;
  route: "server" | "local";
  capturedAt: number;
  landmarkFrames: number[][];
  baselineLandmarkFrames: number[][];
  rgbFrames?: string[];
  timing: AutomaticCaptureTiming;
  /** Sent while the hands rest; its result is held until the sign is confirmed. */
  provisional?: boolean;
}

export interface AutomaticInferenceTiming extends AutomaticCaptureTiming {
  sequence: number;
  queueWaitMs: number;
  responseMs: number;
  /** From the sign being confirmed to its result reaching the app. */
  resultWaitMs?: number;
}

interface Waiting<T> {
  job: T;
  queuedAt: number;
}

interface Running<T> extends Waiting<T> {
  startedAt: number;
  cancelled: boolean;
}

export class AutomaticInferenceQueue<T extends { sequence: number; provisional?: boolean }> {
  private waiting: Waiting<T>[] = [];
  private running: Running<T> | null = null;

  get pendingCount(): number { return this.waiting.length; }
  get busy(): boolean { return this.running !== null; }
  // A provisional job belongs to the sign still being captured; counting it could pause
  // capture and cancel that very sign.
  get full(): boolean { return this.waiting.filter((item) => !item.job.provisional).length >= MAX_WAITING_CAPTURES; }

  enqueue(job: T, now: number): boolean {
    if (
      this.full || this.running?.job.sequence === job.sequence ||
      this.waiting.some((item) => item.job.sequence === job.sequence)
    ) return false;
    this.waiting.push({ job, queuedAt: now });
    return true;
  }

  startNext(now: number): T | null {
    if (this.running) return null;
    const next = this.waiting.shift();
    if (!next) return null;
    this.running = { ...next, startedAt: now, cancelled: false };
    return next.job;
  }

  complete(sequence: number, now: number) {
    if (!this.running || this.running.job.sequence !== sequence) return null;
    const completed = this.running;
    this.running = null;
    return {
      job: completed.job,
      cancelled: completed.cancelled,
      queueWaitMs: Math.max(0, completed.startedAt - completed.queuedAt),
      responseMs: Math.max(0, now - completed.startedAt),
    };
  }

  /** Mark a provisional job final; "running" means it is already with the server. */
  confirm(sequence: number): "waiting" | "running" | null {
    if (this.running?.job.sequence === sequence && !this.running.cancelled) {
      return "running";
    }
    return this.waiting.some((item) => item.job.sequence === sequence) ? "waiting" : null;
  }

  markConfirmed(sequence: number): void {
    const item = this.waiting.find((entry) => entry.job.sequence === sequence);
    if (item) item.job.provisional = false;
  }

  /** Drop a provisional job: unsent ones leave the queue, a sent one ignores its reply. */
  retract(sequence: number): void {
    this.waiting = this.waiting.filter((item) => item.job.sequence !== sequence);
    if (this.running?.job.sequence === sequence) this.running.cancelled = true;
  }

  cancel(): void {
    this.waiting = [];
    // An already sent request still occupies its transport slot until it settles.
    if (this.running) this.running.cancelled = true;
  }
}
