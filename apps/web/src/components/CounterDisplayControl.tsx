import { useState } from "react";
import { LogOut, MessageSquareText, Plug, Video } from "../icons";
import type { CounterDisplayController } from "../hooks/useCounterDisplay";
import "../styles/counter-display.css";

interface Props {
  display: CounterDisplayController;
  /** Clears the recognizer's own transcript and result; the counter is cleared by the same command. */
  onNewConversation: () => void;
  /** Connecting swaps the camera source, so it waits while a capture is in progress. */
  locked: boolean;
}

function statusText(display: CounterDisplayController): { text: string; tone: "ok" | "wait" | "off" } {
  if (display.channelStatus !== "open") return { text: "Đang kết nối quầy…", tone: "wait" };
  if (!display.deviceOnline) return { text: "Máy khách chưa mở", tone: "off" };
  if (display.videoState !== "connected" || !display.remoteStream) return { text: "Đang nhận video…", tone: "wait" };
  return { text: "Đang phục vụ", tone: "ok" };
}

/** Staff control on the recognition page: pick a counter, then serve its customer from here. */
export function CounterDisplayControl({ display, onNewConversation, locked }: Props) {
  const displays = display.overview?.displays ?? [];
  const [picked, setChoice] = useState(display.selectedId ?? "");
  // A counter revoked or renamed away while picked falls back to "not used".
  const choice = displays.some(row => row.id === picked) ? picked : "";

  if (!display.connected && !displays.length && !display.notice) {
    return display.overview?.permissions.manage ? (
      <p className="counter-display-hint">
        <Video size={16} aria-hidden="true" />Dùng thêm màn hình cho khách: thêm quầy trong Cài đặt → Màn hình khách.
      </p>
    ) : null;
  }
  const status = statusText(display);
  const selectedName = displays.find(row => row.id === display.selectedId)?.name ?? display.displayName;

  return (
    <section className={`counter-display${display.connected ? " is-connected" : ""}`} aria-label="Màn hình khách">
      <div className="counter-display-row">
        <span className="counter-display-icon" aria-hidden="true"><Video size={18} /></span>
        {display.connected ? <>
          <div className="counter-display-current">
            <strong>{display.displayName || selectedName}</strong>
            <span className={`counter-display-status tone-${status.tone}`} role="status"><i aria-hidden="true" />{status.text}</span>
          </div>
          <div className="counter-display-actions">
            <button type="button" className="secondary-button" onClick={onNewConversation}
              disabled={display.channelStatus !== "open"} title="Xoá từ và câu trên cả hai máy, giữ kết nối">
              <MessageSquareText size={16} aria-hidden="true" />Cuộc hội thoại mới
            </button>
            <button type="button" className="secondary-button" onClick={display.endSession}
              title="Ngắt khỏi quầy; máy khách về màn chờ và tắt camera">
              <LogOut size={16} aria-hidden="true" />Kết thúc phiên
            </button>
          </div>
        </> : <>
          <label className="counter-display-picker">
            <span>Màn hình khách</span>
            <select value={choice} onChange={event => setChoice(event.target.value)} disabled={!displays.length}>
              <option value="">Không dùng · camera máy này</option>
              {displays.map(row => (
                <option key={row.id} value={row.id}>
                  {row.name}{row.online ? " · đang mở" : " · chưa mở"}{row.staff ? ` · ${row.staff} đang dùng` : ""}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="secondary-button" disabled={!choice || locked}
            onClick={() => display.connect(choice)}>
            <Plug size={16} aria-hidden="true" />Kết nối
          </button>
        </>}
      </div>
      {display.occupiedBy && !display.connected && (
        <p className="counter-display-note" role="status">
          {selectedName || "Quầy này"} đang được {display.occupiedBy} sử dụng.
          <button type="button" className="secondary-button" disabled={locked}
            onClick={() => display.selectedId && display.connect(display.selectedId, true)}>Tiếp quản</button>
        </p>
      )}
      {display.notice && <p className="counter-display-note" role="status">{display.notice}</p>}
      {display.listError && !display.connected && <p className="counter-display-note" role="status">{display.listError}</p>}
    </section>
  );
}
