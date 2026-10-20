import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  readWorkspaceView,
  type WorkspaceView,
} from "../lib/workspaceNavigation";

function currentView(): WorkspaceView {
  if (typeof window === "undefined") return "recognize";
  return readWorkspaceView(new URLSearchParams(window.location.search).get("view"));
}

function hasViewParam() {
  return typeof window !== "undefined" && new URLSearchParams(window.location.search).has("view");
}

/**
 * `landing` is the view opened when the URL names none. It is applied on the first render, not after it,
 * so a reload never paints the default page and then jumps to the landing page.
 */
export function useWorkspaceNavigation(landing: WorkspaceView = "recognize") {
  const [view, setView] = useState<WorkspaceView>(() => hasViewParam() ? currentView() : landing);
  // The URL may omit `view` only for the landing view of the first render; any other view, including
  // recognize when the landing is overview, is written out so a reload reopens it.
  const landingRef = useRef(landing);

  useLayoutEffect(() => {
    if (landing === "recognize" || hasViewParam()) return;
    const url = new URL(window.location.href);
    url.searchParams.set("view", landing);
    window.history.replaceState(window.history.state, "", url);
    // Only the first render can land; later navigation owns the URL.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const navigate = useCallback((nextView: WorkspaceView) => {
    setView(nextView);
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    if (nextView === "recognize" && landingRef.current === "recognize") url.searchParams.delete("view");
    else url.searchParams.set("view", nextView);
    window.history.pushState({}, "", url);
  }, []);

  useEffect(() => {
    const handlePopState = () => setView(currentView());
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  return { view, navigate };
}
