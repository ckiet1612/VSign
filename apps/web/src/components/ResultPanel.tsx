import type { PredictionMessage } from "@contracts";
import type { InferencePhase } from "../state/inferenceMachine";
import type { WordInsertionMode } from "../lib/autoTranscriptInsertion";
import { useDismissibleDetails } from "../hooks/useDismissibleDetails";
import { ArrowRight, CircleAlert, Info, ListOrdered, Settings2, TriangleAlert } from "../icons";

interface ResultPanelProps {
  phase: InferencePhase;
  prediction: PredictionMessage | null;
  guidance: string | null;
  onAdd: () => void;
  canUseLabels: boolean;
  eyebrow?: string;
  collectionReview?: boolean;
  automaticCapture?: boolean;
  wordInsertionMode: WordInsertionMode;
  onWordInsertionModeChange: (mode: WordInsertionMode) => void;
  automaticInsertionAvailable: boolean;
  automaticAdded: boolean;
  cameraReady?: boolean;
}

const phaseText: Record<InferencePhase, string | null> = {
  ready: null,
  capturing: null,
  processing: null,
  ok: null,
  uncertain: "Chưa nhận ra rõ. Hãy thử lại chậm hơn và giữ tay trong khung.",
  no_hands: "Chưa thấy đủ tay. Hãy đưa hai tay vào vùng hướng dẫn.",
  bad_framing: "Khung hình chưa phù hợp. Hãy giữ đầu, vai và tay trong vùng hướng dẫn.",
  busy: "Máy chủ đang bận. Vui lòng thử lại sau giây lát.",
  error: "Không thể nhận dạng lần này. Vui lòng thử lại.",
  disconnected: "Mất kết nối tới máy chủ nhận dạng. Ứng dụng đang thử kết nối lại.",
};

const phaseLabel: Record<InferencePhase, string> = {
  ready: "Sẵn sàng",
  capturing: "Đang thu",
  processing: "Đang nhận dạng",
  ok: "Đã nhận dạng",
  uncertain: "Chưa chắc chắn",
  no_hands: "Chưa thấy tay",
  bad_framing: "Cần chỉnh khung",
  busy: "Máy chủ bận",
  error: "Nhận dạng lỗi",
  disconnected: "Mất kết nối",
};

const phaseTone: Record<InferencePhase, "info" | "warning" | "error"> = {
  ready: "info",
  capturing: "info",
  processing: "info",
  ok: "info",
  uncertain: "warning",
  no_hands: "warning",
  bad_framing: "warning",
  busy: "error",
  error: "error",
  disconnected: "error",
};

const toneIcon = { info: Info, warning: TriangleAlert, error: CircleAlert } as const;

function confidenceLevel(value: number): "high" | "medium" | "low" {
  if (value >= 0.7) return "high";
  if (value >= 0.4) return "medium";
  return "low";
}

function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function ResultPanel({
  phase,
  prediction,
  guidance,
  onAdd,
  canUseLabels,
  eyebrow = "",
  collectionReview = false,
  wordInsertionMode,
  onWordInsertionModeChange,
  automaticInsertionAvailable,
  automaticAdded,
  cameraReady = true,
}: ResultPanelProps) {
  const canAdd =
    canUseLabels &&
    phase === "ok" &&
    prediction?.status === "ok" &&
    Boolean(prediction.label);
  const phaseMessage = guidance ?? phaseText[phase];
  const tone = phaseTone[phase];
  const ToneIcon = toneIcon[tone];
  const suggestionsRef = useDismissibleDetails();
  const insertionRef = useDismissibleDetails();
  const insertionValue = wordInsertionMode === "manual" ? "Xác nhận" : "Tự động";
  return (
    <section className="panel result-panel" aria-labelledby="result-title">
      <div className="panel-heading">
        <h2 id="result-title">Kết quả nhận dạng</h2>
        {/* Secondary choices sit beside the state as small popovers, so the result itself stays one short block. */}
        <div className="result-heading-tools">
          <span className={`recognition-state state-${phase}`} aria-live="polite" aria-atomic="true">
            <i aria-hidden="true" />{!cameraReady && phase === "ready" ? "Chưa bắt đầu" : phaseLabel[phase]}
          </span>
          {Boolean(prediction?.top_k.length) && (
            <details ref={suggestionsRef} className="result-popover top-three" name="result-tools">
              <summary title="Gợi ý khác"><ListOrdered size={18} aria-hidden="true" /><span className="sr-only">Gợi ý khác</span></summary>
              <div className="result-popover-content">
                <p>Gợi ý khác</p>
                <ol>
                  {prediction?.top_k.map((candidate) => (
                    <li key={candidate.label}>
                      <span>{candidate.label}</span>
                      <strong>{percent(candidate.confidence)}</strong>
                    </li>
                  ))}
                </ol>
              </div>
            </details>
          )}
          {!collectionReview && (
            <details ref={insertionRef} className="result-popover insertion-settings" name="result-tools">
              <summary title={`Cách thêm từ: ${insertionValue}`}><Settings2 size={18} aria-hidden="true" />
                <span className="sr-only">Cách thêm từ</span><span className="sr-only setting-value">{insertionValue}</span></summary>
              <fieldset className="result-popover-content word-insertion-mode">
                <legend>Thêm từ vào câu</legend>
                <div className="word-insertion-options">
                  {(["manual", "automatic"] as const).map((value) => (
                    <label key={value} className={wordInsertionMode === value ? "active" : ""}>
                      <input type="radio" name="word-insertion-mode" value={value}
                        checked={wordInsertionMode === value}
                        aria-label={value === "manual" ? "Thêm từ thủ công" : "Thêm từ tự động"}
                        onChange={() => onWordInsertionModeChange(value)} />
                      {value === "manual" ? "Thủ công" : "Tự động"}
                    </label>
                  ))}
                </div>
              </fieldset>
            </details>
          )}
        </div>
      </div>
      {eyebrow && <p className="eyebrow">{eyebrow}</p>}

      <div className="result-entry">
        <div className="result-live" aria-live="polite" aria-atomic="true">
          {phaseMessage && (
            <p className={`phase-message tone-${tone}`}>
              <ToneIcon size={16} aria-hidden="true" />{phaseMessage}
            </p>
          )}
          {prediction?.label ? (
            <div key={prediction.sequence} className={`primary-prediction ${phase !== "ok" ? "previous-prediction" : ""}`}>
              {(phase === "processing" || phase === "capturing") && <span className="prediction-context">Kết quả lượt trước</span>}
              <span className="result-label">{prediction.label}</span>
              <span className="confidence-row">
                <span className="confidence">
                  Độ tin cậy <strong>{prediction.confidence === null ? "—" : percent(prediction.confidence)}</strong>
                </span>
                {prediction.confidence !== null && (
                  <span className={`confidence-meter confidence-${confidenceLevel(prediction.confidence)}`} aria-hidden="true">
                    <span style={{ width: percent(prediction.confidence) }} />
                  </span>
                )}
              </span>
              {prediction.adjusted?.includes("context") && (
                <span className="prediction-adjusted">Đã xét ngữ cảnh câu</span>
              )}
            </div>
          ) : (
            <p className="empty-result">Chưa có kết quả</p>
          )}
        </div>
        {!collectionReview && wordInsertionMode === "manual" && (
          <button type="button" className="add-button" aria-label="Thêm vào câu"
            onClick={onAdd} disabled={!canAdd} hidden={!prediction?.label}>
            Thêm vào câu<ArrowRight size={18} aria-hidden="true" />
          </button>
        )}
      </div>

      {collectionReview ? (
        <p className="confirmation-note collection-review-note">
          Dự đoán chỉ dùng để đối chiếu. Nhãn bạn chọn ở bước 1 mới là nhãn dùng để cải thiện AI.
        </p>
      ) : (
        <>
          {wordInsertionMode === "manual" ? (
            <>
              {!canUseLabels && (
                <p className="confirmation-note">
                  Chưa xác minh nhãn của mô hình.
                </p>
              )}
            </>
          ) : (
            <p className="automatic-insertion-status" role="status">
              {!automaticInsertionAvailable
                ? "Tự động thêm đang tạm dừng."
                : automaticAdded
                  ? "Đã tự thêm vào câu."
                  : "Đang chờ lượt nhận dạng hợp lệ."}
            </p>
          )}
        </>
      )}
    </section>
  );
}
