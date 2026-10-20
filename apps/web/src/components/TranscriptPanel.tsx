import type { ReactNode } from "react";
import type { SentenceDraft } from "../lib/automaticSentence";
import { Copy, MessageSquareText, Sparkles, Trash2, Undo2 } from "../icons";

interface TranscriptPanelProps {
  children?: ReactNode;
  words: string[];
  notice: string;
  composedSentence: string;
  composedWarning?: string;
  composing: boolean;
  composeAvailable: boolean;
  composeWithAi: boolean;
  automatic?: boolean;
  sentenceDrafts?: SentenceDraft[];
  onCompose: () => void;
  onUndo: () => void;
  onClear: () => void;
  onCopy: () => void;
}

export function TranscriptPanel({
  children,
  words,
  notice,
  composedSentence,
  composedWarning = "",
  composing,
  composeAvailable,
  composeWithAi,
  automatic = false,
  sentenceDrafts = [],
  onCompose,
  onUndo,
  onClear,
  onCopy,
}: TranscriptPanelProps) {
  return (
    <section className={`panel transcript-panel ${words.length ? "has-content" : "is-empty"}`} aria-labelledby="transcript-title">
      <div className="transcript-heading">
        <div>
          <h2 id="transcript-title"><MessageSquareText size={17} aria-hidden="true" />Câu của bạn</h2>
        </div>
        {words.length > 0 && <span>{words.length} từ</span>}
      </div>
      <div className="transcript-content" aria-live="polite">
        {words.length ? (
          <p className="transcript-words">{words.slice(0, -1).join(" ")}{words.length > 1 ? " " : ""}
            <span className="confirmed-word" key={`${words.length}-${words.at(-1)}`}>{words.at(-1)}</span>
          </p>
        ) : (
          <p className="transcript-empty">Chưa có từ</p>
        )}
      </div>
      {automatic && <div className="sentence-drafts" aria-live="polite">
        {sentenceDrafts.filter(item => item.words.length || item.warning).map(item => (
          <div key={item.id} className={`sentence-draft sentence-draft-${item.status}`}>
            <span>{[item.warning, item.compositionWarning].filter(Boolean).join(" · ") || (item.status === "composing" ? "Đang ghép câu dự thảo"
              : item.status === "draft" ? "Dự thảo · chưa xác nhận" : "Đang nhận ký hiệu")}</span>
            {(item.sentence || (item.words.length > 0 && item.words.length < words.length)) &&
              <p>{item.sentence || item.words.join(" ")}</p>}
          </div>
        ))}
      </div>}
      {!automatic && composedSentence && (
        <div className="composed-sentence" aria-live="polite">
          <span>{composedWarning || "Câu hoàn thiện"}</span>
          <p>{composedSentence}</p>
        </div>
      )}
      {children}
      <div className="transcript-actions" hidden={!words.length && !composedSentence && !sentenceDrafts.some(item => item.words.length || item.warning)}>
        {!automatic && <button
          type="button"
          className={`compose-button ${composeWithAi ? "uses-ai" : ""}`}
          onClick={onCompose}
          disabled={!words.length || !composeAvailable || composing}
          aria-label={
            composing
              ? "Đang hoàn thiện câu"
              : composeWithAi
                ? "Hoàn thiện câu bằng AI"
                : "Chuẩn hóa câu"
          }
        >
          <Sparkles size={16} aria-hidden="true" />
          {composing
            ? "Đang hoàn thiện…"
            : composeWithAi
              ? "Hoàn thiện bằng AI"
              : "Chuẩn hóa câu"}
        </button>}
        <button type="button" className="icon-button" onClick={onUndo} disabled={!words.length}
          aria-label="Hoàn tác từ cuối" title="Hoàn tác từ cuối">
          <Undo2 size={18} aria-hidden="true" />
        </button>
        <button type="button" className="icon-button clear-button" onClick={onClear}
          disabled={!words.length && !(automatic && sentenceDrafts.length)}
          aria-label="Xóa toàn bộ câu" title="Xóa toàn bộ câu">
          <Trash2 size={18} aria-hidden="true" />
        </button>
        <button type="button" className="icon-button copy-button" onClick={onCopy} disabled={!words.length}
          aria-label="Sao chép câu" title="Sao chép câu">
          <Copy size={18} aria-hidden="true" />
        </button>
      </div>
      <p className="sr-only" aria-live="polite">{notice}</p>
    </section>
  );
}
