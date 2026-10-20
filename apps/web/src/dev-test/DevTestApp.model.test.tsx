import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import DevTestApp from "./DevTestApp";

afterEach(() => vi.unstubAllGlobals());
const labels = [...Array.from({ length: 30 }, (_, i) => `word-${i}`), "Không ký hiệu"];
const oldVersion = "sales30-mvitv2s-personal-v1-head-epoch29";
const newVersion = "sales30-mvitv2s-seated-personal-v1-head-epoch33";
function backend(enabled = true) {
  vi.stubGlobal("fetch", async (url: string) => {
    const candidate = url.includes(":8003");
    const runtime = { enabled: candidate ? enabled : true, backend: "coreml", model_version: candidate ? newVersion : oldVersion,
      runtime_key: candidate ? "new-key" : "old-key", labels, confidence_threshold: .7, margin_threshold: .15,
      mock: false, candidate_labels_unverified: false, protocol_version: "1.0", frame_count: 16,
      frame_width: 224, frame_height: 224, supported_image_formats: ["image/jpeg"],
      collection_enabled: false, collection_labels: labels.slice(0, 30), collection_target_per_hand: 50, sentence_ai_enabled: false };
    return new Response(JSON.stringify(url.endsWith("/metadata") || url.endsWith("/config") ? runtime
      : url.endsWith("/summary") ? { groups: [], recorded: 0 } : { trials: [] }));
  });
}

it("switches manual testing to the candidate runtime and back", async () => {
  backend();
  const user = userEvent.setup();
  render(<DevTestApp />);
  await screen.findByText(oldVersion);
  const select = screen.getByRole("combobox", { name: "Model máy chủ" });
  await waitFor(() => expect(select).toBeEnabled());
  await user.selectOptions(select, "seated");
  await screen.findByText(newVersion);
  expect(select).toHaveValue("seated");
  await waitFor(() => expect(select).toBeEnabled());
  await user.selectOptions(select, "current");
  await screen.findByText(oldVersion);
  expect(select).toHaveValue("current");
});

it("does not switch manual testing to a backend without test APIs", async () => {
  backend(false);
  const user = userEvent.setup();
  render(<DevTestApp />);
  await screen.findByText(oldVersion);
  const select = screen.getByRole("combobox", { name: "Model máy chủ" });
  await waitFor(() => expect(select).toBeEnabled());
  await user.selectOptions(select, "seated");
  await screen.findByRole("alert");
  expect(select).toHaveValue("current");
  expect(screen.getByText(oldVersion)).toBeInTheDocument();
});

it("allows rollback when candidate config fails after a successful preflight", async () => {
  backend();
  const original = fetch;
  let candidateConfig = 0;
  vi.stubGlobal("fetch", async (url: string) => {
    if (url.includes(":8003") && url.endsWith("/config") && ++candidateConfig > 1) {
      return new Response(JSON.stringify({ detail: "offline after preflight" }), { status: 503 });
    }
    return original(url);
  });
  const user = userEvent.setup();
  render(<DevTestApp />);
  await screen.findByText(oldVersion);
  const select = screen.getByRole("combobox", { name: "Model máy chủ" });
  await waitFor(() => expect(select).toBeEnabled());
  await user.selectOptions(select, "seated");
  await screen.findByText(/offline after preflight/);
  expect(select).toHaveValue("seated");
  expect(select).toBeEnabled();
  await user.selectOptions(select, "current");
  await screen.findByText(oldVersion);
  expect(select).toHaveValue("current");
});
