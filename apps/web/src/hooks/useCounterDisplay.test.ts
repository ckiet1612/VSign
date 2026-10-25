import { act, renderHook, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useCounterDisplay, type DisplayContent } from "./useCounterDisplay";

const receiver = vi.hoisted(() => ({ reset: vi.fn(), handleSignal: vi.fn() }));
vi.mock("./useDisplayPeer", () => ({
  useDisplayReceiver: () => ({ state: "idle", stream: null, requestOffer: vi.fn(), ...receiver }),
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
  messages() { return this.sent.map(raw => JSON.parse(raw)).filter(message => message.type !== "ping"); }
}

const overview = { api_version: "1", workspace_id: "local", permissions: { manage: false },
  displays: [{ id: "d1", name: "Quầy 1", online: true, staff: null, last_seen_at: null, created_at: "2026-10-21T00:00:00Z" }], enrollments: [] };
const content = (sentence: string): DisplayContent => ({ phase: "ok", word: "Tôi", words: ["Tôi"], sentence, guide: "fixed" });
const options = { platformUrl: "http://localhost:8000", enabled: true, storageKey: "vsign.counterDisplay:local:u1" };

beforeEach(() => {
  vi.stubGlobal("WebSocket", Socket);
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(overview))));
  window.localStorage.clear();
});
afterEach(() => { vi.unstubAllGlobals(); Socket.all = []; receiver.reset.mockClear(); });

async function connected() {
  const hook = renderHook(() => useCounterDisplay(options));
  await waitFor(() => expect(hook.result.current.overview).not.toBeNull());
  expect(hook.result.current.remoteStream).toBeUndefined();
  act(() => hook.result.current.connect("d1"));
  const socket = Socket.all[0];
  expect(socket.url).toBe("ws://localhost:8000/ws/display/d1?role=staff");
  act(() => {
    socket.open();
    socket.receive({ type: "welcome", role: "staff", display: { id: "d1", name: "Quầy 1" }, ice_servers: [] });
    socket.receive({ type: "peer", role: "device", online: true });
  });
  return { ...hook, socket };
}

it("remembers the counter and mirrors coalesced, de-duplicated results to it", async () => {
  const { result, socket } = await connected();
  expect(window.localStorage.getItem(options.storageKey)).toBe("d1");
  expect(result.current.remoteStream).toBeNull();
  expect(result.current.displayName).toBe("Quầy 1");

  act(() => { result.current.publish(content("a")); result.current.publish(content("ab")); });
  await waitFor(() => expect(socket.messages()).toHaveLength(1));
  act(() => result.current.publish(content("ab")));
  await new Promise(resolve => setTimeout(resolve, 80));
  const [first] = socket.messages();
  expect(socket.messages()).toHaveLength(1);
  expect(first).toMatchObject({ type: "display_state", revision: 1, sentence: "ab" });

  act(() => result.current.newConversation());
  const command = socket.messages()[1];
  expect(command).toMatchObject({ type: "command", name: "new_conversation" });
  expect(command.conversation_id).not.toBe(first.conversation_id);
  act(() => result.current.publish(content("")));
  await waitFor(() => expect(socket.messages()[2]).toMatchObject({ conversation_id: command.conversation_id, revision: 1 }));
});

it("keeps publishing after React's development double mount cancels a pending update", async () => {
  // Like App: the state is published from an effect, so a timer is already pending when Strict Mode remounts.
  const hook = renderHook(() => {
    const display = useCounterDisplay(options);
    useEffect(() => { display.publish(content("a")); });
    return display;
  }, { reactStrictMode: true });
  await waitFor(() => expect(hook.result.current.overview).not.toBeNull());
  act(() => hook.result.current.connect("d1"));
  const socket = Socket.all[0];
  act(() => {
    socket.open();
    socket.receive({ type: "welcome", role: "staff", display: { id: "d1", name: "Quầy 1" }, ice_servers: [] });
    socket.receive({ type: "peer", role: "device", online: true });
  });
  await waitFor(() => expect(socket.messages()).toContainEqual(expect.objectContaining({ type: "display_state", sentence: "a" })));
});

it("drops the frozen video when the counter goes away and ends the session cleanly", async () => {
  const { result, socket } = await connected();
  act(() => socket.receive({ type: "peer", role: "device", online: false }));
  expect(result.current.deviceOnline).toBe(false);
  expect(receiver.reset).toHaveBeenCalled();

  act(() => result.current.endSession());
  expect(socket.messages().at(-1)).toMatchObject({ type: "command", name: "end_session" });
  expect(result.current.connected).toBe(false);
  expect(result.current.remoteStream).toBeUndefined();
  expect(window.localStorage.getItem(options.storageKey)).toBeNull();
});

it("reports who occupies a counter and can take it over", async () => {
  const { result } = renderHook(() => useCounterDisplay(options));
  act(() => result.current.connect("d1"));
  act(() => { Socket.all[0].open(); Socket.all[0].receive({ type: "occupied", staff_name: "Minh" }); Socket.all[0].drop(4009); });
  expect(result.current.occupiedBy).toBe("Minh");
  expect(result.current.connected).toBe(false);
  act(() => result.current.connect("d1", true));
  expect(Socket.all[1].url).toBe("ws://localhost:8000/ws/display/d1?role=staff&takeover=1");
  expect(result.current.occupiedBy).toBeNull();
});

it("forgets a revoked counter and explains a takeover", async () => {
  const { result, socket } = await connected();
  act(() => { socket.receive({ type: "taken_over", by: "Minh" }); socket.drop(4010); });
  expect(result.current.notice).toBe("Minh đã tiếp quản quầy này.");
  expect(result.current.connected).toBe(false);
  expect(result.current.selectedId).toBe("d1");

  act(() => result.current.connect("d1"));
  act(() => { Socket.all[1].open(); Socket.all[1].drop(4003); });
  expect(result.current.notice).toBe("Màn hình quầy này đã bị huỷ.");
  expect(result.current.selectedId).toBeNull();
  expect(window.localStorage.getItem(options.storageKey)).toBeNull();
});

it("passes the customer's undo through for the current conversation only", async () => {
  const onCustomerAction = vi.fn();
  const hook = renderHook(() => useCounterDisplay({ ...options, onCustomerAction }));
  await waitFor(() => expect(hook.result.current.overview).not.toBeNull());
  act(() => hook.result.current.connect("d1"));
  const socket = Socket.all[0];
  act(() => { socket.open(); socket.receive({ type: "peer", role: "device", online: true }); });
  act(() => hook.result.current.publish(content("a")));
  await waitFor(() => expect(socket.messages()).toHaveLength(1));
  const conversation = socket.messages()[0].conversation_id;
  act(() => socket.receive({ type: "customer_action", action: "undo_word", conversation_id: "stale" }));
  expect(onCustomerAction).not.toHaveBeenCalled();
  act(() => socket.receive({ type: "customer_action", action: "undo_word", conversation_id: conversation }));
  expect(onCustomerAction).toHaveBeenCalledWith("undo_word");
});
