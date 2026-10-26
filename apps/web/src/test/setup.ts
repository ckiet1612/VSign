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
  // Reset route state as well as page sections so one component test cannot leak its deep link.
  window.history.replaceState(null, "", "/");
});
