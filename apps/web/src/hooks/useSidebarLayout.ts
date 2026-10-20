import { useCallback, useEffect, useState } from "react";

/** Narrowest open sidebar: the longest labels (system nav, account name) fit without an ellipsis. */
export const SIDEBAR_MIN_WIDTH = 212;
export const SIDEBAR_MAX_WIDTH = 360;
export const SIDEBAR_DEFAULT_WIDTH = 212;
/** Dragging the edge further left than this collapses the sidebar into the icon rail. */
export const SIDEBAR_COLLAPSE_THRESHOLD = 140;

const STORAGE_KEY = "vsign.sidebar";

interface SidebarLayout {
  width: number;
  collapsed: boolean;
}

export function clampSidebarWidth(width: number): number {
  return Math.round(Math.min(SIDEBAR_MAX_WIDTH, Math.max(SIDEBAR_MIN_WIDTH, width)));
}

function readLayout(): SidebarLayout {
  const fallback = { width: SIDEBAR_DEFAULT_WIDTH, collapsed: false };
  if (typeof window === "undefined") return fallback;
  try {
    const stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "null") as Partial<SidebarLayout> | null;
    if (!stored) return fallback;
    return {
      width: typeof stored.width === "number" ? clampSidebarWidth(stored.width) : SIDEBAR_DEFAULT_WIDTH,
      collapsed: stored.collapsed === true,
    };
  } catch {
    return fallback;
  }
}

export function useSidebarLayout() {
  const [layout, setLayout] = useState<SidebarLayout>(readLayout);

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(layout));
    } catch {
      // Storage may be unavailable (private mode); layout still works for this session.
    }
  }, [layout]);

  const setWidth = useCallback((width: number) => {
    setLayout({ width: clampSidebarWidth(width), collapsed: false });
  }, []);
  const setCollapsed = useCallback((collapsed: boolean) => {
    setLayout(current => ({ ...current, collapsed }));
  }, []);
  const toggleCollapsed = useCallback(() => {
    setLayout(current => ({ ...current, collapsed: !current.collapsed }));
  }, []);
  const resetWidth = useCallback(() => {
    setLayout({ width: SIDEBAR_DEFAULT_WIDTH, collapsed: false });
  }, []);

  return { ...layout, setWidth, setCollapsed, toggleCollapsed, resetWidth };
}
