import { type CSSProperties, type RefObject, useEffect, useState } from "react";

/** Inline custom properties (`--name`), which React's CSSProperties type does not list. */
export function cssVars(vars: Record<string, string | number>): CSSProperties {
  return vars as CSSProperties;
}

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(prefersReducedMotion);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(query.matches);
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return reduced;
}

/** Marks every `[data-reveal]` under `root` with `data-revealed` the first time it scrolls into view. */
export function useRevealOnScroll(root: RefObject<HTMLElement | null>): void {
  useEffect(() => {
    const element = root.current;
    if (!element) return;
    const targets = [...element.querySelectorAll<HTMLElement>("[data-reveal]")];
    if (typeof IntersectionObserver === "undefined" || prefersReducedMotion()) {
      for (const target of targets) target.dataset.revealed = "true";
      return;
    }
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        (entry.target as HTMLElement).dataset.revealed = "true";
        observer.unobserve(entry.target);
      }
    }, { rootMargin: "0px 0px -12% 0px", threshold: 0.12 });
    for (const target of targets) observer.observe(target);
    return () => observer.disconnect();
  }, [root]);
}

/** True while the element is at least partly on screen. */
export function useInView(target: RefObject<Element | null>, rootMargin = "0px"): boolean {
  const [inView, setInView] = useState(false);
  useEffect(() => {
    const element = target.current;
    if (!element || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => setInView(entry.isIntersecting), { rootMargin });
    observer.observe(element);
    return () => observer.disconnect();
  }, [target, rootMargin]);
  return inView;
}

/**
 * Writes scroll progress through an element (0–1) to a CSS custom property on it, once per frame and only while
 * it is near the viewport. `measure` maps the element's rect and the viewport height to the progress.
 */
export function useScrollProgress(
  target: RefObject<HTMLElement | null>,
  property: string,
  measure: (rect: DOMRect, viewport: number) => number,
): void {
  useEffect(() => {
    const element = target.current;
    if (!element) return;
    if (prefersReducedMotion()) {
      element.style.setProperty(property, "1");
      return;
    }
    let frame = 0;
    let visible = typeof IntersectionObserver === "undefined";
    const write = () => {
      frame = 0;
      const progress = measure(element.getBoundingClientRect(), window.innerHeight);
      element.style.setProperty(property, Math.min(1, Math.max(0, progress)).toFixed(4));
    };
    const schedule = () => {
      if (visible && !frame) frame = window.requestAnimationFrame(write);
    };
    const observer = typeof IntersectionObserver === "undefined" ? null : new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      schedule();
    }, { rootMargin: "20% 0px" });
    observer?.observe(element);
    write();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      observer?.disconnect();
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, [target, property, measure]);
}
