import type { ReactNode } from "react";
import { useEffect, useRef } from "react";
import { ArrowUpRight, type Icon } from "../icons";

// Building blocks of the overview cards, shared by every dashboard-style page (overview, usage reports).
const number = (value: number) => value.toLocaleString("vi-VN");

const DIGITS = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"];

/**
 * A figure whose digits roll to their new value when the range or a refresh changes it: each digit
 * slides once, straight to its target, instead of the whole number flickering through every value.
 * Columns are keyed from the right so units stay put while the number gains or loses digits.
 */
export function Count({ value, format = number }: { value: number; format?: (value: number) => string }) {
  const text = format(value);
  const chars = [...text];
  // Only columns a later value adds fade in; the first paint shows the number as is.
  const columns = useRef(chars.length);
  useEffect(() => { columns.current = chars.length; });
  const fresh = (key: number) => key > columns.current ? " is-new" : "";
  return <span className="dash-roll"><span className="sr-only">{text}</span>
    <span aria-hidden="true">{chars.map((char, index) => {
      const key = chars.length - index;
      const digit = DIGITS.indexOf(char);
      return digit < 0 ? <span key={`c${key}`} className={`dash-roll-char${fresh(key)}`}>{char}</span>
        : <span key={`d${key}`} className={`dash-roll-digit${fresh(key)}`}><span className="dash-roll-sizer">{char}</span>
          <span className="dash-roll-strip" style={{ transform: `translateY(${-digit * 10}%)` }}>{DIGITS.map(item => <span key={item}>{item}</span>)}</span></span>;
    })}</span></span>;
}

/** Segmented meter: filled blocks on a track that ends at the target tick, followed by a hatched headroom zone. */
export function Meter({ segments, target, size = "large", label, valueNow }: {
  segments: Array<{ value: number; tone: "ink" | "accent" }>; target: number; size?: "large" | "small"; label?: string; valueNow?: number;
}) {
  const filled = segments.reduce((sum, segment) => sum + segment.value, 0);
  const scale = Math.max(target, filled, 1);
  const a11y = label ? { role: "progressbar", "aria-label": label, "aria-valuenow": valueNow ?? filled, "aria-valuemin": 0, "aria-valuemax": Math.max(filled, target, 1) } : { "aria-hidden": true };
  return <div className={`dash-meter is-${size}`} {...a11y}>
    <div className="dash-meter-track">
      {segments.filter(segment => segment.value > 0).map((segment, index) =>
        <span key={index} className={`dash-meter-fill is-${segment.tone}`} style={{ width: `${(segment.value / scale) * 100}%` }} />)}
    </div>
    <i className="dash-meter-target" />
    <span className="dash-meter-tail" />
  </div>;
}

/** Semicircle gauge with an accent dot marking the current value. */
export function Gauge({ value }: { value: number }) {
  const share = Math.min(Math.max(value, 0), 1);
  const angle = Math.PI * (1 - share);
  const dot = { x: 110 + 92 * Math.cos(angle), y: 106 - 92 * Math.sin(angle) };
  return <svg className="dash-gauge" viewBox="0 0 220 116" aria-hidden="true">
    <path d="M 18 106 A 92 92 0 0 1 202 106" className="dash-gauge-track" pathLength={100} />
    {share > 0 && <path d="M 18 106 A 92 92 0 0 1 202 106" className="dash-gauge-value" pathLength={100} strokeDasharray={`${share * 100} 100`} />}
    <circle cx={dot.x} cy={dot.y} r={7} className="dash-gauge-dot" />
  </svg>;
}

export function Figure({ value, unit, caption }: { value: ReactNode; unit?: string; caption: string }) {
  return <div className="dash-figure"><strong>{value}{unit && <sup>{unit}</sup>}</strong><span>{caption}</span></div>;
}

export function Stat({ value, label, align = "start" }: { value: ReactNode; label: string; align?: "start" | "end" }) {
  return <div className={`dash-stat is-${align}`}><strong>{value}</strong><span>{label}</span></div>;
}

export function CardTitle({ icon: Icon, id, children }: { icon: Icon; id?: string; children: ReactNode }) {
  return <span className="dash-card-title"><Icon size={18} aria-hidden="true" />{id ? <h2 id={id}>{children}</h2> : children}</span>;
}

export function LinkButton({ label, onClick }: { label: string; onClick: () => void }) {
  return <button type="button" className="dash-link" aria-label={label} title={label} onClick={onClick}><ArrowUpRight size={16} aria-hidden="true" /></button>;
}
