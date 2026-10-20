import { useCallback, useEffect, useRef, useState } from "react";
import {
  isPredictionMessage,
  type FramesMessage,
  type PredictionMessage,
} from "@contracts";

export type ConnectionStatus = "connecting" | "connected" | "disconnected";

export interface InferenceSocket {
  status: ConnectionStatus;
  sendFrames: (message: FramesMessage) => void;
}

export function useInferenceSocket(
  url: string | null,
  onPrediction: (message: PredictionMessage) => void,
): InferenceSocket {
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [statusUrl, setStatusUrl] = useState(url);
  const socketRef = useRef<WebSocket | null>(null);
  const predictionRef = useRef(onPrediction);
  predictionRef.current = onPrediction;

  useEffect(() => {
    setStatusUrl(url);
    if (!url) {
      setStatus("disconnected");
      return;
    }
    let disposed = false;
    let reconnectTimer: number | undefined;

    const connect = () => {
      if (disposed) return;
      if (typeof WebSocket === "undefined") {
        setStatus("disconnected");
        return;
      }
      setStatus("connecting");
      const socket = new WebSocket(url);
      socketRef.current = socket;
      socket.onopen = () => {
        if (!disposed) setStatus("connected");
      };
      socket.onmessage = (event: MessageEvent<string>) => {
        if (disposed || socketRef.current !== socket) return;
        try {
          const parsed: unknown = JSON.parse(event.data);
          if (isPredictionMessage(parsed)) predictionRef.current(parsed);
        } catch {
          // A malformed server message is ignored; the next valid sequence can continue.
        }
      };
      socket.onerror = () => {
        if (!disposed) setStatus("disconnected");
      };
      socket.onclose = () => {
        if (socketRef.current === socket) socketRef.current = null;
        if (!disposed) {
          setStatus("disconnected");
          reconnectTimer = window.setTimeout(connect, 2_000);
        }
      };
    };

    connect();
    return () => {
      disposed = true;
      if (reconnectTimer !== undefined) window.clearTimeout(reconnectTimer);
      const socket = socketRef.current;
      socketRef.current = null;
      socket?.close();
    };
  }, [url]);

  const sendFrames = useCallback((message: FramesMessage) => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== 1) {
      throw new Error("Kết nối inference chưa sẵn sàng.");
    }
    socket.send(JSON.stringify(message));
  }, []);

  return { status: statusUrl === url ? status : "connecting", sendFrames };
}
