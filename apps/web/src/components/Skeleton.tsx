import type { CSSProperties, ReactNode } from "react";

type Size = number | string;

/** One neutral block standing in for a piece of content; sized like what it replaces. */
export function Bone({ w = "100%", h = 16, r, className }: { w?: Size; h?: Size; r?: Size; className?: string }) {
  return <span className={className ? `skeleton ${className}` : "skeleton"} style={{ width: w, height: h, borderRadius: r }} aria-hidden="true" />;
}

/** A line of text: the block takes the glyph height and the line box keeps the real line height, so stacks match the loaded copy. */
export function TextBone({ w = "60%", size = 14, line = 20, style }: { w?: Size; size?: number; line?: number; style?: CSSProperties }) {
  return <span className="skeleton-line" style={{ height: line, ...style }} aria-hidden="true"><Bone w={w} h={Math.round(size * 0.8)} r={4} /></span>;
}

/** Status pill with a leading dot (page-status / dashboard-status). */
export function PillBone({ w = 84 }: { w?: Size }) {
  return <Bone w={w} h={24} r={999} />;
}

/**
 * Loading region: announced once to assistive technology while the bones stay hidden from it.
 * Callers pass the real layout classes so the placeholder occupies the same grid, card and spacing as the data.
 */
export function SkeletonRegion({ label, className, children }: { label?: string; className?: string; children: ReactNode }) {
  const classes = className ? `skeleton-region ${className}` : "skeleton-region";
  // Without a label the loading state is announced elsewhere (a toolbar status), so the placeholder stays silent.
  if (label === undefined) return <div className={classes} aria-hidden="true">{children}</div>;
  return <div className={classes} role="status" aria-busy="true"><span className="sr-only">{label}</span>{children}</div>;
}

/** Card heading as rendered by CardHead: 18px icon, muted title and an optional trailing pill. */
export function CardHeadBone({ title = 120, pill }: { title?: Size; pill?: Size }) {
  return <div className="page-card-head" aria-hidden="true">
    <span className="page-card-title"><Bone w={18} h={18} r={6} /><TextBone w={title} /></span>
    {pill !== undefined && <PillBone w={pill} />}
  </div>;
}

/** Label/value fact boxes; `className` is the real grid (models-details, data-facts, …). */
export function FactsBone({ className, count, label = "45%", value = "70%" }: { className: string; count: number; label?: Size; value?: Size }) {
  return <div className={className} aria-hidden="true">{Array.from({ length: count }, (_, index) =>
    <div key={index}><TextBone w={label} size={12} line={20} /><TextBone w={value} line={20} style={{ marginTop: 4 }} /></div>)}</div>;
}

/** Labelled form control: caption line and a 40px field. */
export function FieldBone({ label = 96, w = "100%", className }: { label?: Size; w?: Size; className?: string }) {
  return <span className={className ? `skeleton-field ${className}` : "skeleton-field"} aria-hidden="true">
    <TextBone w={label} line={20} /><Bone w={w} h={40} r="var(--radius-12)" />
  </span>;
}

/**
 * Table placeholder inside the real table wrapper, so cell padding, borders and column widths match.
 * `columns` gives each column's bone width (0 = empty action column, "pill" = status pill, "stack" = title over a muted line); `lead` renders the first cell as avatar + two lines (people lists).
 */
export function TableBone({ columns, rows = 5, lead = false, className }: { columns: Array<Size | "pill" | "stack">; rows?: number; lead?: boolean; className?: string }) {
  return <table className={className} aria-hidden="true">
    <thead><tr>{columns.map((width, index) => <th key={index}>{width !== 0 && <TextBone w={64} size={12} line={16} />}</th>)}</tr></thead>
    <tbody>{Array.from({ length: rows }, (_, row) => <tr key={row}>{columns.map((width, index) => <td key={index}>
      {index === 0 && lead ? <span className="skeleton-person"><Bone w={40} h={40} r="var(--radius-12)" />
        <span><TextBone w={110} /><TextBone w={150} size={12} line={16} style={{ marginTop: 5 }} /></span></span>
        : width === "pill" ? <PillBone /> : width === "stack" ? <><TextBone w="70%" /><TextBone w="45%" size={12} line={16} style={{ marginTop: 5 }} /></>
        : width !== 0 && <TextBone w={width} />}
    </td>)}</tr>)}</tbody>
  </table>;
}
