import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import DevTestApp from "./DevTestApp";

afterEach(() => vi.unstubAllGlobals());
function backend(trials: unknown[] = []) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(JSON.stringify(
    url.endsWith("/config") ? { enabled: true, backend: "coreml", model_version: "fixture-v1", runtime_key: "runtime-a",
      labels: ["Mua", "Tôi", "Không ký hiệu"], confidence_threshold: .7, margin_threshold: .15, mock: false, candidate_labels_unverified: false }
      : url.endsWith("/summary") ? { groups: [], recorded: trials.length }
      : { trials },
  ))));
}

it("offers the exact active vocabulary and a separate negative-action selector", async () => {
  backend(); render(<DevTestApp />);
  const select = await screen.findByRole("combobox", { name: "Từ kỳ vọng" });
  await waitFor(() => expect(select).toHaveValue("Mua"));
  expect(screen.getByText("Confidence 70.0% · Margin 15.0%")).toBeInTheDocument();
  expect(screen.queryByRole("combobox", { name: "Chuyển động nền" })).not.toBeInTheDocument();
  fireEvent.change(select, { target: { value: "Không ký hiệu" } });
  expect(screen.getByRole("combobox", { name: "Chuyển động nền" })).toHaveValue("still");
  expect(screen.getByRole("button", { name: "Bắt đầu test" })).toBeDisabled();
});

it("keeps invalid clips visible and opens video review without changing the prediction", async () => {
  backend([{ trial_id: "trial-1", session_id: sessionStorage.getItem("vsign-dev-test-session") ?? "old-session",
    expected_label: "Mua", signer_id: "staff", captured_at: 1791650000000, outcome: "wrong", video_available: true,
    prediction: { status: "ok", label: "Tôi", confidence: .95 }, model_version: "fixture-v1", inference_ms: 100,
    review: { valid: false, notes: "Thiếu cuối", reviewer: "staff" }, review_history: [] }]);
  render(<DevTestApp />);
  fireEvent.click(screen.getByRole("checkbox", { name: "Tất cả phiên" }));
  expect(await screen.findByText("Nhận nhầm")).toBeInTheDocument();
  expect(screen.getByText("Loại khỏi thống kê")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Xem clip" }));
  const dialog = screen.getByRole("dialog", { name: "Kiểm định clip" });
  expect(dialog.querySelector("video")?.getAttribute("src")).toContain("/dev-tests/trials/trial-1/video");
  expect(screen.getByRole("checkbox", { name: "Clip hợp lệ" })).not.toBeChecked();
});
