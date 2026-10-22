interface Props {
  location: "modal" | "mac" | "browser" | null;
  connecting?: boolean;
  floating?: boolean;
  requiresLogin?: boolean;
  gpuName?: string | null;
}

export function BackendLocationBadge({ location, connecting = false, floating = false, requiresLogin = false, gpuName }: Props) {
  const device = gpuName?.replace(/^(?:NVIDIA|Tesla)\s+/i, "");
  const label = requiresLogin ? "Chưa đăng nhập" : location === "modal" ? `Modal ${device || "GPU"}` : location === "mac" ? "Mac"
    : location === "browser" ? "Trình duyệt" : connecting ? "Đang kết nối" : "Chưa kết nối";

  return (
    <div className={`backend-location${floating ? " backend-location-floating" : ""}`}
      role="status" aria-live="polite" aria-atomic="true"
      title={requiresLogin ? "Đăng nhập để kết nối nhận dạng" : "Nơi xử lý nhận dạng"}>
      <span className={`backend-location-dot${location ? " is-connected" : ""}`} aria-hidden="true" />
      <span className="backend-location-caption">Backend:</span>
      <strong>{label}</strong>
    </div>
  );
}
