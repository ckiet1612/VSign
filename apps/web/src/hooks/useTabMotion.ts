import { useLayoutEffect, useRef, type RefObject } from "react";

const EASE = "cubic-bezier(0.2, 0.8, 0.2, 1)";

function selectedTab(root: HTMLElement) {
  return root.querySelector<HTMLElement>('[aria-selected="true"]');
}

/**
 * Segmented-control motion shared by workspace tabs:
 * - a single black pill (the list's ::before) glides to the selected segment, measured so labels may differ in width;
 * - the panel fades in with a short shift toward the direction of travel (transform/opacity only, ~220ms).
 * Both are skipped where layout or the Web Animations API is unavailable, leaving the static selected style.
 */
export function useTabMotion(list: RefObject<HTMLElement | null>, index: number, { panel, pick = selectedTab, mounted = true }: {
  panel?: RefObject<HTMLElement | null>;
  pick?: (root: HTMLElement) => HTMLElement | null;
  /** Re-measure when a conditionally rendered tab list appears. */
  mounted?: boolean;
} = {}) {
  const previous = useRef(index);

  useLayoutEffect(() => {
    const root = list.current;
    if (!root) return;
    const place = () => {
      const active = pick(root);
      if (!active || active.offsetWidth === 0) {
        delete root.dataset.indicator;
        return;
      }
      root.style.setProperty("--indicator-x", `${active.offsetLeft}px`);
      root.style.setProperty("--indicator-y", `${active.offsetTop}px`);
      root.style.setProperty("--indicator-w", `${active.offsetWidth}px`);
      root.style.setProperty("--indicator-h", `${active.offsetHeight}px`);
      // The first placement must not animate in from the corner; transitions start one frame later.
      if (!root.dataset.indicator) {
        root.dataset.indicator = "placed";
        requestAnimationFrame(() => { if (root.dataset.indicator) root.dataset.indicator = "live"; });
      }
    };
    place();
    if (typeof ResizeObserver === "undefined") return;
    // Segments can change width without the list resizing (late web fonts, clamped scrolling lists).
    const observer = new ResizeObserver(place);
    observer.observe(root);
    for (const child of root.children) observer.observe(child);
    return () => observer.disconnect();
  }, [list, index, pick, mounted]);

  useLayoutEffect(() => {
    const from = previous.current;
    previous.current = index;
    const element = panel?.current;
    if (from === index || !element || typeof element.animate !== "function") return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
    const shift = reduced ? 0 : index > from ? 12 : -12;
    element.animate(
      [{ opacity: 0, transform: `translateX(${shift}px)` }, { opacity: 1, transform: "none" }],
      { duration: reduced ? 120 : 220, easing: EASE },
    );
  }, [panel, index]);
}
