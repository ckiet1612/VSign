import { config } from "../config";

// The landing page owns the site root; the workspace lives under /workspace. The static public demo has no landing
// page, so its workspace stays at the root of its base path.
export const WORKSPACE_SEGMENT = config.publicDemo ? "" : "workspace";

function sitePath() {
  if (typeof window === "undefined") return "";
  return new URL(import.meta.env.BASE_URL || "/", window.location.origin).pathname.replace(/\/+$/, "");
}

/** Path of the workspace root, without a trailing slash ("" when it is the site root). */
export function workspaceBasePath(): string {
  return WORKSPACE_SEGMENT ? `${sitePath()}/${WORKSPACE_SEGMENT}` : sitePath();
}

/** Link to the workspace, optionally with a query such as `?login=`. */
export function workspaceHref(search = ""): string {
  return `${workspaceBasePath() || "/"}${search}`;
}

export function landingHref(): string {
  return `${sitePath()}/`;
}

export function isLandingPath(pathname: string, search = ""): boolean {
  if (config.publicDemo) return false;
  const path = pathname.replace(/\/+$/, "");
  const params = new URLSearchParams(search);
  return path === `${sitePath()}/landing` ||
    (path === sitePath() && !params.has("view") && !params.has("login"));
}

export function isWorkspacePath(pathname: string): boolean {
  const base = workspaceBasePath();
  return !base || pathname === base || pathname.startsWith(`${base}/`);
}
