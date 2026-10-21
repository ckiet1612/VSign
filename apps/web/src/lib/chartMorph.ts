import type { AnimationInterpolateFn, AnimationItem, BarRectangleItem, LinePointItem } from "recharts";

/*
 * Range morphs for date series (7 ↔ 30 ↔ 90 days). Items are matched by date, so a day that is in
 * both ranges slides to its new slot. The x-scale change those matched days imply is applied to the
 * other days too: when the range shrinks, older days fold into the left edge; when it grows, they
 * unfold out of it. Nothing travels beyond the plot area, so the y-axis labels are never covered.
 */

const lerp = (from: number, to: number, t: number) => from + (to - from) * t;
const num = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? value : 0;

interface Zoom { toPrev: (x: number) => number; toNext: (x: number) => number; prevLeft: number; nextLeft: number }

/** Linear map between old and new x positions, fitted on the leftmost and rightmost matched items. */
function zoom<T>(items: ReadonlyArray<AnimationItem<T>>, centre: (item: T) => number): Zoom | null {
  const matched = items.flatMap(item => item.status === "matched" ? [item] : []);
  if (matched.length < 2) return null;
  const first = matched.reduce((a, b) => centre(b.next) < centre(a.next) ? b : a);
  const last = matched.reduce((a, b) => centre(b.next) > centre(a.next) ? b : a);
  const span = centre(last.next) - centre(first.next);
  if (span <= 0) return null;
  const scale = (centre(last.prev) - centre(first.prev)) / span;
  if (scale <= 0) return null;
  const offset = centre(first.prev) - scale * centre(first.next);
  const edge = (pick: (item: AnimationItem<T>) => T | undefined) =>
    Math.min(...items.flatMap(item => { const value = pick(item); return value ? [centre(value)] : []; }));
  return {
    toPrev: x => scale * x + offset,
    toNext: x => (x - offset) / scale,
    prevLeft: edge(item => item.status === "added" ? undefined : item.prev),
    nextLeft: edge(item => item.status === "removed" ? undefined : item.next),
  };
}

const settled = <T>(items: ReadonlyArray<AnimationItem<T>>) => items.flatMap(item => item.status === "removed" ? [] : [item.next]);

/** Vertical bars on a date axis. */
export const morphDateBars: AnimationInterpolateFn<BarRectangleItem, "horizontal" | "vertical"> = (items, t) => {
  if (!items) return [];
  if (t >= 1) return settled(items);
  const centre = (bar: BarRectangleItem) => num(bar.x) + num(bar.width) / 2;
  const map = zoom(items, centre);
  const bottom = (bar: BarRectangleItem) => num(bar.y) + num(bar.height);
  return items.map(item => {
    if (item.status === "matched") {
      const { prev, next } = item;
      return { ...next, x: lerp(num(prev.x), num(next.x), t), y: lerp(num(prev.y), num(next.y), t),
        width: lerp(num(prev.width), num(next.width), t), height: lerp(num(prev.height), num(next.height), t) };
    }
    if (item.status === "added") {
      const { next } = item;
      const fromCentre = map ? Math.max(map.toPrev(centre(next)), map.prevLeft) : centre(next);
      const width = lerp(map ? 0 : num(next.width), num(next.width), t);
      const height = lerp(0, num(next.height), t);
      return { ...next, x: lerp(fromCentre, centre(next), t) - width / 2, width, height, y: bottom(next) - height };
    }
    const { prev } = item;
    const toCentre = map ? Math.max(map.toNext(centre(prev)), map.nextLeft) : centre(prev);
    const width = lerp(num(prev.width), map ? 0 : num(prev.width), t);
    const height = lerp(num(prev.height), 0, t);
    return { ...prev, x: lerp(centre(prev), toCentre, t) - width / 2, width, height, y: bottom(prev) - height };
  });
};

/** A line on a date axis; days outside the shared range collapse onto, or grow out of, its first point. */
export const morphDateLine: AnimationInterpolateFn<LinePointItem, "horizontal" | "vertical"> = (items, t) => {
  if (!items) return [];
  if (t >= 1) return settled(items);
  const x = (point: LinePointItem) => num(point.x);
  const map = zoom(items, x);
  const anchor = items.filter(item => item.status === "matched").reduce<AnimationItem<LinePointItem> & { status: "matched" } | null>(
    (best, item) => item.status === "matched" && (!best || x(item.next) < x(best.next)) ? item : best, null);
  return items.map(item => {
    if (item.status === "matched") {
      return { ...item.next, x: lerp(x(item.prev), x(item.next), t), y: lerp(num(item.prev.y), num(item.next.y), t) };
    }
    if (item.status === "added") {
      const { next } = item;
      const fromX = map ? Math.max(map.toPrev(x(next)), map.prevLeft) : x(next);
      return { ...next, x: lerp(fromX, x(next), t), y: lerp(anchor ? num(anchor.prev.y) : num(next.y), num(next.y), t) };
    }
    const { prev } = item;
    const toX = map ? Math.max(map.toNext(x(prev)), map.nextLeft) : x(prev);
    return { ...prev, x: lerp(x(prev), toX, t), y: lerp(num(prev.y), anchor ? num(anchor.next.y) : num(prev.y), t) };
  });
};
