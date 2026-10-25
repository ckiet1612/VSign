import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  type RefObject,
  type SyntheticEvent,
} from "react";
import { Camera, CameraOff, Hand, Pause, Play, Sparkles, Square } from "../icons";
import type { CameraController, CameraStatus } from "../hooks/useCamera";
import type { CaptureStatus } from "../hooks/useSignCapture";
import type { ConnectionStatus } from "../hooks/useInferenceSocket";
import type { AutomaticCapturePhase } from "../lib/autoSegmentation";
import type { AutomaticCollectionPhase } from "../hooks/useAutomaticCollectionCycle";
import type { CaptureFramingMode } from "../lib/inferenceRoute";
import { centeredSquareRect, containedVideoRect } from "../lib/cameraGeometry";
import { MAX_WAITING_CAPTURES, type AutomaticInferenceTiming } from "../lib/automaticInferenceQueue";
import {
  HandTrackingOverlay,
  type HandTrackingFrame,
} from "./HandTrackingOverlay";

export type CaptureInputMode = "manual" | "automatic";

interface CameraPanelProps {
  videoRef: RefObject<HTMLVideoElement | null>;
  camera: CameraController;
  connection: ConnectionStatus;
  /** Where recognition runs when a GPU runtime is configured ("GPU" or "Mac"). */
  runtimeLabel?: string;
  captureStatus: CaptureStatus;
  canCapture: boolean;
  purpose: "recognize" | "collect";
  framingMode: CaptureFramingMode;
  captureInputMode: CaptureInputMode;
  automaticPhase: AutomaticCapturePhase;
  automaticAvailable: boolean;
  automaticCollectionPhase: AutomaticCollectionPhase;
  automaticCollectionCountdown: number | null;
  collectionControls?: {
    state: "idle" | "running" | "paused";
    ready: boolean;
    completed: boolean;
    onStart: () => void;
    onPause: () => void;
    onStop: () => void;
  };
  automaticQueue?: {
    waitingCount: number;
    busy: boolean;
    full: boolean;
    lastTiming: AutomaticInferenceTiming | null;
    notice: string;
  };
  onCaptureInputModeChange: (mode: CaptureInputMode) => void;
  onTrackingFrame: (frame: HandTrackingFrame) => void;
  onPointerDown: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onPointerUp: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onPointerCancel: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  /** The picture comes from a counter display's camera; it is switched on there, not here. */
  remote?: { name: string };
}

const connectionText: Record<ConnectionStatus, string> = {
  connecting: "Đang kết nối",
  connected: "Đã kết nối",
  disconnected: "Mất kết nối",
};

const cameraStatusText: Record<CameraStatus, string> = {
  off: "Chưa bật",
  requesting: "Đang bật",
  ready: "Trực tiếp",
  denied: "Chưa có quyền",
  unavailable: "Không khả dụng",
  busy: "Camera đang bận",
  interrupted: "Đã ngắt",
  error: "Lỗi camera",
};

const GUIDE_WIDTH = 960;
const GUIDE_HEIGHT = 540;

export function CameraPanel({
  videoRef,
  camera,
  connection,
  runtimeLabel,
  captureStatus,
  canCapture,
  purpose,
  framingMode,
  captureInputMode,
  automaticPhase,
  automaticAvailable,
  automaticCollectionPhase,
  automaticCollectionCountdown,
  collectionControls,
  automaticQueue,
  onCaptureInputModeChange,
  onTrackingFrame,
  onPointerDown,
  onPointerUp,
  onPointerCancel,
  remote,
}: CameraPanelProps) {
  const startCameraButtonRef = useRef<HTMLButtonElement>(null);
  const ready = camera.status === "ready";
  // While the card fades out it keeps the text it had, instead of flashing "Camera chưa sẵn sàng".
  const lastIdleStatus = useRef<CameraStatus>("off");
  if (!ready) lastIdleStatus.current = camera.status;
  const onboardingStatus = lastIdleStatus.current;
  const returnFocusAfterStop = useRef(false);
  useEffect(() => {
    if (camera.status === "off" && returnFocusAfterStop.current) {
      startCameraButtonRef.current?.focus();
      returnFocusAfterStop.current = false;
    }
  }, [camera.status]);
  // The white thumb slides to the active option; options differ in width ("Tự động" carries a beta tag), so it is measured.
  const modeSwitchRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const host = modeSwitchRef.current;
    if (!host) return;
    const place = () => {
      const active = host.querySelector<HTMLElement>(".mode.active");
      if (!active) return;
      host.style.setProperty("--thumb-x", `${active.offsetLeft}px`);
      host.style.setProperty("--thumb-w", `${active.offsetWidth}px`);
    };
    place();
    // Placed once without motion; later moves glide.
    const frame = window.requestAnimationFrame(() => host.setAttribute("data-thumb-ready", ""));
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(place);
    observer?.observe(host);
    return () => { window.cancelAnimationFrame(frame); observer?.disconnect(); };
    // `purpose`: coming back from collecting mounts a new switch even when the mode did not change; it needs placing too.
  }, [captureInputMode, purpose]);
  const [videoDimensions, setVideoDimensions] = useState({
    width: GUIDE_WIDTH,
    height: GUIDE_HEIGHT,
  });
  const updateVideoDimensions = (event: SyntheticEvent<HTMLVideoElement>) => {
    const video = event.currentTarget;
    if (!video.videoWidth || !video.videoHeight) return;
    setVideoDimensions((current) =>
      current.width === video.videoWidth && current.height === video.videoHeight
        ? current
        : { width: video.videoWidth, height: video.videoHeight },
    );
  };
  const fixedGuide = centeredSquareRect(
    containedVideoRect(
      GUIDE_WIDTH,
      GUIDE_HEIGHT,
      videoDimensions.width,
      videoDimensions.height,
    ),
  );
  const cornerLength = Math.min(34, fixedGuide.width / 8);
  const { x, y, width, height } = fixedGuide;
  const cropCorners = `M${x} ${y + cornerLength} V${y} H${x + cornerLength}
    M${x + width - cornerLength} ${y} H${x + width} V${y + cornerLength}
    M${x + width} ${y + height - cornerLength} V${y + height} H${x + width - cornerLength}
    M${x + cornerLength} ${y + height} H${x} V${y + height - cornerLength}`;
  const automaticActive = captureInputMode === "automatic";
  const recording =
    captureStatus === "capturing" ||
    (automaticActive &&
      (automaticPhase === "capturing" || automaticPhase === "postroll"));
  const captureLabel =
    captureStatus === "capturing"
      ? purpose === "collect" ? "Thả để kết thúc mẫu" : "Thả để nhận dạng"
      : captureStatus === "encoding"
        ? "Đang chuẩn bị 16 khung hình…"
        : purpose === "collect"
          ? "Giữ để quay mẫu"
          : "Giữ để ký";
  const automaticText = purpose === "collect"
    ? automaticCollectionPhase === "preparing"
      ? `Chuẩn bị ký sau ${automaticCollectionCountdown ?? 1}…`
      : automaticCollectionPhase === "recording"
        ? "Đang quay một lượt…"
        : automaticCollectionPhase === "processing"
          ? "Đang kiểm tra và lưu mẫu…"
          : automaticCollectionPhase === "waiting"
            ? "Sẵn sàng cho lượt tự động tiếp theo"
            : collectionControls?.completed
              ? "Đã đủ mẫu"
              : collectionControls?.state === "paused"
                ? "Phiên đã tạm dừng"
                : "Sẵn sàng thu mẫu"
    : automaticQueue?.full
      ? "Hàng đợi đầy · chờ AI xử lý"
      : automaticPhase === "encoding"
      ? "Đang xử lý ảnh ký hiệu…"
      : automaticPhase === "capturing" || automaticPhase === "postroll"
      ? "Đang thu ký hiệu…"
      : automaticPhase === "cooldown" || automaticPhase === "rearming"
        ? "Chờ tay nghỉ · chưa nhận lượt mới"
        : automaticPhase === "waiting"
          ? "Sẵn sàng · hãy ký một từ"
          : "Bật camera để bắt đầu tự động";

  const stopCamera = () => {
    returnFocusAfterStop.current = true;
    camera.disable();
  };
  const automaticStatus = (detail?: ReactNode) => (
    <div
      className={`automatic-action automatic-${
        purpose === "collect" ? automaticCollectionPhase
          : automaticQueue?.full ? "full" : automaticPhase
      }`}
      role="status"
      aria-live="polite"
    >
      <span className="automatic-dot" aria-hidden="true" />
      <div>
        <strong title={automaticText}>{automaticText}</strong>
        {detail}
      </div>
    </div>
  );
  const holdButton = (
    <button
      type="button"
      className={`hold-button ${captureStatus === "capturing" ? "active" : ""}`}
      disabled={!canCapture && captureStatus === "idle"}
      onPointerDown={onPointerDown}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerCancel}
      onContextMenu={(event) => event.preventDefault()}
      aria-label="Giữ để ký, cũng có thể giữ phím Space"
    >
      <span className="hold-dot" aria-hidden="true" />
      {captureLabel}
      {purpose === "recognize" && captureStatus === "idle" && <kbd aria-hidden="true">Space</kbd>}
    </button>
  );

  return (
    <section className={`panel camera-panel ${ready ? "is-ready" : "is-idle"}`} aria-labelledby="camera-title">
      <div className="camera-heading">
        <h2 id="camera-title">Camera{remote && <span className="camera-heading-source"> · {remote.name}</span>}</h2>
        <div className="camera-status-group" aria-label="Trạng thái hệ thống">
          <span className={`camera-state camera-state-${camera.status}`} role="status">
            <i aria-hidden="true" />{cameraStatusText[camera.status]}
          </span>
          <span className={`camera-state status-chip connection-${connection}`}>
            <i aria-hidden="true" />AI: {connectionText[connection]}{connection === "connected" && runtimeLabel ? ` · ${runtimeLabel}` : ""}
          </span>
        </div>
      </div>

      <div
        className={`camera-stage ${
          recording ? "is-recording" : ""
        } ${ready ? "camera-ready-stage" : ""} ${remote && !ready ? "remote-unavailable" : ""} framing-${framingMode}`}
      >
        <video
          ref={videoRef}
          autoPlay
          muted
          playsInline
          aria-label={remote ? `Hình ảnh camera trực tiếp từ ${remote.name}` : "Hình ảnh camera trực tiếp"}
          onLoadedMetadata={updateVideoDimensions}
          onResize={updateVideoDimensions}
        />
        <div className="body-guide" aria-hidden="true">
          <svg
            className="body-guide-svg"
            viewBox="0 0 960 540"
            preserveAspectRatio="xMidYMid meet"
          >
            {framingMode === "fixed" && (<>
              <rect
                className="guide-rgb-crop"
                x={fixedGuide.x}
                y={fixedGuide.y}
                width={fixedGuide.width}
                height={fixedGuide.height}
              />
              <path className="guide-rgb-corners" d={cropCorners} />
            </>)}
            <rect className="guide-safe-area" x="34" y="36" width="892" height="454" rx="28" />
            <path
              className="guide-reach"
              d="M72 308 C178 258 278 244 360 250 M888 308 C782 258 682 244 600 250"
            />
            <ellipse className="guide-head" cx="480" cy="123" rx="54" ry="67" />
            <path
              className="guide-body"
              d="M449 185 L446 204 C392 213 337 228 301 262 C258 303 247 378 242 466 M511 185 L514 204 C568 213 623 228 659 262 C702 303 713 378 718 466 M354 235 C340 312 339 391 336 470 M606 235 C620 312 621 391 624 470 M336 470 L624 470"
            />
            <path className="guide-chest" d="M392 217 C423 240 537 240 568 217" />
            <path
              className="guide-corners"
              d="M34 116 V64 Q34 36 62 36 H122 M838 36 H898 Q926 36 926 64 V116 M926 410 V462 Q926 490 898 490 H838 M122 490 H62 Q34 490 34 462 V410"
            />
          </svg>
          <span className="body-guide-label">
            <i /> {framingMode === "fixed"
              ? purpose === "collect"
                ? "Khung RGB cố định · Giữ tay thực hiện bên trong"
                : "Khung RGB cố định · Giữ hai tay bên trong"
              : "Căn giữa thân trên · Giữ hai tay trong khung"}
          </span>
        </div>
        <HandTrackingOverlay
          videoRef={videoRef}
          active={ready}
          framingMode={framingMode}
          onTrackingFrame={onTrackingFrame}
        />
        {/* Stays mounted so turning the camera on or off fades the card instead of cutting it. */}
        <div
          className={`camera-onboarding${ready ? " is-hidden" : ""}`}
          aria-hidden={ready || undefined}
          inert={ready}
        >
          <span className="camera-onboarding-icon" aria-hidden="true">
            {onboardingStatus === "off" || onboardingStatus === "requesting" ? <Camera size={22} /> : <CameraOff size={22} />}
          </span>
          <strong>
            {remote
              ? onboardingStatus === "interrupted" ? `Mất video từ ${remote.name}` : `Đang chờ video từ ${remote.name}`
              : onboardingStatus === "off" || onboardingStatus === "requesting"
              ? "Bật camera để bắt đầu"
              : onboardingStatus === "denied" ? "Cần quyền truy cập camera" : "Camera chưa sẵn sàng"}
          </strong>
          {(remote || onboardingStatus !== "off") && !ready && camera.message && (
            <p className="camera-message" aria-live="polite">{camera.message}</p>
          )}
          {!remote && <button ref={startCameraButtonRef} type="button" className="camera-start-button"
            onClick={() => void camera.enable()} disabled={camera.status === "requesting"}>
            {camera.status === "requesting" ? "Đang bật…" : "Bật camera"}
          </button>}
        </div>
        {recording && (
          <div className="recording-badge">
            <span aria-hidden="true" />
            {automaticActive ? "Tự động đang thu" : "Đang thu"}
          </div>
        )}
      </div>

      {purpose === "recognize" ? (
        // Keyed per purpose: reusing the collect toolbar's black "Bắt đầu thu" button as "Thủ công" made it fade from black.
        // One fixed row: mode, the capture action, stop. The action and stop slots keep their place while the camera
        // is off (hidden), so turning it on fades them in where they belong instead of dropping a new row.
        <div key="recognize" className={`camera-toolbar purpose-recognize${ready ? " is-live" : ""}`} role="group" aria-label="Điều khiển camera">
          <div ref={modeSwitchRef} className="mode-switch capture-mode-switch" role="group" aria-label="Chế độ thu ký hiệu">
            <button
              type="button"
              className={`mode ${!automaticActive ? "active" : ""}`}
              aria-pressed={!automaticActive}
              disabled={captureStatus !== "idle"}
              onClick={() => onCaptureInputModeChange("manual")}
            >
              <Hand size={16} aria-hidden="true" />Thủ công
            </button>
            <button
              type="button"
              className={`mode ${automaticActive ? "active" : ""}`}
              aria-pressed={automaticActive}
              disabled={
                !automaticAvailable ||
                captureStatus !== "idle"
              }
              title={
                automaticAvailable
                  ? "Tự phát hiện đầu và cuối bằng chuyển động tay + khung xương"
                  : "AI cần sẵn sàng trước khi bật tự động"
              }
              onClick={() => onCaptureInputModeChange("automatic")}
            >
              <Sparkles size={16} aria-hidden="true" />Tự động <span>beta</span>
            </button>
          </div>
          <div className="camera-action-slot" aria-hidden={!ready || undefined} inert={!ready}>
            {automaticActive ? automaticStatus(automaticQueue && (
              <span className="automatic-queue-counts" role="status" aria-live="polite">
                <span>Đang xử lý: {automaticQueue.busy ? 1 : 0}</span>
                <span>Chờ: {automaticQueue.waitingCount}/{MAX_WAITING_CAPTURES}</span>
                {automaticQueue.full && <strong>Thu tạm dừng</strong>}
              </span>
            )) : holdButton}
          </div>
          <button type="button" className="secondary-button camera-stop-button camera-stop-icon"
            aria-label="Tắt camera" title="Tắt camera" hidden={!!remote}
            aria-hidden={!ready || undefined} inert={!ready} onClick={stopCamera}>
            <CameraOff size={18} aria-hidden="true" />
          </button>
        </div>
      ) : (
        <div key="collect" className="camera-toolbar purpose-collect" role="group" aria-label="Điều khiển camera">
          {collectionControls && (
            <div className="collection-session-actions">
              {collectionControls.state === "running" ? (
                <button type="button" className="secondary-button" onClick={collectionControls.onPause}>
                  <Pause size={18} aria-hidden="true" />Tạm dừng
                </button>
              ) : (
                <button
                  type="button"
                  className="save-sample-button"
                  disabled={!collectionControls.ready || collectionControls.completed}
                  onClick={collectionControls.onStart}
                >
                  <Play size={18} aria-hidden="true" />
                  {collectionControls.completed ? "Đã đủ mẫu"
                    : collectionControls.state === "paused" ? "Tiếp tục" : "Bắt đầu thu"}
                </button>
              )}
              <button
                type="button"
                className="secondary-button"
                disabled={collectionControls.state === "idle"}
                onClick={collectionControls.onStop}
              >
                <Square size={16} aria-hidden="true" />Dừng phiên
              </button>
            </div>
          )}
          {ready && automaticStatus()}
          {ready && (
            <button type="button" className="secondary-button camera-stop-button" onClick={stopCamera}>
              <CameraOff size={18} aria-hidden="true" />Tắt camera
            </button>
          )}
        </div>
      )}

      {automaticActive && purpose === "recognize" && automaticQueue && (automaticQueue.lastTiming || automaticQueue.notice) && (
        <div className="automatic-queue-readout">
          {automaticQueue.lastTiming && (
            <details className="capture-diagnostics">
              <summary>Thời gian xử lý</summary>
              <dl className="capture-timings" aria-label={`Thời gian lượt ${automaticQueue.lastTiming.sequence + 1}`}>
                <div><dt>Đoạn thu</dt><dd>{Math.round(automaticQueue.lastTiming.captureMs)} ms</dd></div>
                <div><dt>Encode ảnh</dt><dd>{Math.round(automaticQueue.lastTiming.encodeMs)} ms</dd></div>
                <div><dt>Chờ gửi</dt><dd>{Math.round(automaticQueue.lastTiming.queueWaitMs)} ms</dd></div>
                <div title="Từ lúc gửi đến khi nhận kết quả, gồm truyền dữ liệu và xử lý máy chủ">
                  <dt>Phản hồi AI</dt><dd>{Math.round(automaticQueue.lastTiming.responseMs)} ms</dd>
                </div>
                {automaticQueue.lastTiming.resultWaitMs !== undefined && (
                  <div title="Model đã chạy từ lúc tay vừa dừng; đây là thời gian còn chờ sau khi lượt ký được xác nhận">
                    <dt>Chờ sau khi ký</dt><dd>{Math.round(automaticQueue.lastTiming.resultWaitMs)} ms</dd>
                  </div>
                )}
              </dl>
            </details>
          )}
          {automaticQueue.notice && <p className="capture-queue-notice" role="status">{automaticQueue.notice}</p>}
        </div>
      )}

    </section>
  );
}
