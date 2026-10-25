import { useState, type FormEvent } from "react";
import { REPLY_MAX } from "../../../../contracts/v1/display";
import { useDismissibleDetails } from "../hooks/useDismissibleDetails";
import { useSpeechDictation } from "../hooks/useSpeechDictation";
import { ChevronDown, MessageReply, Mic, Send, Square, X } from "../icons";

// Common answers at a retail counter; one tap sends them.
const QUICK_REPLIES = [
  "Xin chào, tôi có thể giúp gì cho bạn?",
  "Vui lòng chờ một chút.",
  "Sản phẩm này đang còn hàng.",
  "Sản phẩm này tạm hết hàng.",
  "Mời bạn thanh toán tại quầy.",
  "Cảm ơn bạn, hẹn gặp lại!",
] as const;

export type ReplySource = "typed" | "quick" | "voice";

interface Props {
  /** The answer currently shown to the customer. */
  reply: string;
  /** Whether a counter screen shows the answer; otherwise the customer reads it on this screen. */
  counter: boolean;
  onSend: (text: string, source: ReplySource) => void;
  onClear: () => void;
}

/** F05: the staff side of the conversation. Typed, picked from a list, or dictated, then shown to the customer. */
export function StaffReplyPanel({ reply, counter, onSend, onClear }: Props) {
  const [draft, setDraft] = useState("");
  const [dictated, setDictated] = useState(false);
  // Dictation only fills the box: speech recognition makes mistakes, so the staff member reads it before sending.
  const dictation = useSpeechDictation(text => {
    setDraft(text.slice(0, REPLY_MAX));
    setDictated(true);
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const text = draft.trim();
    if (!text) return;
    onSend(text, dictated ? "voice" : "typed");
    setDraft("");
    setDictated(false);
  };
  const listening = dictation.status === "listening";
  const templatesRef = useDismissibleDetails();
  const sendTemplate = (text: string) => {
    onSend(text, "quick");
    if (templatesRef.current) templatesRef.current.open = false;
  };
  return (
    <section className="panel reply-panel" aria-labelledby="reply-title">
      <div className="transcript-heading">
        <h2 id="reply-title"><MessageReply size={17} aria-hidden="true" />Trả lời khách</h2>
        {/* The list opens upward: the panel is pinned to the bottom of the column. */}
        <details ref={templatesRef} className="reply-templates">
          <summary>Câu mẫu<ChevronDown size={14} aria-hidden="true" /></summary>
          <div className="reply-templates-menu" role="group" aria-label="Câu trả lời mẫu">
            {QUICK_REPLIES.map(text => <button key={text} type="button" onClick={() => sendTemplate(text)}>{text}</button>)}
          </div>
        </details>
      </div>
      {reply && <div className="reply-current" aria-live="polite">
        <span>Khách đang thấy</span>
        <p title={`${reply} (${counter ? "trên màn hình quầy" : "trên màn hình này"})`}>{reply}</p>
        <button type="button" className="icon-button" onClick={onClear} aria-label="Ẩn câu trả lời" title="Ẩn câu trả lời">
          <X size={14} aria-hidden="true" /></button>
      </div>}
      <form className="reply-form" onSubmit={submit}>
        <label className="sr-only" htmlFor="reply-input">Câu trả lời</label>
        <div className="reply-input-shell">
          <input id="reply-input" value={draft} maxLength={REPLY_MAX} autoComplete="off"
            placeholder={listening ? "Đang nghe…" : "Nhập câu trả lời"}
            onChange={event => { setDraft(event.target.value); setDictated(false); }} />
          {dictation.status !== "unsupported" && <button type="button" className={`icon-button${listening ? " is-listening" : ""}`}
            onClick={listening ? dictation.stop : dictation.start} aria-pressed={listening}
            aria-label={listening ? "Dừng nghe" : "Nói để nhập câu trả lời"} title={listening ? "Dừng nghe" : "Nói để nhập câu trả lời"}>
            {listening ? <Square size={17} aria-hidden="true" /> : <Mic size={17} aria-hidden="true" />}
          </button>}
        </div>
        <button type="submit" className="icon-button reply-send" disabled={!draft.trim()} aria-label="Gửi câu trả lời" title="Gửi câu trả lời">
          <Send size={19} aria-hidden="true" /></button>
      </form>
      {dictation.error && <p className="reply-error" role="alert">{dictation.error}</p>}
    </section>
  );
}
