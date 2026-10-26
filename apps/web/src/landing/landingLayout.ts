// Pure layout helpers for the landing sections, kept out of the component files for fast refresh and tests.

/** A stable scatter for chip `index`: a small tilt and lift, so the cloud looks tossed but never reshuffles. */
export function chipScatter(index: number): { rotate: number; lift: number } {
  return { rotate: ((index * 37) % 13) - 6, lift: (((index * 53) % 9) - 4) * 3 };
}

export interface StatementWord {
  text: string;
  tone?: string;
}

export function parseStatement(source: string): StatementWord[] {
  const words: StatementWord[] = [];
  for (const match of source.matchAll(/\[([^|\]]+)\|(\w+)\]|(\S+)/g)) {
    if (match[3]) words.push({ text: match[3] });
    else for (const text of match[1].split(" ")) words.push({ text, tone: match[2] });
  }
  return words;
}

/** Signed distance from the active card, wrapped so the deck fans out on both sides (−2…2 for five cards). */
export function deckOffset(index: number, active: number, count: number): number {
  const half = Math.floor(count / 2);
  return ((index - active + count + half) % count) - half;
}
