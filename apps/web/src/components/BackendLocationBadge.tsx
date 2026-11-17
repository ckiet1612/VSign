import { useId } from "react";

interface Props {
  location: "modal" | "aws" | "mac" | "windows" | "browser" | null;
  connecting?: boolean;
  floating?: boolean;
  requiresLogin?: boolean;
  gpuName?: string | null;
  modalControl?: {
    enabled: boolean | null;
    busy?: boolean;
    error?: string | null;
    onChange: (enabled: boolean) => void;
  };
}

export function BackendLocationBadge({ location, connecting = false, floating = false, requiresLogin = false, gpuName, modalControl }: Props) {
  const errorId = useId();
  const device = gpuName?.replace(/^(?:NVIDIA|Tesla)\s+/i, "");
  const label = requiresLogin ? "Chưa đăng nhập" : location === "modal" ? `Modal ${device || "GPU"}`
    : location === "aws" ? `AWS ${device || "GPU"}` : location === "mac" ? "Mac"
    : location === "windows" ? "Windows"
    : location === "browser" ? "Trình duyệt" : connecting ? "Đang kết nối" : "Chưa kết nối";

  return <>
    {modalControl && <div className="modal-gpu-control">
      <button type="button" role="switch" aria-checked={modalControl.enabled === true}
        aria-label="GPU Modal" aria-busy={modalControl.busy || (modalControl.enabled === null && !modalControl.error) || undefined}
        aria-describedby={modalControl.error ? errorId : undefined}
        disabled={modalControl.enabled === null || modalControl.busy}
        title={modalControl.enabled === null ? "Đang đọc trạng thái GPU Modal" : "Cho phép VSign dùng GPU Modal"}
        className="modal-gpu-switch" data-unknown={modalControl.enabled === null || undefined}
        onClick={() => modalControl.onChange(!modalControl.enabled)}>
        GPU Modal<span className="modal-gpu-switch-track" aria-hidden="true" />
      </button>
      {modalControl.error && <span id={errorId} className="modal-gpu-error" role="alert">{modalControl.error}</span>}
    </div>}
    <div className={`backend-location${floating ? " backend-location-floating" : ""}`}
      role="status" aria-live="polite" aria-atomic="true"
      title={requiresLogin ? "Đăng nhập để kết nối nhận dạng" : "Nơi xử lý nhận dạng"}>
      <span className={`backend-location-dot${location ? " is-connected" : ""}`} aria-hidden="true" />
      <span className="backend-location-caption">Backend:</span>
      <strong>{label}</strong>
    </div>
  </>;
}
