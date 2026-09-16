export const TRANSCRIPT_COOLDOWN_MS = 1_000;

export interface TranscriptState {
  words: string[];
  lastAdded: { label: string; at: number } | null;
}

export type TranscriptAction =
  | { type: "add"; label: string; at: number }
  | { type: "undo" }
  | { type: "clear" };

export const initialTranscriptState: TranscriptState = {
  words: [],
  lastAdded: null,
};

export function transcriptReducer(
  state: TranscriptState,
  action: TranscriptAction,
): TranscriptState {
  switch (action.type) {
    case "add": {
      const label = action.label.trim();
      if (!label) return state;
      if (
        state.lastAdded?.label === label &&
        action.at - state.lastAdded.at < TRANSCRIPT_COOLDOWN_MS
      ) {
        return state;
      }
      return {
        words: [...state.words, label],
        lastAdded: { label, at: action.at },
      };
    }
    case "undo":
      return {
        words: state.words.slice(0, -1),
        lastAdded: null,
      };
    case "clear":
      return initialTranscriptState;
  }
}
