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
import { Check, Save, X } from "../icons";

export interface PendingCollectionSample {
  sampleKey: string;
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
  target: number;
  pending: PendingCollectionSample | null;
  prediction: PredictionMessage | null;
  saving: boolean;
  notice: string;
  controlsLocked?: boolean;
  automaticActive?: boolean;
  /** The data page shows step 1 (word, progress, reference clip) in its own header area instead. */
  wordPickerElsewhere?: boolean;
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

function countsFor(counts: Record<string, CollectionHandCounts>, label: string) {
  return counts[label] ??
    Object.entries(counts).find(
      ([name]) => name.localeCompare(label, "vi", { sensitivity: "base" }) === 0,
    )?.[1] ?? { right: 0, left: 0 };
}

/** Step 1 of collecting: choose the word, see its progress and the reference clip. */
/** Reference clip for the chosen word, or the negative-sample guidance. */
export function CollectionReference({ label }: { label: string }) {
  const referenceVideo = referenceVideoFor(label);
  const idleSample = label === IDLE_LABEL;
  const selectedLabel = label;
  return (<>
        {referenceVideo ? (
          <div className="reference-player">
            <video
              key={referenceVideo}
              controls
              muted
              loop
              playsInline
              preload="metadata"
              aria-label={`Video mẫu cho từ ${selectedLabel}`}
              // A new word remounts the player; it fades in once a frame exists instead of flashing an empty box.
              onLoadedData={(event) => { event.currentTarget.dataset.loaded = ""; }}
            >
              <source src={referenceVideo} type="video/mp4" />
            </video>
            <p>Sales30 · VSL-472 · CC BY 4.0</p>
          </div>
        ) : idleSample ? (
          <p className="muted">
            Không làm một từ nào: đứng yên, đưa/rút tay, chỉnh tóc hoặc kính,
            quay người hay chồng hai tay tự nhiên. Mỗi lượt chỉ chọn một hành động.
          </p>
        ) : (
          <p className="muted">Chưa có video mẫu cho nhãn này.</p>
        )}
  </>);
}

export function CollectionWordPicker({ labels, selectedLabel, counts, target, controlsLocked = false, showReference = true, onLabelChange }: {
  labels: string[];
  /** The data page shows the reference clip in its own card beside the camera instead. */
  showReference?: boolean;
  selectedLabel: string;
  counts: Record<string, CollectionHandCounts>;
  target: number;
  controlsLocked?: boolean;
  onLabelChange: (label: string) => void;
}) {
  const idleSample = selectedLabel === IDLE_LABEL;
  const selectedCounts = countsFor(counts, selectedLabel);
  const selectedCount = selectedCounts.right + selectedCounts.left;
  const selectedTarget = target;
  const completed = Math.min(100, Math.round((selectedCount / selectedTarget) * 100));
  return (
      <div className="collection-step">
        <div className="collection-step-heading">
          <span className="collection-step-index" aria-hidden="true">1</span>
          <h3>Chọn từ</h3>
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
        <div
          className="collection-progress"
          role="progressbar"
          aria-label={`Tiến độ ${selectedLabel}`}
          aria-valuemin={0}
          aria-valuemax={selectedTarget}
          aria-valuenow={selectedCount}
        >
          <span style={{ width: `${completed}%` }} />
        </div>

        {showReference && <CollectionReference label={selectedLabel} />}

      </div>
  );
}

export function CollectionPanel({
  labels,
  selectedLabel,
  selectedHand,
  selectedDistance,
  selectedLighting,
  selectedNegativeAction,
  counts,
  target,
  pending,
  prediction,
  saving,
  notice,
  controlsLocked = false,
  automaticActive = false,
  wordPickerElsewhere = false,
  onLabelChange,
  onHandChange,
  onDistanceChange,
  onLightingChange,
  onNegativeActionChange,
  onSave,
  onDiscard,
}: CollectionPanelProps) {
  const idleSample = selectedLabel === IDLE_LABEL;
  const selectedCounts = countsFor(counts, selectedLabel);
  const selectedCount = selectedCounts.right + selectedCounts.left;
  const selectedTarget = target;
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
          <h2 id="collection-title">Thu {selectedTarget} mẫu mỗi từ</h2>
        </div>
        <span className="collection-progress-label">
          {selectedCount}/{selectedTarget}
        </span>
      </div>

      {wordPickerElsewhere && (
        <div className="collection-step collection-reference">
          <div className="collection-step-heading"><h3>Video mẫu · {selectedLabel}</h3></div>
          <CollectionReference label={selectedLabel} />
        </div>
      )}
      {!wordPickerElsewhere && <CollectionWordPicker labels={labels} selectedLabel={selectedLabel} counts={counts}
        target={target} controlsLocked={controlsLocked} onLabelChange={onLabelChange} />}

      <div className="collection-step">
        <div className="collection-step-heading">
          <span className="collection-step-index" aria-hidden="true">2</span>
          <h3>Thiết lập lượt quay</h3>
        </div>
        <fieldset className="hand-choice">
          <legend>{idleSample ? "Tay xuất hiện chính (nếu có)" : "Tay thuận"}</legend>
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
              {selectedHand === hand && <Check size={16} aria-hidden="true" />}
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

      </div>

      <div className="collection-step">
        <div className="collection-step-heading">
          <span className="collection-step-index" aria-hidden="true">3</span>
          <h3>Duyệt mẫu</h3>
        </div>
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
                  : ""}
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
                  <X size={16} aria-hidden="true" />Bỏ mẫu
                </button>
                <button
                  type="button"
                  className="save-sample-button"
                  onClick={onSave}
                  disabled={saving}
                >
                  <Save size={16} aria-hidden="true" />
                  {saving ? "Đang lưu…" : "Thử lưu lại"}
                </button>
              </div>
            </>
          ) : (
            <p>
              {automaticActive
                ? "Đang thu tự động."
                : "Chưa có lượt đang chờ lưu."}
            </p>
          )}
        </div>
      </div>
      <p className="collection-notice" aria-live="polite">
        {notice}
      </p>
    </section>
  );
}
