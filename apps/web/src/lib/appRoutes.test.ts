import { afterEach, expect, it, vi } from "vitest";
import { config } from "../config";
import { isLandingPath, workspaceHref } from "./appRoutes";

afterEach(() => vi.restoreAllMocks());

it("reserves the root for landing while keeping old workspace links", () => {
  expect(isLandingPath("/")).toBe(true);
  expect(isLandingPath("/landing")).toBe(true);
  expect(isLandingPath("/workspace")).toBe(false);
  expect(isLandingPath("/", "?view=models")).toBe(false);
  expect(isLandingPath("/", "?login=staff")).toBe(false);
  expect(workspaceHref()).toBe("/workspace");
  expect(workspaceHref("?login=staff")).toBe("/workspace?login=staff");
});

it("keeps the public demo at its existing root", () => {
  vi.spyOn(config, "publicDemo", "get").mockReturnValue(true);
  expect(isLandingPath("/")).toBe(false);
});
