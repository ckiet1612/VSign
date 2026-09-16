import type { PointerEvent as ReactPointerEvent, RefObject } from "react";
import type { CameraController } from "../hooks/useCamera";
import type { CaptureStatus } from "../hooks/useSignCapture";
import type { ConnectionStatus } from "../hooks/useInferenceSocket";
import type { AutomaticCapturePhase } from "../lib/autoSegmentation";
import type { AutomaticCollectionPhase } from "../hooks/useAutomaticCollectionCycle";
import {
  HandTrackingOverlay,
  type HandTrackingFrame,
} from "./HandTrackingOverlay";

export type CaptureInputMode = "manual" | "automatic";

interface CameraPanelProps {
  videoRef: RefObject<HTMLVideoElement | null>;
  camera: CameraController;
  connection: ConnectionStatus;
  captureStatus: CaptureStatus;
  canCapture: boolean;
  purpose: "recognize" | "collect";
  captureInputMode: CaptureInputMode;
  automaticPhase: AutomaticCapturePhase;
  automaticAvailable: boolean;
  automaticCollectionPhase: AutomaticCollectionPhase;
  automaticCollectionCountdown: number | null;
  onCaptureInputModeChange: (mode: CaptureInputMode) => void;
  onTrackingFrame: (frame: HandTrackingFrame) => void;
  onPointerDown: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onPointerUp: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onPointerCancel: (event: ReactPointerEvent<HTMLButtonElement>) => void;
}

const connectionText: Record<ConnectionStatus, string> = {
  connecting: "Đang kết nối",
  connected: "Đã kết nối",
  disconnected: "Mất kết nối",
};

export function CameraPanel({
  videoRef,
  camera,
  connection,
  captureStatus,
  canCapture,
  purpose,
  captureInputMode,
  automaticPhase,
  automaticAvailable,
  automaticCollectionPhase,
  automaticCollectionCountdown,
  onCaptureInputModeChange,
  onTrackingFrame,
  onPointerDown,
  onPointerUp,
  onPointerCancel,
}: CameraPanelProps) {
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
            : "Bật camera để bắt đầu phiên tự động"
    : automaticPhase === "capturing" || automaticPhase === "postroll"
      ? "Đang thu ký hiệu…"
      : automaticPhase === "cooldown"
        ? "Đã nhận chuyển động · chờ ký hiệu tiếp theo"
        : automaticPhase === "waiting"
          ? "Sẵn sàng · hãy thực hiện một ký hiệu"
          : "Bật camera để bắt đầu tự động";

  return (
    <section className="panel camera-panel" aria-labelledby="camera-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">{purpose === "collect" ? "Bước 2" : "Bước 1"}</p>
          <h2 id="camera-title">
            {purpose === "collect" ? "Quay một mẫu mới" : "Thực hiện một ký hiệu"}
          </h2>
        </div>
        <div className="status-row" aria-label="Trạng thái hệ thống">
          <span className={`status-chip camera-${camera.status}`}>
            Camera: {camera.status === "ready" ? "Sẵn sàng" : "Chưa sẵn sàng"}
          </span>
          <span className={`status-chip connection-${connection}`}>
            AI: {connectionText[connection]}
          </span>
        </div>
      </div>

      <div
        className={`camera-stage ${
          recording ? "is-recording" : ""
        } ${camera.status === "ready" ? "camera-ready-stage" : ""}`}
      >
        <video ref={videoRef} autoPlay muted playsInline aria-label="Hình ảnh camera trực tiếp" />
        {camera.status !== "ready" && (
          <div className="camera-placeholder">
            <span className="camera-icon" aria-hidden="true">◉</span>
            <strong>Bật camera để bắt đầu</strong>
            <span>Đứng chính diện, giữ đầu, vai và hai tay trong khung.</span>
          </div>
        )}
        <div className="body-guide" aria-hidden="true">
          <svg
            className="body-guide-svg"
            viewBox="0 0 960 540"
            preserveAspectRatio="xMidYMid meet"
          >
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
            <i /> Căn giữa thân trên · Giữ hai tay trong khung
          </span>
        </div>
        <HandTrackingOverlay
          videoRef={videoRef}
          active={camera.status === "ready"}
          onTrackingFrame={onTrackingFrame}
        />
        {recording && (
          <div className="recording-badge">
            <span aria-hidden="true" />
            {automaticActive ? "Tự động đang thu" : "Đang thu"}
          </div>
        )}
      </div>

      <p className="camera-message" aria-live="polite">{camera.message}</p>

      <div className="mode-switch" aria-label="Chế độ thu ký hiệu">
        <button
          type="button"
          className={`mode ${!automaticActive ? "active" : ""}`}
          aria-pressed={!automaticActive}
          disabled={captureStatus !== "idle"}
          onClick={() => onCaptureInputModeChange("manual")}
        >
          {purpose === "collect" ? "Giữ để quay mẫu" : "Giữ để ký"}
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
              ? purpose === "collect"
                ? "Đếm ngược, quay và tự lưu từng lượt; chuyển về thủ công để dừng"
                : "Tự phát hiện đầu và cuối bằng chuyển động tay + khung xương"
              : "AI local cần tải xong trước khi bật tự động"
          }
          onClick={() => onCaptureInputModeChange("automatic")}
        >
          Tự động <span>beta</span>
        </button>
      </div>

      <div className="camera-actions">
        {camera.status === "ready" ? (
          <button type="button" className="secondary-button" onClick={camera.disable}>
            Tắt camera
          </button>
        ) : (
          <button
            type="button"
            className="secondary-button"
            onClick={() => void camera.enable()}
            disabled={camera.status === "requesting"}
          >
            {camera.status === "requesting" ? "Đang bật…" : "Bật camera"}
          </button>
        )}
        {automaticActive ? (
          <div
            className={`automatic-action automatic-${
              purpose === "collect" ? automaticCollectionPhase : automaticPhase
            }`}
            role="status"
            aria-live="polite"
          >
            <span className="automatic-dot" aria-hidden="true" />
            <div>
              <strong>{automaticText}</strong>
              <small>
                {purpose === "collect"
                  ? "Mỗi lượt quay 2,1 giây; chỉ ký một lần khi bắt đầu ghi."
                  : "Hoàn thành động tác rồi giữ tay yên một nhịp."}
              </small>
            </div>
          </div>
        ) : (
          <button
            type="button"
            className={`hold-button ${captureStatus === "capturing" ? "active" : ""}`}
            disabled={!canCapture && captureStatus === "idle"}
            onPointerDown={onPointerDown}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerCancel}
            onContextMenu={(event) => event.preventDefault()}
            aria-label={
              purpose === "collect"
                ? "Giữ để quay mẫu, cũng có thể giữ phím Space"
                : "Giữ để ký, cũng có thể giữ phím Space"
            }
          >
            <span className="hold-dot" aria-hidden="true" />
            {captureLabel}
            <kbd>Space</kbd>
          </button>
        )}
      </div>

      <p className="privacy-note">
        <span aria-hidden="true">⌁</span>
        {purpose === "collect"
          ? automaticActive
            ? "Phiên tự động lưu local sau khi kiểm tra đủ hình tay. Chuyển về “Giữ để quay mẫu” để dừng."
            : "Mẫu chỉ được lưu local sau khi bạn bấm “Lưu mẫu vào máy”. Bỏ mẫu sẽ không tạo tệp."
          : automaticActive
            ? "Tự động chỉ giữ tạm điểm tracking trong bộ nhớ. Kết quả vẫn cần bạn xác nhận trước khi thêm vào câu."
            : "Điểm tracking được xử lý local. VSign không dùng MediaRecorder và không lưu video mặc định."}
      </p>
    </section>
  );
}
