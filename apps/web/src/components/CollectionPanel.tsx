import type {
  CaptureDistance,
  CaptureLighting,
  CollectionHand,
  CollectionHandCounts,
  NegativeAction,
  PredictionMessage,
} from "@contracts";
import { referenceVideoFor } from "../referenceSigns";
import { IDLE_LABEL } from "../lib/landmarkInference";

export interface PendingCollectionSample {
  sequence: number;
  expectedLabel: string;
  hand: CollectionHand;
  durationMs: number;
  capturedAt: number;
  frames: string[];
  distance: CaptureDistance;
  lighting: CaptureLighting;
  negativeAction: NegativeAction | null;
}

interface CollectionPanelProps {
  labels: string[];
  selectedLabel: string;
  selectedHand: CollectionHand;
  selectedDistance: CaptureDistance;
  selectedLighting: CaptureLighting;
  selectedNegativeAction: NegativeAction;
  counts: Record<string, CollectionHandCounts>;
  targetCounts: CollectionHandCounts;
  pending: PendingCollectionSample | null;
  prediction: PredictionMessage | null;
  saving: boolean;
  notice: string;
  controlsLocked?: boolean;
  automaticActive?: boolean;
  onLabelChange: (label: string) => void;
  onHandChange: (hand: CollectionHand) => void;
  onDistanceChange: (distance: CaptureDistance) => void;
  onLightingChange: (lighting: CaptureLighting) => void;
  onNegativeActionChange: (action: NegativeAction) => void;
  onSave: () => void;
  onDiscard: () => void;
}

const handText: Record<CollectionHand, string> = {
  right: "Tay phải",
  left: "Tay trái",
};

const negativeActions: ReadonlyArray<{ value: NegativeAction; label: string }> = [
  { value: "still", label: "Đứng yên" },
  { value: "hand_enter_exit", label: "Đưa/rút tay khỏi khung" },
  { value: "adjust_hair_glasses", label: "Chỉnh tóc hoặc kính" },
  { value: "touch_face", label: "Chạm mặt" },
  { value: "turn_body", label: "Quay người" },
  { value: "random_motion", label: "Cử động ngẫu nhiên" },
  { value: "overlap_hands", label: "Chồng hai tay tự nhiên" },
  { value: "other_sign", label: "Ký hiệu ngoài sales-30" },
];

export function CollectionPanel({
  labels,
  selectedLabel,
  selectedHand,
  selectedDistance,
  selectedLighting,
  selectedNegativeAction,
  counts,
  targetCounts,
  pending,
  prediction,
  saving,
  notice,
  controlsLocked = false,
  automaticActive = false,
  onLabelChange,
  onHandChange,
  onDistanceChange,
  onLightingChange,
  onNegativeActionChange,
  onSave,
  onDiscard,
}: CollectionPanelProps) {
  const referenceVideo = referenceVideoFor(selectedLabel);
  const idleSample = selectedLabel === IDLE_LABEL;
  const selectedCounts =
    counts[selectedLabel] ??
    Object.entries(counts).find(
      ([label]) =>
        label.localeCompare(selectedLabel, "vi", { sensitivity: "base" }) === 0,
    )?.[1] ?? { right: 0, left: 0 };
  const selectedCount = selectedCounts[selectedHand];
  const selectedTarget = targetCounts[selectedHand];
  const completed = Math.min(
    100,
    Math.round((selectedCount / selectedTarget) * 100),
  );
  const matchingPrediction =
    pending && prediction?.sequence === pending.sequence ? prediction : null;
  const agrees = idleSample
    ? matchingPrediction !== null && matchingPrediction.status !== "ok"
    : matchingPrediction?.status === "ok" &&
      matchingPrediction.label === pending?.expectedLabel;

  return (
    <section className="panel collection-panel" aria-labelledby="collection-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Bước 1</p>
          <h2 id="collection-title">Chọn mẫu cần quay</h2>
        </div>
        <span className="collection-progress-label">
          {selectedCount}/{selectedTarget} · {handText[selectedHand]}
        </span>
      </div>

      <label className="field-label" htmlFor="collection-label">
        {idleSample ? "Tình huống negative" : "Từ cần thực hiện"}
      </label>
      <select
        id="collection-label"
        className="collection-select"
        value={selectedLabel}
        disabled={controlsLocked}
        onChange={(event) => onLabelChange(event.target.value)}
      >
        {labels.map((label, index) => (
          <option key={label} value={label}>
            {index + 1}. {label}
          </option>
        ))}
      </select>

      <fieldset className="hand-choice">
        <legend>{idleSample ? "Tay xuất hiện chính (nếu có)" : "Tay thực hiện chính"}</legend>
        {(["right", "left"] as const).map((hand) => (
          <button
            key={hand}
            type="button"
            className={selectedHand === hand ? "active" : ""}
            aria-pressed={selectedHand === hand}
            disabled={controlsLocked}
            onClick={() => onHandChange(hand)}
          >
            {handText[hand]}
            <small>{selectedCounts[hand]}/{targetCounts[hand]}</small>
          </button>
        ))}
      </fieldset>

      <div className="capture-context">
        <label>
          <span className="field-label">Khoảng cách</span>
          <select
            className="collection-select"
            value={selectedDistance}
            disabled={controlsLocked}
            onChange={(event) =>
              onDistanceChange(event.target.value as CaptureDistance)
            }
          >
            <option value="near">Gần</option>
            <option value="standard">Chuẩn</option>
            <option value="far">Xa</option>
          </select>
        </label>
        <label>
          <span className="field-label">Ánh sáng</span>
          <select
            className="collection-select"
            value={selectedLighting}
            disabled={controlsLocked}
            onChange={(event) =>
              onLightingChange(event.target.value as CaptureLighting)
            }
          >
            <option value="normal">Đủ sáng</option>
            <option value="low">Thiếu sáng</option>
            <option value="side">Sáng lệch bên</option>
          </select>
        </label>
      </div>

      {idleSample && (
        <label className="negative-action-field">
          <span className="field-label">Hành động negative</span>
          <select
            className="collection-select"
            value={selectedNegativeAction}
            disabled={controlsLocked}
            onChange={(event) =>
              onNegativeActionChange(event.target.value as NegativeAction)
            }
          >
            {negativeActions.map((action) => (
              <option key={action.value} value={action.value}>
                {action.label}
              </option>
            ))}
          </select>
        </label>
      )}

      <div
        className="collection-progress"
        role="progressbar"
        aria-label={`Tiến độ ${selectedLabel}, ${handText[selectedHand]}`}
        aria-valuemin={0}
        aria-valuemax={selectedTarget}
        aria-valuenow={selectedCount}
      >
        <span style={{ width: `${completed}%` }} />
      </div>
      <p className="muted">
        Mục tiêu local là 50 mẫu mỗi tay, tổng 100 mẫu cho mỗi từ sales-30.
      </p>

      {referenceVideo ? (
        <div className="reference-player">
          <video
            key={referenceVideo}
            controls
            muted
            loop
            playsInline
            preload="auto"
            aria-label={`Video mẫu cho từ ${selectedLabel}`}
          >
            <source src={referenceVideo} type="video/mp4" />
          </video>
          <p>
            Xem mẫu rồi dùng đúng tay đã chọn. Hãy theo tay thật của người ký,
            không theo phía hiển thị trên màn hình.
          </p>
        </div>
      ) : idleSample ? (
        <p className="muted">
          Không làm một từ nào: đứng yên, đưa/rút tay, chỉnh tóc hoặc kính,
          quay người hay chồng hai tay tự nhiên. Mỗi lượt chỉ chọn một hành động.
        </p>
      ) : (
        <p className="muted">Chưa có video mẫu cho nhãn này.</p>
      )}

      <div className={`pending-sample ${pending ? "has-sample" : ""}`}>
        {pending ? (
          <>
            <strong>
              Đã quay “{pending.expectedLabel}” · {handText[pending.hand]}
            </strong>
            <span>
              Thời lượng {(pending.durationMs / 1000).toFixed(1)} giây
              {` · ${pending.distance === "near" ? "gần" : pending.distance === "far" ? "xa" : "chuẩn"}`}
              {matchingPrediction
                ? matchingPrediction.label
                  ? ` · AI đoán “${matchingPrediction.label}”`
                  : " · AI đã từ chối dự đoán"
                : " · AI đang xử lý"}
            </span>
            {matchingPrediction?.label && (
              <span className={agrees ? "agreement-ok" : "agreement-mismatch"}>
                {agrees
                  ? idleSample
                    ? "Đúng: AI không ép hành động này thành một từ."
                    : "Kết quả khớp nhãn mong đợi."
                  : "Kết quả chưa khớp — đây là mẫu đặc biệt hữu ích để sửa AI."}
              </span>
            )}
            <div className="sample-actions">
              <button type="button" onClick={onDiscard} disabled={saving}>
                Bỏ mẫu
              </button>
              <button
                type="button"
                className="save-sample-button"
                onClick={onSave}
                disabled={saving}
              >
                {saving ? "Đang lưu…" : "Lưu mẫu vào máy"}
              </button>
            </div>
          </>
        ) : (
          <p>
            {automaticActive
              ? "Phiên tự động sẽ đếm ngược, quay 2,1 giây, kiểm tra hình tay và tự lưu. Chỉ thực hiện một ký hiệu trong mỗi lượt."
              : "Sau khi chọn từ và tay, giữ nút quay ở khung camera trong lúc thực hiện trọn vẹn ký hiệu."}
          </p>
        )}
      </div>
      <p className="collection-notice" aria-live="polite">
        {notice}
      </p>
    </section>
  );
}
