import { useEffect, useState } from "react";

const PARAM = "tab";

function basePath() {
  if (typeof window === "undefined") return "";
  return new URL(import.meta.env.BASE_URL || "/", window.location.origin).pathname.replace(/\/+$/, "");
}

function relativeSegments() {
  const base = basePath();
  const pathname = window.location.pathname;
  const relative = base && pathname.startsWith(`${base}/`) ? pathname.slice(base.length) : pathname;
  return relative.split("/").filter(Boolean);
}

function absolutePath(segments: readonly string[]) {
  const base = basePath();
  return segments.length ? `${base}/${segments.join("/")}` : base || "/";
}

function readTab<T extends string>(values: readonly T[], fallback: T): T {
  if (typeof window === "undefined") return fallback;
  const pathTab = relativeSegments().at(-1);
  if (values.includes(pathTab as T)) return pathTab as T;
  const value = new URLSearchParams(window.location.search).get(PARAM);
  return values.includes(value as T) ? value as T : fallback;
}

function parentSegments<T extends string>(values: readonly T[]) {
  const segments = relativeSegments();
  return values.includes(segments.at(-1) as T) ? segments.slice(0, -1) :
    new URLSearchParams(window.location.search).get("view")?.split("/").filter(Boolean) ?? segments;
}

/**
 * The selected section of a page with tabs, kept as the final path segment so a reload reopens it.
 * The first render reads the URL, so a reload never paints the first tab and then jumps. `active` is false
 * while the page is not shown (state owned above the page); navigating to another view drops the segment.
 */
export function useUrlTab<T extends string>(values: readonly T[], fallback: T, active = true) {
  const [tab, setTab] = useState<T>(() => readTab(values, fallback));

  useEffect(() => {
    if (!active || typeof window === "undefined") return;
    const url = new URL(window.location.href);
    const parent = parentSegments(values);
    url.pathname = absolutePath(tab === fallback ? parent : [...parent, tab]);
    url.searchParams.delete(PARAM);
    url.searchParams.delete("view");
    if (url.href !== window.location.href) window.history.replaceState(window.history.state, "", url);
  }, [active, tab, fallback, values]);

  return [tab, setTab] as const;
}
