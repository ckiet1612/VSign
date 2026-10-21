import { useEffect, useState } from "react";

const PARAM = "tab";

function readTab<T extends string>(values: readonly T[], fallback: T): T {
  if (typeof window === "undefined") return fallback;
  const value = new URLSearchParams(window.location.search).get(PARAM);
  return values.includes(value as T) ? value as T : fallback;
}

/**
 * The selected section of a page with tabs, kept in the URL's `tab` parameter so a reload reopens it.
 * The first render reads the URL, so a reload never paints the first tab and then jumps. `active` is false
 * while the page is not shown (state owned above the page); navigating to another view drops the parameter.
 */
export function useUrlTab<T extends string>(values: readonly T[], fallback: T, active = true) {
  const [tab, setTab] = useState<T>(() => readTab(values, fallback));

  useEffect(() => {
    if (!active || typeof window === "undefined") return;
    const url = new URL(window.location.href);
    if (tab === fallback) url.searchParams.delete(PARAM);
    else url.searchParams.set(PARAM, tab);
    if (url.href !== window.location.href) window.history.replaceState(window.history.state, "", url);
  }, [active, tab, fallback]);

  return [tab, setTab] as const;
}
