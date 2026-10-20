import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import App from "./App";
import type { AuthenticatedUser } from "@workspace-contracts";

let auditUser: AuthenticatedUser | null = null;

vi.mock("./hooks/useWorkspacePlatform", async () => {
  const { localWorkspacePlatform } = await import("./test/workspacePlatformFixture");
  return { useWorkspacePlatform: () => ({ ...localWorkspacePlatform(), user: auditUser }) };
});

const labels = [...Array.from({ length: 30 }, (_, i) => `word-${i}`), "Không ký hiệu"];
const currentVersion = "sales30-mvitv2s-personal-v1-head-epoch29";
const candidateVersion = "sales30-mvitv2s-seated-personal-v1-head-epoch20";
let offline = false;
class Socket {
  readyState = 0;
  onopen = null;
  onmessage = null;
  onerror = null;
  onclose = null;
  constructor(public url: string) {}
  close() {}
  send() {}
}
beforeEach(() => {
  offline = false;
  auditUser = { id: "internal-1", email: "internal@example.com", display_name: "Internal", role: "model_admin" };
  vi.stubGlobal("WebSocket", Socket);
  vi.stubGlobal("fetch", async (input: string | URL | Request) => {
    const seated = String(input).includes(":8003");
    if (seated && offline) throw new Error("offline");
    return new Response(JSON.stringify({ backend: "coreml", model_version: seated ? candidateVersion : currentVersion,
      protocol_version: "1.0", frame_count: 16, frame_width: 224, frame_height: 224,
      supported_image_formats: ["image/jpeg", "image/webp"], confidence_threshold: .7, margin_threshold: .15,
      labels, collection_labels: labels.slice(0, 30), candidate_labels_unverified: false, mock: false,
      collection_enabled: false, collection_target_per_hand: 50, sentence_ai_enabled: false }));
  });
});

it("records a verified model switch as a browser report through the platform endpoint", async () => {
  auditUser = { id: "owner-1", email: "owner@example.com", display_name: "Internal", role: "model_admin" };
  const baseFetch = fetch;
  const submitted: Array<{ url: string; body: Record<string, unknown>; credentials?: RequestCredentials }> = [];
  vi.stubGlobal("fetch", async (input: string | URL | Request, init?: RequestInit) => {
    if (String(input).includes("/audit/client-events")) {
      const body = JSON.parse(String(init?.body));
      submitted.push({ url: String(input), body, credentials: init?.credentials });
      return new Response(JSON.stringify({ status: "recorded", event_id: body.event_id }), { status: 201 });
    }
    return baseFetch(input, init);
  });
  render(<App />);
  await userEvent.click(screen.getByText("Cấu hình AI", { exact: true }));
  await screen.findByText(new RegExp(currentVersion));
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "Model máy chủ" }), "seated");
  await screen.findByText(new RegExp(candidateVersion));
  await waitFor(() => expect(submitted).toHaveLength(1));
  expect(submitted[0].url).toBe("http://localhost:8000/api/v1/workspace/audit/client-events");
  expect(submitted[0].credentials).toBe("include");
  expect(submitted[0].body).toMatchObject({ event_type: "model.switched", previous_model_version: currentVersion,
    model_version: candidateVersion, previous_model_option: "current", model_option: "seated" });
  expect(submitted[0].body).not.toHaveProperty("actor_id");
});

it("switches model identity and allows returning to the old model", async () => {
  const user = userEvent.setup();
  render(<App />);
  await user.click(screen.getByText("Cấu hình AI", { exact: true }));
  await screen.findByText(new RegExp(currentVersion));
  const select = screen.getByRole("combobox", { name: "Model máy chủ" });
  expect(select).toHaveValue("current");
  await user.selectOptions(select, "seated");
  await screen.findByText(new RegExp(candidateVersion));
  expect(select).toHaveValue("seated");
  await user.selectOptions(select, "current");
  await screen.findByText(new RegExp(currentVersion));
  expect(select).toHaveValue("current");
});

it("opens the backed models page without confusing endpoint selection with deployment", async () => {
  auditUser = null;
  window.history.replaceState(null, "", "/?view=models");
  try {
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Mô hình nhận dạng", level: 1 })).toHaveAttribute("id", "workspace-page-title");
    expect(await screen.findByRole("heading", { name: /Đăng nhập VSign/ })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Runtime đang chọn · Dev/Test" })).not.toBeInTheDocument();
    expect(screen.queryByText("Production endpoint")).not.toBeInTheDocument();
  } finally {
    window.history.replaceState(null, "", "/");
  }
});

it("keeps current model identity when the candidate is offline", async () => {
  const user = userEvent.setup();
  render(<App />);
  await user.click(screen.getByText("Cấu hình AI", { exact: true }));
  await screen.findByText(new RegExp(currentVersion));
  offline = true;
  await user.selectOptions(screen.getByRole("combobox", { name: "Model máy chủ" }), "seated");
  await screen.findByRole("alert");
  expect(screen.getByRole("combobox", { name: "Model máy chủ" })).toHaveValue("current");
  expect(screen.getByText(new RegExp(currentVersion))).toBeInTheDocument();
});

it("keeps a delayed model-switch failure visible after opening another disclosure", async () => {
  const currentFetch = fetch;
  let rejectSwitch!: (reason: Error) => void;
  vi.stubGlobal("fetch", (input: string | URL | Request) => String(input).includes(":8003")
    ? new Promise<Response>((_resolve, reject) => { rejectSwitch = reject; })
    : currentFetch(input));
  const user = userEvent.setup();
  render(<App />);
  await user.click(screen.getByText("Cấu hình AI", { exact: true }));
  await screen.findByText(new RegExp(currentVersion));
  await user.selectOptions(screen.getByRole("combobox", { name: "Model máy chủ" }), "seated");
  await waitFor(() => expect(screen.getByRole("combobox", { name: "Model máy chủ" })).toBeDisabled());
  await user.click(screen.getByText("Công cụ", { exact: true }));
  screen.getByRole("link", { name: "Dev / Test" }).focus();
  // jsdom does not implement exclusive native details groups.
  screen.getByText("Cấu hình AI", { exact: true }).closest("details")!.open = false;
  rejectSwitch(new Error("offline"));
  const alert = await screen.findByRole("alert");
  expect(alert).toBeVisible();
  expect(alert.closest("details")).toBeNull();
  expect(alert).toHaveClass("model-switch-error");
  await waitFor(() => expect(screen.getByText("Công cụ", { exact: true }).closest("details")).not.toHaveAttribute("open"));
  expect(screen.getByText("Cấu hình AI", { exact: true }).closest("details")).not.toHaveAttribute("open");
  expect(screen.getByText("Công cụ", { exact: true }).closest("summary")).toHaveFocus();
  expect(screen.getByLabelText("Model máy chủ")).toHaveValue("current");
});

it("keeps switching unavailable until the old label order is loaded", async () => {
  let complete!: (value: Response) => void;
  vi.stubGlobal("fetch", () => new Promise<Response>(resolve => { complete = resolve; }));
  render(<App />);
  await userEvent.click(screen.getByText("Cấu hình AI", { exact: true }));
  expect(screen.getByRole("combobox", { name: "Model máy chủ" })).toBeDisabled();
  complete(new Response(JSON.stringify({ labels, model_version: currentVersion, mock: false, candidate_labels_unverified: false })));
  await waitFor(() => expect(screen.getByRole("combobox", { name: "Model máy chủ" })).toBeEnabled());
});
