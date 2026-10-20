import { Info, RefreshCw, Server } from "../icons";
import { emptyRuntime, type RuntimeSnapshot } from "../hooks/useRuntimeStatus";

function RuntimeTime({ value }: { value: number | null }) {
  return value === null ? <>Chưa kiểm tra</> : <time dateTime={new Date(value).toISOString()}>{new Date(value).toLocaleString("vi-VN")}</time>;
}

export function RuntimeRefreshButton({ checking, onRefresh }: { checking: boolean; onRefresh: () => void }) {
  return <button type="button" className="runtime-refresh page-icon-button" aria-label="Làm mới trạng thái dịch vụ"
    title="Làm mới trạng thái dịch vụ" disabled={checking} data-busy={checking || undefined} onClick={onRefresh}>
    <RefreshCw size={18} aria-hidden="true" />
  </button>;
}

export function WorkspaceRuntime({ runtime = emptyRuntime(""), monitoring = false, onRefresh, systemAdmin = false }: {
  runtime?: RuntimeSnapshot;
  monitoring?: boolean;
  onRefresh?: () => void;
  systemAdmin?: boolean;
}) {
  const { health } = runtime;
  const offline = !!runtime.healthError;
  const cachedMetadata = runtime.metadata;
  const metadataMatchesHealth = offline || !health || (cachedMetadata?.backend === health.backend &&
    cachedMetadata.model_version === health.model_version && cachedMetadata.protocol_version === health.protocol_version);
  const metadata = metadataMatchesHealth ? cachedMetadata : null;
  const stale = !!cachedMetadata && (offline || !!runtime.metadataError || !metadataMatchesHealth);
  const state = offline ? "offline" : !health ? "pending" : metadata?.mock ? "mock" : "online";
  const stateText = { offline: "Dịch vụ ngoại tuyến", pending: runtime.checking ? "Đang kiểm tra dịch vụ" : "Chưa kiểm tra dịch vụ",
    mock: "Dịch vụ mô phỏng", online: "Dịch vụ đang hoạt động" }[state];
  // Only a matching metadata response establishes the model's labels and capabilities.
  const identity = !offline && health ? health : metadata;
  return <>
    <div className="runtime-toolbar">
      <span>Kiểm tra gần nhất: <RuntimeTime value={runtime.checkedAt} /></span>
      {onRefresh && <RuntimeRefreshButton checking={runtime.checking} onRefresh={onRefresh} />}
    </div>
    <section className="workspace-overview" aria-label="Trạng thái dịch vụ">
      <div className="workspace-metric workspace-metric-status" data-runtime-state={state}>
        <span className="workspace-metric-label">Dịch vụ nhận dạng</span>
        <strong><i aria-hidden="true" />{stateText}</strong>
        {runtime.checking && runtime.checkedAt !== null && <span className="workspace-metric-detail">Đang cập nhật</span>}
      </div>
      <div className="workspace-metric">
        <span className="workspace-metric-label">{stale && offline ? "Phiên bản lần đọc trước" : "Phiên bản nhận dạng"}</span>
        <strong>{identity?.model_version ?? "Chưa có thông tin phiên bản"}</strong>
      </div>
      <div className="workspace-metric">
        <span className="workspace-metric-label">{stale && metadata ? "Ký hiệu lần đọc trước" : "Ký hiệu hỗ trợ"}</span>
        <strong>{metadata ? `${metadata.labels.length} ký hiệu` : "Chưa có thông tin ký hiệu"}</strong>
        <span className="workspace-metric-detail">{metadata ? metadata.candidate_labels_unverified ? "Chưa xác minh" : "Đã xác minh" : "Chưa nhận được thông tin"}</span>
      </div>
      <div className="workspace-metric">
        <span className="workspace-metric-label">{stale && metadata ? "Thu dữ liệu lần đọc trước" : "Thu dữ liệu"}</span>
        <strong>{metadata ? metadata.collection_enabled ? "Đã bật" : "Chưa bật" : "Chưa có thông tin"}</strong>
        <span className="workspace-metric-detail">{metadata ? metadata.collection_enabled ? `${metadata.collection_target_per_hand} mẫu / tay` : "Không ghi dữ liệu" : "Chưa nhận được thông tin"}</span>
      </div>
    </section>
    {(runtime.healthError || runtime.metadataError) && <p className="runtime-warning" role="status">
      {runtime.healthError && <span>Không thể kết nối dịch vụ nhận dạng.</span>}
      {runtime.metadataError && <span>Chưa tải được thông tin nhận dạng.</span>}
      {stale && <span>Dữ liệu lần đọc trước: <RuntimeTime value={runtime.metadataUpdatedAt} />.</span>}
    </p>}
    {monitoring && <>
      <section className="runtime-section" aria-labelledby="runtime-metrics-title">
        <h2 id="runtime-metrics-title"><Server size={18} aria-hidden="true" />Chất lượng dịch vụ</h2>
        <dl className="workspace-detail-list runtime-metrics">
          <div><dt>Độ trễ kiểm tra kết nối</dt><dd>{runtime.healthLatencyMs === null ? "Chưa đo được" : `${runtime.healthLatencyMs.toFixed(1)} ms`}</dd></div>
          <div><dt>Độ trễ nhận dạng</dt><dd>Chưa có dữ liệu</dd></div>
          <div><dt>Tỷ lệ lỗi nhận dạng</dt><dd>Chưa có dữ liệu</dd></div>
        </dl>
      </section>
      <section className="runtime-section" aria-labelledby="runtime-source-title">
        <h2 id="runtime-source-title"><Info size={18} aria-hidden="true" />Thông tin dịch vụ</h2>
        <dl className="workspace-detail-list runtime-sources">
          <div><dt>Kết nối thành công gần nhất</dt><dd><RuntimeTime value={runtime.lastHealthyAt} /></dd></div>
          {systemAdmin && <>
            <div><dt>Endpoint đang quan sát</dt><dd>{runtime.endpoint || "Chưa cấu hình"}</dd></div>
            <div><dt>Backend</dt><dd>{identity?.backend ?? "Chưa xác nhận"}</dd></div>
            <div><dt>Protocol</dt><dd>{identity?.protocol_version ?? "Chưa xác nhận"}</dd></div>
            <div><dt>Ngưỡng confidence</dt><dd>{metadata?.confidence_threshold ?? "Chưa xác nhận"}</dd></div>
            <div><dt>Ngưỡng margin</dt><dd>{metadata?.margin_threshold ?? "Chưa xác nhận"}</dd></div>
          </>}
        </dl>
        {metadata && <details className="runtime-labels"><summary>Ký hiệu hỗ trợ ({metadata.labels.length})</summary>
          <ul>{metadata.labels.map((label, index) => <li key={`${index}:${label}`}>{label}</li>)}</ul>
        </details>}
      </section>
    </>}
  </>;
}
