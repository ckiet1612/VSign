import { useCallback, useEffect, useRef, useState } from "react";
import {
  DISPLAY_CLOSE,
  type CustomerActionMessage,
  type DisplayOverview,
  type DisplayStateMessage,
  type ServerDisplayMessage,
} from "../../../../contracts/v1/display";
import { workspaceRequest } from "../lib/workspaceApi";
import { displaySocketUrl, useDisplayChannel } from "./useDisplayChannel";
import { useDisplayReceiver } from "./useDisplayPeer";

export type DisplayContent = Omit<DisplayStateMessage, "type" | "conversation_id" | "revision">;

const LIST_REFRESH_MS = 15000;
const PUBLISH_DELAY_MS = 50;

function conversationId(): string {
  return globalThis.crypto?.randomUUID?.().replace(/-/g, "") ?? Math.random().toString(36).slice(2);
}

function readStored(key: string | null): string | null {
  if (!key) return null;
  try { return window.localStorage.getItem(key); } catch { return null; }
}

function writeStored(key: string | null, value: string | null) {
  if (!key) return;
  try {
    if (value) window.localStorage.setItem(key, value);
    else window.localStorage.removeItem(key);
  } catch { /* Private mode: the counter is simply not remembered. */ }
}

interface Options {
  platformUrl: string;
  enabled: boolean;
  /** Per workspace and user, so a shared staff laptop does not reconnect someone else's counter. */
  storageKey: string | null;
  /** A button the customer pressed on the counter, for the conversation this recognizer is serving. */
  onCustomerAction?: (action: CustomerActionMessage["action"]) => void;
}

/**
 * Staff side of a counter display: which counter this recognizer serves, the customer's camera as a remote
 * stream, and the recognition results mirrored back to the counter.
 */
export function useCounterDisplay({ platformUrl, enabled, storageKey, onCustomerAction }: Options) {
  const [overview, setOverview] = useState<DisplayOverview | null>(null);
  const [listError, setListError] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(() => readStored(storageKey));
  const [active, setActive] = useState(() => readStored(storageKey) !== null);
  const [takeover, setTakeover] = useState(false);
  const [occupiedBy, setOccupiedBy] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [deviceOnline, setDeviceOnline] = useState(false);
  const [iceServers, setIceServers] = useState<RTCIceServer[]>([]);
  const [displayName, setDisplayName] = useState("");
  const conversation = useRef(conversationId());
  const revision = useRef(0);
  const customerAction = useRef(onCustomerAction);
  customerAction.current = onCustomerAction;

  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      const { body } = await workspaceRequest<DisplayOverview>(platformUrl, "/api/v1/displays", {}, signal);
      if (body) { setOverview(body); setListError(""); }
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) setListError("Chưa tải được danh sách quầy.");
    }
  }, [platformUrl]);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    void refresh(controller.signal);
    const timer = window.setInterval(() => { if (document.visibilityState === "visible") void refresh(); }, LIST_REFRESH_MS);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [enabled, refresh]);

  const url = enabled && active && selectedId ? displaySocketUrl(platformUrl, selectedId, "staff", takeover) : null;
  const sendRef = useRef<(message: Parameters<ReturnType<typeof useDisplayChannel>["send"]>[0]) => boolean>(() => false);
  const receiver = useDisplayReceiver({ active: url !== null, iceServers, send: message => sendRef.current(message) });
  const resetReceiver = receiver.reset;
  const handleSignal = receiver.handleSignal;

  const onMessage = useCallback((message: ServerDisplayMessage) => {
    switch (message.type) {
      case "welcome":
        setIceServers(message.ice_servers);
        setDisplayName(message.display.name);
        setOccupiedBy(null);
        break;
      case "peer":
        if (message.role === "device") {
          setDeviceOnline(message.online);
          // The counter offers fresh video as soon as it sees us; an old connection is only a frozen picture.
          if (!message.online) resetReceiver();
        }
        break;
      case "signal":
        handleSignal(message);
        break;
      case "occupied":
        setOccupiedBy(message.staff_name);
        break;
      case "taken_over":
        setNotice(`${message.by || "Một nhân viên khác"} đã tiếp quản quầy này.`);
        break;
      case "customer_action":
        // A press from the previous conversation, delivered late, must not undo the new customer's words.
        if (message.conversation_id === conversation.current) customerAction.current?.(message.action);
        break;
      default:
        break;
    }
  }, [handleSignal, resetReceiver]);

  const onEnded = useCallback((code: number) => {
    setActive(false);
    setTakeover(false);
    setDeviceOnline(false);
    resetReceiver();
    if (code === DISPLAY_CLOSE.revoked) {
      setNotice("Màn hình quầy này đã bị huỷ.");
      setSelectedId(null);
      writeStored(storageKey, null);
      void refresh();
    } else if (code === 1008) {
      setNotice("Không kết nối được quầy. Hãy tải lại danh sách và thử lại.");
    }
  }, [refresh, resetReceiver, storageKey]);

  const channel = useDisplayChannel({ url, onMessage, onEnded });
  sendRef.current = channel.send;
  const open = channel.status === "open";

  useEffect(() => { if (!open) setDeviceOnline(false); }, [open]);

  const connect = useCallback((id: string, takeOver = false) => {
    setSelectedId(id);
    writeStored(storageKey, id);
    setOccupiedBy(null);
    setNotice("");
    setTakeover(takeOver);
    setActive(true);
    conversation.current = conversationId();
    revision.current = 0;
  }, [storageKey]);

  const send = channel.send;
  const endSession = useCallback(() => {
    send({ type: "command", name: "end_session", conversation_id: conversation.current });
    writeStored(storageKey, null);
    setActive(false);
    setTakeover(false);
    setOccupiedBy(null);
    setNotice("");
  }, [send, storageKey]);

  const newConversation = useCallback(() => {
    conversation.current = conversationId();
    revision.current = 0;
    send({ type: "command", name: "new_conversation", conversation_id: conversation.current });
  }, [send]);

  // Results are coalesced: a burst of state changes in one recognition step reaches the counter as one message.
  const pending = useRef<DisplayContent | null>(null);
  const lastSent = useRef("");
  const timer = useRef(0);
  const flush = useCallback(() => {
    timer.current = 0;
    const content = pending.current;
    if (!content) return;
    const key = `${conversation.current}:${JSON.stringify(content)}`;
    if (key === lastSent.current) return;
    revision.current += 1;
    if (send({ type: "display_state", conversation_id: conversation.current, revision: revision.current, ...content })) {
      lastSent.current = key;
    }
  }, [send]);
  const publish = useCallback((content: DisplayContent) => {
    pending.current = content;
    if (!timer.current) timer.current = window.setTimeout(flush, PUBLISH_DELAY_MS);
  }, [flush]);
  // A reopened socket, or a counter that came back, starts from nothing: send the current state again.
  useEffect(() => {
    if (open && deviceOnline) { lastSent.current = ""; if (!timer.current) timer.current = window.setTimeout(flush, PUBLISH_DELAY_MS); }
  }, [open, deviceOnline, flush]);
  // Forget the cancelled timer too: a remount (React's development double mount) would otherwise never publish again.
  useEffect(() => () => { window.clearTimeout(timer.current); timer.current = 0; }, []);

  const connected = url !== null;
  return {
    overview, listError, refresh, selectedId, displayName: displayName || overview?.displays.find(row => row.id === selectedId)?.name || "",
    connected, channelStatus: channel.status, deviceOnline, occupiedBy, notice,
    videoState: receiver.state,
    /** undefined: no counter, use this device's webcam. null: counter connected, its video has not arrived. */
    remoteStream: connected ? receiver.stream : undefined,
    connect, endSession, newConversation, publish,
    dismissNotice: () => setNotice(""),
  };
}

export type CounterDisplayController = ReturnType<typeof useCounterDisplay>;
