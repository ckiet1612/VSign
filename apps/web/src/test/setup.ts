import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
import { clearViewCache } from "../lib/viewCache";

afterEach(() => {
  cleanup();
  clearViewCache();
  // A remembered workspace capture default would otherwise leak into the next test.
  Object.keys(window.localStorage).filter(key => key.startsWith("vsign.captureDefault:"))
    .forEach(key => window.localStorage.removeItem(key));
  // So does a page section remembered in the URL.
  const url = new URL(window.location.href);
  if (url.searchParams.has("tab")) { url.searchParams.delete("tab"); window.history.replaceState(null, "", url); }
});
