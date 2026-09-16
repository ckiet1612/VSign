import { type RefObject, useCallback, useEffect, useRef, useState } from "react";

export type CameraStatus =
  | "off"
  | "requesting"
  | "ready"
  | "denied"
  | "unavailable"
  | "busy"
  | "interrupted"
  | "error";

const cameraMessages: Record<CameraStatus, string> = {
  off: "Camera đang tắt.",
  requesting: "Đang xin quyền dùng camera…",
  ready: "Camera đã sẵn sàng.",
  denied: "Quyền camera bị từ chối. Hãy cho phép camera trong cài đặt trình duyệt.",
  unavailable: "Không tìm thấy camera phù hợp trên thiết bị này.",
  busy: "Camera có thể đang được ứng dụng khác sử dụng.",
  interrupted: "Luồng camera đã bị ngắt. Hãy bật lại camera.",
  error: "Không thể bật camera. Hãy kiểm tra trình duyệt và thử lại.",
};

function classifyCameraError(error: unknown): CameraStatus {
  if (!(error instanceof DOMException)) return "error";
  if (error.name === "NotAllowedError" || error.name === "SecurityError") {
    return "denied";
  }
  if (error.name === "NotFoundError" || error.name === "OverconstrainedError") {
    return "unavailable";
  }
  if (error.name === "NotReadableError" || error.name === "AbortError") {
    return "busy";
  }
  return "error";
}

export interface CameraController {
  status: CameraStatus;
  message: string;
  enable: () => Promise<void>;
  disable: () => void;
}

function stopTracks(stream: MediaStream): void {
  for (const track of stream.getTracks()) track.stop();
}

export function useCamera(
  videoRef: RefObject<HTMLVideoElement | null>,
): CameraController {
  const [status, setStatus] = useState<CameraStatus>("off");
  const streamRef = useRef<MediaStream | null>(null);
  const mountedRef = useRef(true);
  const requestIdRef = useRef(0);
  const requestingRef = useRef(false);
  const removeEndedListenersRef = useRef<(() => void) | null>(null);

  const stopStream = useCallback(() => {
    removeEndedListenersRef.current?.();
    removeEndedListenersRef.current = null;
    const stream = streamRef.current;
    streamRef.current = null;
    if (stream) stopTracks(stream);
    if (videoRef.current) videoRef.current.srcObject = null;
  }, [videoRef]);

  const disable = useCallback(() => {
    requestIdRef.current += 1;
    requestingRef.current = false;
    stopStream();
    if (mountedRef.current) setStatus("off");
  }, [stopStream]);

  const enable = useCallback(async () => {
    if (requestingRef.current || streamRef.current) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      if (mountedRef.current) setStatus("unavailable");
      return;
    }
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    requestingRef.current = true;
    setStatus("requesting");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: { ideal: "user" },
          width: { ideal: 1280 },
          height: { ideal: 720 },
          frameRate: { ideal: 30 },
        },
      });
      if (!mountedRef.current || requestId !== requestIdRef.current) {
        stopTracks(stream);
        return;
      }
      stopStream();
      streamRef.current = stream;
      const handleEnded = () => {
        if (!mountedRef.current || streamRef.current !== stream) return;
        stopStream();
        setStatus("interrupted");
      };
      const videoTracks = stream.getVideoTracks();
      for (const track of videoTracks) {
        track.addEventListener("ended", handleEnded, { once: true });
      }
      removeEndedListenersRef.current = () => {
        for (const track of videoTracks) {
          track.removeEventListener("ended", handleEnded);
        }
      };
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => undefined);
      }
      if (
        !mountedRef.current ||
        requestId !== requestIdRef.current ||
        streamRef.current !== stream
      ) {
        if (streamRef.current === stream) stopStream();
        else stopTracks(stream);
        return;
      }
      setStatus("ready");
    } catch (error) {
      if (mountedRef.current && requestId === requestIdRef.current) {
        stopStream();
        setStatus(classifyCameraError(error));
      }
    } finally {
      if (requestId === requestIdRef.current) requestingRef.current = false;
    }
  }, [stopStream, videoRef]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestIdRef.current += 1;
      requestingRef.current = false;
      stopStream();
    };
  }, [stopStream]);

  return { status, message: cameraMessages[status], enable, disable };
}
