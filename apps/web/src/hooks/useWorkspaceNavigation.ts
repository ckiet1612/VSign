import { useCallback, useEffect, useLayoutEffect, useState } from "react";
import {
  isWorkspaceView,
  readWorkspaceView,
  type WorkspaceView,
} from "../lib/workspaceNavigation";

function basePath() {
  if (typeof window === "undefined") return "";
  return new URL(import.meta.env.BASE_URL || "/", window.location.origin).pathname.replace(/\/+$/, "");
}

function relativePathname() {
  const base = basePath();
  const pathname = window.location.pathname;
  return (base && pathname.startsWith(`${base}/`) ? pathname.slice(base.length) : pathname)
    .replace(/^\/+|\/+$/g, "");
}

function pathView() {
  return relativePathname().split("/")[0] ?? "";
}

function viewPath(view: WorkspaceView) {
  const base = basePath();
  return base ? `${base}/${view}` : `/${view}`;
}

function currentView(): WorkspaceView {
  if (typeof window === "undefined") return "recognize";
  const view = pathView();
  return isWorkspaceView(view)
    ? view
    : readWorkspaceView(new URLSearchParams(window.location.search).get("view"));
}

function hasWorkspaceView() {
  if (typeof window === "undefined") return false;
  return isWorkspaceView(pathView()) || new URLSearchParams(window.location.search).has("view");
}

/**
 * `landing` is the view opened when the URL names none. It is applied on the first render, not after it,
 * so a reload never paints the default page and then jumps to the landing page.
 */
export function useWorkspaceNavigation(landing: WorkspaceView = "recognize") {
  const [view, setView] = useState<WorkspaceView>(() => hasWorkspaceView() ? currentView() : landing);

  useLayoutEffect(() => {
    const url = new URL(window.location.href);
    const legacyView = url.searchParams.get("view");
    const currentPathView = pathView();
    if (legacyView && isWorkspaceView(legacyView)) {
      url.pathname = viewPath(legacyView);
      url.searchParams.delete("view");
      window.history.replaceState(window.history.state, "", url);
      return;
    }
    if (isWorkspaceView(currentPathView) || landing === "recognize") return;
    url.pathname = viewPath(landing);
    window.history.replaceState(window.history.state, "", url);
    // Only the first render can land; later navigation owns the URL.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const navigate = useCallback((nextView: WorkspaceView) => {
    setView(nextView);
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    url.pathname = viewPath(nextView);
    url.searchParams.delete("view");
    // A section belongs to the page it was chosen on; the next page opens on its own first section.
    if (nextView !== currentView()) url.searchParams.delete("tab");
    window.history.pushState({}, "", url);
  }, []);

  useEffect(() => {
    const handlePopState = () => setView(currentView());
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  return { view, navigate };
}
