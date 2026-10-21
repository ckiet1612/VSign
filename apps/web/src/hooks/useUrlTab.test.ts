import { act, renderHook } from "@testing-library/react";
import { expect, it } from "vitest";
import { useUrlTab } from "./useUrlTab";

const tabs = ["first", "second", "third"] as const;

it("reopens the section named in the URL and writes changes back", () => {
  window.history.replaceState(null, "", "/?view=data&tab=second");
  const { result } = renderHook(() => useUrlTab(tabs, "first"));
  expect(result.current[0]).toBe("second");
  act(() => result.current[1]("third"));
  expect(window.location.search).toBe("?view=data&tab=third");
  act(() => result.current[1]("first"));
  expect(window.location.search).toBe("?view=data");
});

it("ignores an unknown section and leaves the URL alone while inactive", () => {
  window.history.replaceState(null, "", "/?view=models&tab=bogus");
  const { result } = renderHook(() => useUrlTab(tabs, "first", false));
  expect(result.current[0]).toBe("first");
  act(() => result.current[1]("second"));
  expect(window.location.search).toBe("?view=models&tab=bogus");
  window.history.replaceState(null, "", "/");
});
