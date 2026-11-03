import { useCallback, useEffect, useRef, useState } from "react";
import {
  isPredictionMessage,
  type FramesMessage,
  type PredictionMessage,
} from "@contracts";

export type ConnectionStatus = "connecting" | "connected" | "disconnected";

export interface InferenceSocket {
  status: ConnectionStatus;
  activeUrl: string | null;
  gpuName: string | null;
  sendFrames: (message: FramesMessage) => void;
}

interface ParkedSocket {
  socket: WebSocket;
  modelKey: string;
}

/**
 * `modelKey` names the model behind `url`. When only the URL changes for the same key (the same
 * model on another runtime, e.g. Modal GPU and the Mac), the open socket keeps serving until the
 * new one opens and `isBusy` clears. Both sends and replies stay on the old socket until then.
 */
export function useInferenceSocket(
  url: string | null,
  onPrediction: (message: PredictionMessage) => void,
  modelKey?: string,
  isBusy?: () => boolean,
): InferenceSocket {
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [activeUrl, setActiveUrl] = useState<string | null>(null);
  const [gpuName, setGpuName] = useState<string | null>(null);
  const [statusFor, setStatusFor] = useState({ url, modelKey });
  const socketRef = useRef<WebSocket | null>(null);
  const parkedRef = useRef<ParkedSocket | null>(null);
  const predictionRef = useRef(onPrediction);
  predictionRef.current = onPrediction;
  const busyRef = useRef(isBusy);
  busyRef.current = isBusy;

  const deliver = useCallback((event: MessageEvent<string>, serving = true): string | null => {
    try {
      const parsed: unknown = JSON.parse(event.data);
      if (parsed && typeof parsed === "object" && "type" in parsed && parsed.type === "runtime_info"
          && "gpu_name" in parsed && typeof parsed.gpu_name === "string") {
        if (serving) setGpuName(parsed.gpu_name);
        return parsed.gpu_name;
      }
      if (serving && isPredictionMessage(parsed)) predictionRef.current(parsed);
    } catch {
      // A malformed server message is ignored; the next valid sequence can continue.
    }
    return null;
  }, []);

  useEffect(() => {
    setStatusFor({ url, modelKey });
    const parked = parkedRef.current;
    if (parked && (modelKey === undefined || parked.modelKey !== modelKey || !url)) {
      parkedRef.current = null;
      parked.socket.close();
    }
    const releaseParked = () => {
      const previous = parkedRef.current;
      parkedRef.current = null;
      previous?.socket.close();
    };
    if (!url) {
      setStatus("disconnected");
      setActiveUrl(null);
      return;
    }
    let disposed = false;
    let reconnectTimer: number | undefined;
    let handoverTimer: number | undefined;

    const connect = () => {
      if (disposed) return;
      if (typeof WebSocket === "undefined") {
        setStatus("disconnected");
        setActiveUrl(null);
        return;
      }
      if (!parkedRef.current) {
        setStatus("connecting");
        setActiveUrl(null);
      }
      const socket = new WebSocket(url);
      socketRef.current = socket;
      let serving = false;
      let candidateGpuName: string | null = null;
      const handOver = () => {
        if (disposed || socketRef.current !== socket || socket.readyState !== 1) return;
        if (parkedRef.current && busyRef.current?.()) {
          handoverTimer = window.setTimeout(handOver, 100);
          return;
        }
        releaseParked();
        serving = true;
        setStatus("connected");
        setActiveUrl(url);
        setGpuName(candidateGpuName);
      };
      socket.onopen = handOver;
      socket.onmessage = (event: MessageEvent<string>) => {
        if (disposed || socketRef.current !== socket) return;
        const name = deliver(event, serving);
        if (name !== null) candidateGpuName = name;
      };
      socket.onerror = () => {
        if (!disposed && !parkedRef.current) {
          setStatus("disconnected");
          setActiveUrl(null);
        }
      };
      socket.onclose = () => {
        if (socketRef.current === socket) socketRef.current = null;
        if (!disposed) {
          if (handoverTimer !== undefined) window.clearTimeout(handoverTimer);
          if (!parkedRef.current || !busyRef.current?.()) {
            releaseParked();
            setStatus("disconnected");
            setActiveUrl(null);
          }
          reconnectTimer = window.setTimeout(connect, 2_000);
        }
      };
    };

    connect();
    return () => {
      disposed = true;
      if (reconnectTimer !== undefined) window.clearTimeout(reconnectTimer);
      if (handoverTimer !== undefined) window.clearTimeout(handoverTimer);
      const socket = socketRef.current;
      socketRef.current = null;
      if (socket && socket.readyState === 1 && modelKey !== undefined && !parkedRef.current) {
        // Keep serving on the old runtime until the next effect decides whether it may hand over.
        parkedRef.current = { socket, modelKey };
        socket.onmessage = deliver;
        socket.onclose = () => {
          if (parkedRef.current?.socket !== socket) return;
          parkedRef.current = null;
          setStatus("connecting");
          setActiveUrl(null);
        };
      } else {
        socket?.close();
      }
    };
  }, [url, modelKey, deliver]);

  useEffect(() => () => {
    parkedRef.current?.socket.close();
    parkedRef.current = null;
  }, []);

  const sendFrames = useCallback((message: FramesMessage) => {
    const current = socketRef.current;
    const socket = parkedRef.current?.socket ?? current;
    if (!socket || socket.readyState !== 1) {
      throw new Error("Kết nối inference chưa sẵn sàng.");
    }
    socket.send(JSON.stringify(message));
  }, []);

  const handingOver = modelKey !== undefined && statusFor.modelKey === modelKey && status === "connected";
  const connectionStatus = statusFor.url === url ? status : handingOver ? "connected" : "connecting";
  return {
    status: connectionStatus,
    activeUrl: connectionStatus === "connected" ? activeUrl : null,
    gpuName: connectionStatus === "connected" ? gpuName : null,
    sendFrames,
  };
}
