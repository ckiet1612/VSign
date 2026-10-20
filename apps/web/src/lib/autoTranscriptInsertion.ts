import type { PredictionMessage } from "@contracts";

export type WordInsertionMode = "manual" | "automatic";

export interface AutoTranscriptCapture {
  generation: number;
  contextKey: string;
}

export class AutoTranscriptInsertion {
  private mode: WordInsertionMode = "manual";
  private generation = 0;
  private requests = new Map<number, AutoTranscriptCapture>();

  setMode(mode: WordInsertionMode): void {
    if (mode === this.mode) return;
    this.mode = mode;
    this.invalidate();
  }

  invalidate(): void {
    this.generation += 1;
    this.requests.clear();
  }

  beginCapture(contextKey: string, eligible: boolean): AutoTranscriptCapture | null {
    return this.mode === "automatic" && eligible
      ? { generation: this.generation, contextKey }
      : null;
  }

  register(sequence: number, capture: AutoTranscriptCapture | null): void {
    if (capture?.generation === this.generation && this.mode === "automatic") {
      this.requests.set(sequence, capture);
    }
  }

  discard(sequence: number): void {
    this.requests.delete(sequence);
  }

  consume(prediction: PredictionMessage, contextKey: string, eligible: boolean): string | null {
    const capture = this.requests.get(prediction.sequence);
    this.requests.delete(prediction.sequence);
    if (
      !eligible || this.mode !== "automatic" ||
      capture?.generation !== this.generation || capture.contextKey !== contextKey ||
      prediction.status !== "ok"
    ) return null;
    return prediction.label?.trim() || null;
  }
}
