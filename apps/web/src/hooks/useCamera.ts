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

const remoteMessages: Partial<Record<CameraStatus, string>> = {
  off: "Đang chờ video từ máy khách.",
  requesting: "Đang nhận video từ máy khách…",
  ready: "Đang nhận video từ máy khách.",
  interrupted: "Mất video từ máy khách. Đang chờ nối lại.",
};

// A remote picture that stops advancing for this long is treated as lost, never as live.
const REMOTE_STALL_MS = 1500;

/**
 * The video source for recognition: the device webcam, or, when `remoteStream` is given (a counter display is
 * connected), the customer laptop's camera. `null` means the counter is connected but its video has not arrived.
 */
export function useCamera(
  videoRef: RefObject<HTMLVideoElement | null>,
  remoteStream?: MediaStream | null,
): CameraController {
  const remote = remoteStream !== undefined;
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
    // The counter's camera is turned off on the counter, not here.
    if (remote) return;
    requestIdRef.current += 1;
    requestingRef.current = false;
    stopStream();
    if (mountedRef.current) setStatus("off");
  }, [remote, stopStream]);

  const enable = useCallback(async () => {
    if (remote || requestingRef.current || streamRef.current) return;
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
  }, [remote, stopStream, videoRef]);

  // Remote mode: the local webcam is released, and the status follows the remote picture frame by frame.
  useEffect(() => {
    if (!remote) return;
    requestIdRef.current += 1;
    requestingRef.current = false;
    stopStream();
    const video = videoRef.current;
    const track = remoteStream?.getVideoTracks()[0];
    if (!video || !remoteStream || !track) { setStatus("off"); return; }
    video.srcObject = remoteStream;
    void video.play().catch(() => undefined);
    setStatus("requesting");
    let lastTime = -1, lastAdvance = 0;
    const check = () => {
      const now = performance.now();
      if (video.currentTime !== lastTime) { lastTime = video.currentTime; lastAdvance = lastTime > 0 ? now : 0; }
      const live = track.readyState === "live" && !track.muted && lastAdvance > 0 && now - lastAdvance < REMOTE_STALL_MS;
      setStatus(live ? "ready" : lastAdvance ? "interrupted" : "requesting");
    };
    const timer = window.setInterval(check, 250);
    track.addEventListener("mute", check);
    track.addEventListener("unmute", check);
    track.addEventListener("ended", check);
    return () => {
      window.clearInterval(timer);
      track.removeEventListener("mute", check);
      track.removeEventListener("unmute", check);
      track.removeEventListener("ended", check);
      if (video.srcObject === remoteStream) video.srcObject = null;
      if (mountedRef.current) setStatus("off");
    };
  }, [remote, remoteStream, stopStream, videoRef]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestIdRef.current += 1;
      requestingRef.current = false;
      stopStream();
    };
  }, [stopStream]);

  return { status, message: (remote ? remoteMessages[status] : undefined) ?? cameraMessages[status], enable, disable };
}
