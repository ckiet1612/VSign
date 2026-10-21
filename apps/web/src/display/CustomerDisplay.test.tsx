import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CustomerDisplay } from "./CustomerDisplay";

const camera = vi.hoisted(() => ({ status: "off", enable: vi.fn(async () => undefined), disable: vi.fn() }));
vi.mock("../hooks/useCamera", () => ({
  useCamera: () => ({ ...camera, message: "" }),
}));
vi.mock("../hooks/useDisplayPeer", () => ({
  useDisplaySender: () => ({ state: "idle", handleSignal: vi.fn() }),
}));

class Socket {
  static OPEN = 1;
  static all: Socket[] = [];
  readyState = 0;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  constructor(public url: string) { Socket.all.push(this); }
  open() { this.readyState = 1; this.onopen?.(); }
  receive(data: unknown) { this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(data) })); }
  drop(code: number) { this.readyState = 3; this.onclose?.({ code }); }
  close() { this.readyState = 3; }
  send(data: string) { this.sent.push(data); }
}

const platformUrl = "http://localhost:8000";
const paired = { api_version: "1", state: "paired", workspace_name: "Cửa hàng", display: { id: "d1", name: "Quầy 1" } };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

beforeEach(() => { vi.stubGlobal("WebSocket", Socket); camera.status = "off"; });
afterEach(() => { vi.unstubAllGlobals(); Socket.all = []; window.history.replaceState(null, "", "/"); });

const state = (revision: number, extra: object = {}) => ({
  type: "display_state", conversation_id: "c1", revision, phase: "ok", word: "Xin chào",
  words: ["Xin chào"], sentence: "Xin chào bạn", guide: "fixed", ...extra,
});

it("pairs with a code and shows the verification code to compare", async () => {
  const fetcher = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(async url => url.endsWith("/claim")
    ? json({ api_version: "1", state: "awaiting_confirmation", workspace_name: "Cửa hàng", name: "Quầy 1", verification: "K7", expires_at: "2026-10-21T00:10:00Z" })
    : json({ api_version: "1", state: "unpaired", reason: null }));
  vi.stubGlobal("fetch", fetcher);
  render(<CustomerDisplay platformUrl={platformUrl} />);
  const input = await screen.findByLabelText("Mã 6 số");
  fireEvent.change(input, { target: { value: "12a3 456" } });
  expect(input).toHaveValue("123456");
  fireEvent.click(screen.getByRole("button", { name: "Đăng ký" }));
  expect(await screen.findByLabelText("Mã đối chiếu K 7")).toHaveTextContent("K7");
  const claim = fetcher.mock.calls.find(([url]) => url.endsWith("/claim"))!;
  expect(JSON.parse(String(claim[1]?.body))).toEqual({ code: "123456" });
});

it("claims a QR link once and removes the secret from the address bar", async () => {
  const token = "a".repeat(43);
  window.history.replaceState(null, "", `/display#token=${token}`);
  const fetcher = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(async url => url.endsWith("/claim")
    ? json({ detail: "Mã không hợp lệ hoặc đã hết hạn." }, 400)
    : json({ api_version: "1", state: "unpaired", reason: "revoked" }));
  vi.stubGlobal("fetch", fetcher);
  render(<CustomerDisplay platformUrl={platformUrl} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Mã không hợp lệ");
  expect(screen.getByText(/đã bị huỷ/)).toBeInTheDocument();
  expect(window.location.hash).toBe("");
  const claims = fetcher.mock.calls.filter(([url]) => url.endsWith("/claim"));
  expect(claims).toHaveLength(1);
  expect(JSON.parse(String(claims[0][1]?.body))).toEqual({ link_token: token });
});

it("waits with the camera off, shows words while served and clears them when staff leaves", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json(paired)));
  render(<CustomerDisplay platformUrl={platformUrl} />);
  await waitFor(() => expect(Socket.all).toHaveLength(1));
  expect(Socket.all[0].url).toBe("ws://localhost:8000/ws/display/d1?role=device");
  act(() => { Socket.all[0].open(); Socket.all[0].receive({ type: "welcome", role: "device", display: paired.display, ice_servers: [] }); });
  expect(screen.getByText("Xin chào!")).toBeInTheDocument();
  expect(camera.enable).not.toHaveBeenCalled();

  act(() => Socket.all[0].receive({ type: "peer", role: "staff", online: true, name: "Lan" }));
  expect(camera.enable).toHaveBeenCalled();
  act(() => { Socket.all[0].receive(state(2)); Socket.all[0].receive(state(1, { word: "Cũ" })); });
  expect(screen.getByText("Xin chào bạn")).toBeInTheDocument();
  expect(screen.queryByText("Cũ")).not.toBeInTheDocument();

  act(() => Socket.all[0].receive({ type: "command", name: "new_conversation", conversation_id: "c2" }));
  expect(screen.queryByText("Xin chào bạn")).not.toBeInTheDocument();
  expect(screen.getByText("Hãy bắt đầu ký")).toBeInTheDocument();

  act(() => { Socket.all[0].receive(state(0, { conversation_id: "c2", sentence: "Câu mới" })); });
  expect(screen.getByText("Câu mới")).toBeInTheDocument();
  act(() => Socket.all[0].receive({ type: "peer", role: "staff", online: false, name: null }));
  expect(screen.queryByText("Câu mới")).not.toBeInTheDocument();
  expect(screen.getByText("Xin chào!")).toBeInTheDocument();
});

it("warns instead of showing stale words when its own connection drops mid-service", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json(paired)));
  camera.status = "ready";
  render(<CustomerDisplay platformUrl={platformUrl} />);
  await waitFor(() => expect(Socket.all).toHaveLength(1));
  act(() => { Socket.all[0].open(); Socket.all[0].receive({ type: "peer", role: "staff", online: true, name: "Lan" }); });
  act(() => Socket.all[0].receive(state(1)));
  expect(screen.getByText("Xin chào bạn")).toBeInTheDocument();
  act(() => Socket.all[0].drop(1006));
  expect(screen.getByRole("alert")).toHaveTextContent("Mất kết nối với máy nhân viên");
  expect(screen.queryByText("Xin chào bạn")).not.toBeInTheDocument();
  expect(camera.disable).not.toHaveBeenCalledAfter(camera.enable);
});

it("returns to pairing when the screen is revoked", async () => {
  let me: object = paired;
  vi.stubGlobal("fetch", vi.fn(async () => json(me)));
  render(<CustomerDisplay platformUrl={platformUrl} />);
  await waitFor(() => expect(Socket.all).toHaveLength(1));
  act(() => Socket.all[0].open());
  me = { api_version: "1", state: "unpaired", reason: "revoked" };
  act(() => Socket.all[0].drop(4003));
  expect(await screen.findByLabelText("Mã 6 số", {}, { timeout: 2500 })).toBeInTheDocument();
  expect(screen.getByText(/đã bị huỷ/)).toBeInTheDocument();
});
