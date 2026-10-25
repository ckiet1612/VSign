import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Camera, Check, ChevronDown, LogOut, MessageSquareText, Video, X } from "../icons";
import type { CounterDisplayController } from "../hooks/useCounterDisplay";
import "../styles/counter-display.css";

interface Props {
  display: CounterDisplayController;
  /** Clears the recognizer's own transcript and result; the counter is cleared by the same command. */
  onNewConversation: () => void;
  /** Called before the session ends, so the conversation can be closed on this side. */
  onEndSession?: () => void;
  /** Connecting swaps the camera source, so it waits while a capture is in progress. */
  locked: boolean;
}

function statusText(display: CounterDisplayController): { text: string; tone: "ok" | "wait" | "off" } {
  if (display.channelStatus !== "open") return { text: "Đang kết nối quầy…", tone: "wait" };
  if (!display.deviceOnline) return { text: "Máy khách chưa mở", tone: "off" };
  if (display.videoState !== "connected" || !display.remoteStream) return { text: "Đang nhận video…", tone: "wait" };
  return { text: "Đang phục vụ", tone: "ok" };
}

/** Staff control in the recognition header: pick the camera source (this laptop or a counter), then serve from here. */
export function CounterDisplayControl({ display, onNewConversation, onEndSession, locked }: Props) {
  const displays = display.overview?.displays ?? [];
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const keyboardOpen = useRef(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const { refresh } = display;

  // The list is refreshed on opening, so online dots and "in use" names are current when choosing.
  useEffect(() => {
    if (!open) return;
    void refresh();
    const close = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [open, refresh]);
  useEffect(() => { if (locked) setOpen(false); }, [locked]);
  // Only a keyboard opening moves focus into the menu; preventScroll keeps the page still either way.
  useEffect(() => {
    if (!open || !keyboardOpen.current) return;
    keyboardOpen.current = false;
    menuRef.current?.querySelector<HTMLButtonElement>("[aria-checked=true]")?.focus({ preventScroll: true });
  }, [open]);

  const onMenuKeys = (event: KeyboardEvent<HTMLDivElement>) => {
    const items = [...event.currentTarget.querySelectorAll<HTMLButtonElement>("[role=menuitemradio]:not(:disabled)")];
    const index = items.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === "Escape") { event.preventDefault(); setOpen(false); trigger.current?.focus({ preventScroll: true }); return; }
    const next = event.key === "ArrowDown" ? index + 1 : event.key === "ArrowUp" ? index - 1
      : event.key === "Home" ? 0 : event.key === "End" ? items.length - 1 : null;
    if (next === null || !items.length) return;
    event.preventDefault();
    items[(next + items.length) % items.length].focus({ preventScroll: true });
  };

  const manage = display.overview?.permissions.manage === true;
  if (!display.connected && !displays.length && !display.notice && !display.occupiedBy && !manage) return null;
  const selectedName = displays.find(row => row.id === display.selectedId)?.name ?? display.displayName;
  const status = statusText(display);

  const notes = <>
    {display.occupiedBy && !display.connected && (
      <div className="counter-display-note" role="status">
        <span>{selectedName || "Quầy này"} đang được <strong>{display.occupiedBy}</strong> sử dụng.</span>
        <button type="button" className="counter-note-action" disabled={locked}
          onClick={() => display.selectedId && display.connect(display.selectedId, true)}>Tiếp quản</button>
      </div>
    )}
    {display.notice && (
      <div className="counter-display-note" role="status">
        <span>{display.notice}</span>
        <button type="button" className="counter-note-dismiss" aria-label="Đóng thông báo" title="Đóng thông báo"
          onClick={display.dismissNotice}><X size={16} aria-hidden="true" /></button>
      </div>
    )}
    {display.listError && !display.connected && <div className="counter-display-note" role="status"><span>{display.listError}</span></div>}
  </>;

  if (display.connected) {
    return <>
      <div className="counter-display is-connected" role="group" aria-label="Màn hình khách">
        <span className="counter-session">
          <span className="counter-session-icon" aria-hidden="true"><Video size={16} /></span>
          <span className="counter-session-text">
            <strong>{display.displayName || selectedName}</strong>
            <span className={`counter-display-status tone-${status.tone}`} role="status"><i aria-hidden="true" />{status.text}</span>
          </span>
        </span>
        <button type="button" className="counter-action" onClick={onNewConversation}
          disabled={display.channelStatus !== "open"} title="Xoá từ và câu trên cả hai máy, giữ kết nối">
          <MessageSquareText size={16} aria-hidden="true" />Cuộc hội thoại mới
        </button>
        <button type="button" className="counter-action" onClick={() => { onEndSession?.(); display.endSession(); }}
          title="Ngắt khỏi quầy; máy khách về màn chờ và tắt camera">
          <LogOut size={16} aria-hidden="true" />Kết thúc phiên
        </button>
      </div>
      {notes}
    </>;
  }

  return <>
    <div ref={root} className="counter-display counter-picker">
      <button ref={trigger} type="button" className="counter-trigger" aria-haspopup="menu" aria-expanded={open}
        disabled={locked} title={locked ? "Chờ lượt thu hiện tại kết thúc" : undefined}
        onClick={event => { keyboardOpen.current = event.detail === 0; setOpen(value => !value); }}
        onKeyDown={event => {
          if (event.key === "Escape" && open) { event.preventDefault(); setOpen(false); return; }
          if (event.key !== "ArrowDown") return;
          event.preventDefault();
          if (open) root.current?.querySelector<HTMLButtonElement>("[role=menuitemradio]")?.focus({ preventScroll: true });
          else { keyboardOpen.current = true; setOpen(true); }
        }}>
        <Camera size={16} aria-hidden="true" />
        <span>Nguồn camera</span>
        <span className="setting-value">Máy này</span>
        <ChevronDown size={14} aria-hidden="true" />
      </button>
      {/* Stays mounted while closed (hidden) so the stylesheet can fade it out. */}
      <div ref={menuRef} className="counter-menu" role="menu" aria-label="Chọn nguồn camera" onKeyDown={onMenuKeys}
        hidden={!open}>
        <button type="button" role="menuitemradio" aria-checked="true" onClick={() => setOpen(false)}>
          <span className="counter-menu-icon" aria-hidden="true"><Camera size={16} /></span>
          <span className="counter-menu-text"><strong>Camera máy này</strong><small>Khách ký trước laptop nhân viên</small></span>
          <Check size={16} aria-hidden="true" />
        </button>
        <p className="counter-menu-label">Màn hình khách</p>
        {displays.map(row => (
          <button key={row.id} type="button" role="menuitemradio" aria-checked="false"
            onClick={() => { setOpen(false); display.connect(row.id); }}>
            <span className="counter-menu-icon" aria-hidden="true"><Video size={16} /></span>
            <span className="counter-menu-text">
              <strong>{row.name}</strong>
              <small className={row.online ? "is-online" : undefined}>
                <i aria-hidden="true" />{row.online ? "Đang mở" : "Chưa mở"}{row.staff ? ` · ${row.staff} đang dùng` : ""}
              </small>
            </span>
          </button>
        ))}
        {!displays.length && (
          <p className="counter-menu-empty">Chưa có màn hình quầy. Thêm trong Cài đặt → Màn hình khách.</p>
        )}
      </div>
    </div>
    {notes}
  </>;
}
