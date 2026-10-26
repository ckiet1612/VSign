// Chapters of the 60 s brand film (marketing/brand-film-60s/README.md), made contiguous for the hero scrubber.
export interface FilmChapter {
  label: string;
  start: number;
}

export const FILM_DURATION = 60;

export const FILM_CHAPTERS: readonly FilmChapter[] = [
  { label: "Mở đầu", start: 0 },
  { label: "Nhịp cầu", start: 9.6 },
  { label: "Nhìn", start: 15 },
  { label: "16 khung hình", start: 20 },
  { label: "Một từ", start: 25 },
  { label: "Một câu", start: 29.4 },
  { label: "Hai màn hình", start: 36 },
  { label: "Riêng tư", start: 42.5 },
  { label: "30 ký hiệu", start: 45 },
  { label: "VSign", start: 50 },
];

export function chapterEnd(index: number): number {
  return FILM_CHAPTERS[index + 1]?.start ?? FILM_DURATION;
}

/** Index of the chapter playing at `time`; the last chapter holds past the end. */
export function chapterAt(time: number): number {
  let index = 0;
  for (let i = 0; i < FILM_CHAPTERS.length; i += 1) {
    if (time >= FILM_CHAPTERS[i].start) index = i;
  }
  return index;
}

/** How far `time` is through chapter `index`, 0–1; earlier chapters are full and later ones empty. */
export function chapterFill(index: number, time: number): number {
  const start = FILM_CHAPTERS[index].start;
  const end = chapterEnd(index);
  return Math.min(1, Math.max(0, (time - start) / (end - start)));
}
