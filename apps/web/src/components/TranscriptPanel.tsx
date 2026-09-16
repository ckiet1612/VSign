interface TranscriptPanelProps {
  words: string[];
  notice: string;
  onUndo: () => void;
  onClear: () => void;
  onCopy: () => void;
}

export function TranscriptPanel({
  words,
  notice,
  onUndo,
  onClear,
  onCopy,
}: TranscriptPanelProps) {
  return (
    <section className="panel transcript-panel" aria-labelledby="transcript-title">
      <div className="transcript-heading">
        <div>
          <p className="eyebrow">Bước 3</p>
          <h2 id="transcript-title">Câu của bạn</h2>
        </div>
        <span>{words.length} từ</span>
      </div>
      <div className="transcript-content" aria-live="polite">
        {words.length ? (
          <p>{words.join(" ")}</p>
        ) : (
          <p className="muted">Các từ bạn xác nhận sẽ được nối tại đây.</p>
        )}
      </div>
      <div className="transcript-actions">
        <button type="button" onClick={onUndo} disabled={!words.length} aria-label="Hoàn tác từ cuối">
          ↶ Hoàn tác
        </button>
        <button type="button" onClick={onClear} disabled={!words.length} aria-label="Xóa toàn bộ câu">
          × Xóa toàn bộ
        </button>
        <button type="button" className="copy-button" onClick={onCopy} disabled={!words.length}>
          Sao chép câu
        </button>
      </div>
      <p className="transcript-storage">Transcript chỉ tồn tại trong bộ nhớ của trang hiện tại.</p>
      <p className="sr-only" aria-live="polite">{notice}</p>
    </section>
  );
}
