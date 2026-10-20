import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import DevTestApp from "./DevTestApp";

vi.mock("../lib/frameEncoder", () => ({ encodeFrames: async (frames: unknown[]) => frames.map(() => "encoded-frame") }));

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("records camera loss during a buffered capture as technical, never ordinary inference", async () => {
  const track = new EventTarget() as EventTarget & { readyState: string; stop: () => void };
  track.readyState = "live";
  track.stop = () => { track.readyState = "ended"; };
  const stream = { active: true, getTracks: () => [track], getVideoTracks: () => [track] };
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
  vi.spyOn(HTMLMediaElement.prototype, "readyState", "get").mockReturnValue(2);
  vi.stubGlobal("createImageBitmap", async () => ({ width: 1280, height: 720, close: () => undefined }));
  vi.stubGlobal("navigator", { ...navigator, mediaDevices: { getUserMedia: async () => stream } });
  const requests: Record<string, unknown>[] = [];
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    if (url.endsWith("/config")) return new Response(JSON.stringify({ enabled: true, backend: "coreml", model_version: "fixture", runtime_key: "key",
      labels: ["Mua", ...Array.from({ length: 29 }, (_, i) => `word-${i}`), "Không ký hiệu"], confidence_threshold: .7, margin_threshold: .15, mock: false, candidate_labels_unverified: false }));
    if (url.endsWith("/summary")) return new Response(JSON.stringify({ groups: [], recorded: requests.length }));
    if (init?.method === "POST") {
      const value = JSON.parse(init.body as string); requests.push(value);
      if (requests.length === 1) return new Response(JSON.stringify({ detail: "Lost save acknowledgement" }), { status: 503 });
      return new Response(JSON.stringify({ ...value, outcome: value.technical_error ? "technical_error" : "correct", prediction: null, inference_ms: null }));
    }
    return new Response(JSON.stringify({ trials: [] }));
  });
  render(<DevTestApp />);
  await waitFor(() => expect(screen.getByRole("combobox", { name: "Từ kỳ vọng" })).toHaveValue("Mua"));
  fireEvent.change(screen.getByRole("textbox", { name: "Người ký" }), { target: { value: "tester" } });
  fireEvent.click(screen.getByRole("button", { name: "Bật camera" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Bắt đầu test" })).not.toBeDisabled());
  expect(screen.getByRole("combobox", { name: "Model máy chủ" })).toBeEnabled();
  vi.useFakeTimers();
  fireEvent.click(screen.getByRole("button", { name: "Bắt đầu test" }));
  expect(screen.getByRole("combobox", { name: "Model máy chủ" })).toBeDisabled();
  await act(() => vi.advanceTimersByTimeAsync(900));
  act(() => { track.readyState = "ended"; stream.active = false; track.dispatchEvent(new Event("ended")); });
  await act(() => vi.advanceTimersByTimeAsync(3500));
  vi.useRealTimers();
  expect(requests).toHaveLength(1);
  expect(requests[0].technical_error).toBeTruthy();
  expect(requests[0].frames).toEqual([]);
  expect(requests[0].source_frames).toEqual([]);
  expect(screen.getByRole("combobox", { name: "Model máy chủ" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Thử lưu lại" }));
  await waitFor(() => expect(requests).toHaveLength(2));
  expect(requests[1].trial_id).toBe(requests[0].trial_id);
  await waitFor(() => expect(screen.getByRole("combobox", { name: "Model máy chủ" })).toBeEnabled());
});
