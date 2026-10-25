import { useRef, type KeyboardEvent, type PointerEvent, type RefObject } from "react";
import {
  SIDEBAR_COLLAPSE_THRESHOLD,
  SIDEBAR_MAX_WIDTH,
  SIDEBAR_MIN_WIDTH,
  clampSidebarWidth,
} from "../hooks/useSidebarLayout";

const SIDEBAR_RAIL_WIDTH = 68;
const KEYBOARD_STEP = 16;

interface SidebarResizerProps {
  shellRef: RefObject<HTMLDivElement | null>;
  width: number;
  collapsed: boolean;
  onResize: (width: number) => void;
  onCollapse: (collapsed: boolean) => void;
  onReset: () => void;
}

/** Progressive resistance past a bound, so the edge never stops dead under the pointer. */
function rubberband(overshoot: number, dimension: number, constant = 0.55): number {
  return (overshoot * dimension * constant) / (dimension + constant * Math.abs(overshoot));
}

function previewWidth(raw: number): number {
  if (raw > SIDEBAR_MAX_WIDTH) return SIDEBAR_MAX_WIDTH + rubberband(raw - SIDEBAR_MAX_WIDTH, SIDEBAR_MAX_WIDTH);
  if (raw < SIDEBAR_MIN_WIDTH) {
    return Math.max(SIDEBAR_RAIL_WIDTH, SIDEBAR_MIN_WIDTH - rubberband(SIDEBAR_MIN_WIDTH - raw, SIDEBAR_MIN_WIDTH));
  }
  return raw;
}

export function SidebarResizer({ shellRef, width, collapsed, onResize, onCollapse, onReset }: SidebarResizerProps) {
  const drag = useRef<{ startX: number; startWidth: number; raw: number } | null>(null);
  const resizing = useRef(false);

  const setPreview = (raw: number) => {
    const shell = shellRef.current;
    if (!shell) return;
    shell.style.setProperty("--sidebar-width", `${previewWidth(raw)}px`);
    shell.classList.toggle("sidebar-will-collapse", raw < SIDEBAR_COLLAPSE_THRESHOLD);
  };

  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    const startWidth = collapsed ? SIDEBAR_RAIL_WIDTH : width;
    drag.current = { startX: event.clientX, startWidth, raw: startWidth };
    resizing.current = false;
  };

  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    drag.current.raw = drag.current.startWidth + event.clientX - drag.current.startX;
    if (!resizing.current && Math.abs(drag.current.raw - drag.current.startWidth) <= 3) return;
    if (!resizing.current) {
      resizing.current = true;
      shellRef.current?.classList.add("sidebar-resizing");
      // Expanded geometry while dragging out of the rail, so the edge tracks the pointer 1:1.
      shellRef.current?.classList.remove("sidebar-collapsed");
    }
    setPreview(drag.current.raw);
  };

  const finishDrag = () => {
    const current = drag.current;
    const shell = shellRef.current;
    if (!current || !shell) return;
    drag.current = null;
    const moved = Math.abs(current.raw - current.startWidth) > 3;
    resizing.current = false;
    shell.classList.remove("sidebar-resizing", "sidebar-will-collapse");
    if (!moved) {
      // A click without movement restores the committed layout untouched.
      shell.style.setProperty("--sidebar-width", `${width}px`);
      shell.classList.toggle("sidebar-collapsed", collapsed);
      return;
    }
    if (current.raw < SIDEBAR_COLLAPSE_THRESHOLD) {
      shell.style.setProperty("--sidebar-width", `${width}px`);
      shell.classList.add("sidebar-collapsed");
      onCollapse(true);
      return;
    }
    const next = clampSidebarWidth(current.raw);
    shell.style.setProperty("--sidebar-width", `${next}px`);
    onResize(next);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? KEYBOARD_STEP * 3 : KEYBOARD_STEP;
    const base = collapsed ? SIDEBAR_MIN_WIDTH : width;
    const keys: Record<string, () => void> = {
      ArrowLeft: () => (collapsed ? undefined : base - step < SIDEBAR_MIN_WIDTH ? onCollapse(true) : onResize(base - step)),
      ArrowRight: () => onResize(collapsed ? SIDEBAR_MIN_WIDTH : base + step),
      Home: () => onResize(SIDEBAR_MIN_WIDTH),
      End: () => onResize(SIDEBAR_MAX_WIDTH),
      Enter: () => onCollapse(!collapsed),
    };
    const action = keys[event.key];
    if (!action) return;
    event.preventDefault();
    action();
  };

  return (
    <div
      className="sidebar-resizer"
      role="separator"
      aria-orientation="vertical"
      aria-label="Độ rộng sidebar"
      aria-valuemin={SIDEBAR_RAIL_WIDTH}
      aria-valuemax={SIDEBAR_MAX_WIDTH}
      aria-valuenow={collapsed ? SIDEBAR_RAIL_WIDTH : width}
      tabIndex={0}
      title="Kéo để đổi độ rộng · Nhấp đúp để đặt lại"
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={finishDrag}
      onPointerCancel={finishDrag}
      onLostPointerCapture={finishDrag}
      onDoubleClick={onReset}
      onKeyDown={handleKeyDown}
    />
  );
}
