import { useCallback, useEffect, useRef, useState } from "react";
import {
  DISPLAY_CLOSE,
  parseServerDisplayMessage,
  type ClientDisplayMessage,
  type ServerDisplayMessage,
} from "../../../../contracts/v1/display";

export type DisplayChannelStatus = "idle" | "connecting" | "open" | "reconnecting" | "closed";

const PING_MS = 5000;
// No reply (not even a pong) for this long means the network is gone, even if the socket has not noticed.
const SILENCE_MS = 12000;
const BACKOFF_MS = [1000, 2000, 5000];

export function displaySocketUrl(platformUrl: string, displayId: string, role: "staff" | "device", takeover = false): string {
  const base = platformUrl.replace(/\/$/, "").replace(/^http/, "ws");
  return `${base}/ws/display/${encodeURIComponent(displayId)}?role=${role}${takeover ? "&takeover=1" : ""}`;
}

interface Options {
  /** null keeps the channel closed. A new URL opens a new connection. */
  url: string | null;
  onMessage: (message: ServerDisplayMessage) => void;
  /** Called when the server ends the channel for good (revoked, taken over, occupied, ended, replaced). */
  onEnded?: (code: number) => void;
}

/**
 * The /ws/display socket shared by the staff recognizer and the counter display. It pings, notices a silent
 * network, and reconnects with backoff, except after a close code that says reconnecting is pointless.
 */
export function useDisplayChannel({ url, onMessage, onEnded }: Options) {
  const [status, setStatus] = useState<DisplayChannelStatus>("idle");
  const socketRef = useRef<WebSocket | null>(null);
  const handlers = useRef({ onMessage, onEnded });
  handlers.current = { onMessage, onEnded };

  useEffect(() => {
    if (!url) { setStatus("idle"); return; }
    let disposed = false, attempt = 0, retry = 0, ping = 0, lastHeard = 0;
    const terminal = new Set<number>(Object.values(DISPLAY_CLOSE));
    const connect = () => {
      if (disposed) return;
      setStatus(attempt ? "reconnecting" : "connecting");
      const socket = new WebSocket(url);
      socketRef.current = socket;
      socket.onopen = () => {
        if (disposed) return;
        attempt = 0; lastHeard = Date.now();
        setStatus("open");
        ping = window.setInterval(() => {
          if (Date.now() - lastHeard > SILENCE_MS) { socket.close(); return; }
          if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "ping" }));
        }, PING_MS);
      };
      socket.onmessage = event => {
        lastHeard = Date.now();
        const message = parseServerDisplayMessage(event.data);
        if (message && !disposed) handlers.current.onMessage(message);
      };
      socket.onclose = event => {
        window.clearInterval(ping);
        if (socketRef.current === socket) socketRef.current = null;
        if (disposed) return;
        // 1008 is a refused login or a refused device: retrying cannot succeed until something else changes.
        if (terminal.has(event.code) || event.code === 1008) {
          setStatus("closed");
          handlers.current.onEnded?.(event.code);
          return;
        }
        setStatus("reconnecting");
        retry = window.setTimeout(connect, BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)]);
        attempt += 1;
      };
    };
    connect();
    return () => {
      disposed = true;
      window.clearTimeout(retry);
      window.clearInterval(ping);
      const socket = socketRef.current;
      socketRef.current = null;
      if (socket) {
        socket.onopen = socket.onmessage = socket.onclose = null;
        socket.close();
      }
    };
  }, [url]);

  const send = useCallback((message: ClientDisplayMessage) => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;
    socket.send(JSON.stringify(message));
    return true;
  }, []);

  return { status, send };
}
