import type { PredictionMessage } from "@contracts";
import type { InferencePhase } from "../state/inferenceMachine";

interface ResultPanelProps {
  phase: InferencePhase;
  prediction: PredictionMessage | null;
  guidance: string | null;
  onAdd: () => void;
  canUseLabels: boolean;
  eyebrow?: string;
  collectionReview?: boolean;
  automaticCapture?: boolean;
}

const phaseText: Record<InferencePhase, string> = {
  ready: "Sẵn sàng. Giữ nút hoặc phím Space trong khi thực hiện một ký hiệu.",
  capturing: "Đang thu ký hiệu. Thả nút khi bạn thực hiện xong.",
  processing: "Đang nhận dạng 16 khung hình…",
  ok: "Đã có dự đoán. Hãy xác nhận trước khi thêm vào câu.",
  uncertain: "Chưa nhận ra rõ. Hãy thử lại chậm hơn và giữ tay trong khung.",
  no_hands: "Chưa thấy đủ tay. Hãy đưa hai tay vào vùng hướng dẫn.",
  bad_framing: "Khung hình chưa phù hợp. Hãy giữ đầu, vai và tay trong vùng hướng dẫn.",
  busy: "Máy chủ đang bận. Vui lòng thử lại sau giây lát.",
  error: "Không thể nhận dạng lần này. Vui lòng thử lại.",
  disconnected: "Mất kết nối tới máy chủ nhận dạng. Ứng dụng đang thử kết nối lại.",
};

function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function ResultPanel({
  phase,
  prediction,
  guidance,
  onAdd,
  canUseLabels,
  eyebrow = "Bước 2",
  collectionReview = false,
  automaticCapture = false,
}: ResultPanelProps) {
  const canAdd =
    canUseLabels &&
    phase === "ok" &&
    prediction?.status === "ok" &&
    Boolean(prediction.label);
  const phaseMessage =
    automaticCapture && phase === "ready"
      ? "Tự động đang chờ chuyển động tay + khung xương. Thực hiện trọn vẹn một ký hiệu rồi giữ yên một nhịp."
      : automaticCapture && phase === "capturing"
        ? "Đã phát hiện chuyển động. Hãy hoàn thành ký hiệu; VSign sẽ tự kết thúc lượt thu."
        : phaseText[phase];
  return (
    <section className="panel result-panel" aria-labelledby="result-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h2 id="result-title">Kết quả nhận dạng</h2>
        </div>
        <span className={`recognition-state state-${phase}`}>{phase === "ok" ? "Đã nhận dạng" : "Chờ xác nhận"}</span>
      </div>

      <div className="result-live" aria-live="polite" aria-atomic="true">
        <p className="phase-message">{guidance ?? phaseMessage}</p>
        {prediction?.label ? (
          <div className="primary-prediction">
            <span className="result-label">{prediction.label}</span>
            <span className="confidence">
              Độ tin cậy <strong>{prediction.confidence === null ? "—" : percent(prediction.confidence)}</strong>
            </span>
          </div>
        ) : (
          <div className="empty-result">
            <span aria-hidden="true">VSL</span>
            <p>Từ dự đoán sẽ xuất hiện tại đây</p>
          </div>
        )}
      </div>

      <div className="top-three">
        <h3>Top 3 gợi ý</h3>
        {prediction?.top_k.length ? (
          <ol>
            {prediction.top_k.map((candidate) => (
              <li key={candidate.label}>
                <span>{candidate.label}</span>
                <strong>{percent(candidate.confidence)}</strong>
              </li>
            ))}
          </ol>
        ) : (
          <p className="muted">Chưa có gợi ý.</p>
        )}
      </div>

      {collectionReview ? (
        <p className="confirmation-note collection-review-note">
          Dự đoán chỉ dùng để đối chiếu. Nhãn bạn chọn ở bước 1 mới là nhãn dùng để cải thiện AI.
        </p>
      ) : (
        <>
          <button type="button" className="add-button" onClick={onAdd} disabled={!canAdd}>
            Thêm vào câu
          </button>
          <p className="confirmation-note">
            {canUseLabels
              ? "VSign không tự thêm từ. Bạn luôn là người xác nhận kết quả."
              : "Chỉ bật ghép câu khi checkpoint và label map cùng phiên bản đã được xác minh."}
          </p>
        </>
      )}
    </section>
  );
}
