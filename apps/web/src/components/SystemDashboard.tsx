import type { AuthenticatedUser } from "@workspace-contracts";
import type { RuntimeSnapshot } from "../hooks/useRuntimeStatus";
import type { WorkspaceView } from "../lib/workspaceNavigation";
import type { ReactNode } from "react";
import { useRef, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Activity, ArrowUpRight, BarChart3, Boxes, Calendar, CircleAlert, CircleCheck, Cpu, Database, RefreshCw, Robot } from "../icons";
import { useSystemDashboard } from "../hooks/useSystemDashboard";
import { useTabMotion } from "../hooks/useTabMotion";
import { DashboardSkeleton } from "./SystemDashboardSkeleton";
import "../styles/system-dashboard.css";

interface Props {
  platformUrl: string;
  workspaceId: string;
  user: AuthenticatedUser | null;
  runtime: RuntimeSnapshot;
  onNavigate: (view: WorkspaceView) => void;
}

const number = (value: number) => value.toLocaleString("vi-VN");
const decimal = (value: number) => value.toLocaleString("vi-VN", { maximumFractionDigits: 1 });
const percent = (part: number, whole: number) => whole > 0 ? Math.round((part / whole) * 1000) / 10 : 0;
const day = (value: string) => new Date(value).toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit", timeZone: "UTC" });
const fullDay = (value: string) => new Date(value).toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric", timeZone: "UTC" }).replaceAll("/", ".");
const time = (value: string) => new Date(value).toLocaleString("vi-VN", { timeZone: "UTC" });
const evaluationStatus: Record<string, string> = { queued: "Đang chờ", running: "Đang đánh giá", completed: "Hoàn tất", failed: "Thất bại", cancelled: "Đã hủy" };
const workerStatus = { online: "Sẵn sàng", offline: "Ngoại tuyến", not_configured: "Chưa cấu hình" };
const eventNames: Record<string, string> = { "auth.login": "Đăng nhập", "auth.logout": "Đăng xuất", "model.registered": "Đăng ký mô hình",
  "auth.login_failed": "Đăng nhập thất bại", "permission.denied": "Từ chối truy cập", "model.baseline_observed": "Ghi nhận phiên bản ban đầu",
  "evaluation.completed": "Hoàn tất đánh giá", "evaluation.created": "Tạo lượt đánh giá", "data.sample_saved": "Lưu mẫu thu" };
const chartTick = { fontSize: 11, fill: "var(--muted)" };
const checkedRange = (root: HTMLElement) => root.querySelector<HTMLInputElement>("input:checked")?.parentElement ?? null;
const tooltipStyle = { borderRadius: 12, border: "1px solid var(--line)", fontSize: 12, boxShadow: "var(--shadow-drop-1)" };

/** Segmented meter: filled blocks on a track that ends at the target tick, followed by a hatched headroom zone. */
function Meter({ segments, target, size = "large", label, valueNow }: {
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
function Gauge({ value }: { value: number }) {
  const share = Math.min(Math.max(value, 0), 1);
  const angle = Math.PI * (1 - share);
  const dot = { x: 110 + 92 * Math.cos(angle), y: 106 - 92 * Math.sin(angle) };
  return <svg className="dash-gauge" viewBox="0 0 220 116" aria-hidden="true">
    <path d="M 18 106 A 92 92 0 0 1 202 106" className="dash-gauge-track" pathLength={100} />
    {share > 0 && <path d="M 18 106 A 92 92 0 0 1 202 106" className="dash-gauge-value" pathLength={100} strokeDasharray={`${share * 100} 100`} />}
    <circle cx={dot.x} cy={dot.y} r={7} className="dash-gauge-dot" />
  </svg>;
}

function Figure({ value, unit, caption }: { value: string; unit?: string; caption: string }) {
  return <div className="dash-figure"><strong>{value}{unit && <sup>{unit}</sup>}</strong><span>{caption}</span></div>;
}

function Stat({ value, label, align = "start" }: { value: ReactNode; label: string; align?: "start" | "end" }) {
  return <div className={`dash-stat is-${align}`}><strong>{value}</strong><span>{label}</span></div>;
}

function CardTitle({ icon: Icon, id, children }: { icon: typeof Database; id?: string; children: ReactNode }) {
  return <span className="dash-card-title"><Icon size={18} aria-hidden="true" />{id ? <h2 id={id}>{children}</h2> : children}</span>;
}

function LinkButton({ label, onClick }: { label: string; onClick: () => void }) {
  return <button type="button" className="dash-link" aria-label={label} title={label} onClick={onClick}><ArrowUpRight size={16} aria-hidden="true" /></button>;
}

export function SystemDashboard({ platformUrl, workspaceId, user, runtime, onNavigate }: Props) {
  const [days, setDays] = useState<7 | 30 | 90>(30);
  const rangeRef = useRef<HTMLDivElement>(null);
  useTabMotion(rangeRef, days, { pick: checkedRange });
  const reader = useSystemDashboard(platformUrl, workspaceId, user, days);
  const data = reader.data;
  const healthy = runtime.checkedAt !== null && !runtime.healthError && runtime.health !== null;
  const refresh = () => { reader.refresh(); if ("refresh" in runtime && typeof runtime.refresh === "function") void runtime.refresh(); };
  const metadata = runtime.metadata && !runtime.metadataError ? runtime.metadata : null;

  const labels = data?.label_progress ?? [];
  const chartLabels = labels.slice(0, 8);
  const targetTotal = labels.reduce((sum, row) => sum + row.target, 0);
  const coveredTotal = labels.reduce((sum, row) => sum + Math.min(row.count, row.target), 0);
  const reachedLabels = labels.filter(row => row.target > 0 && row.count >= row.target).length;
  const datasets = data ? data.totals.datasets_draft + data.totals.datasets_sealed : 0;
  const daily = (data?.daily_samples ?? []).map((row, index, rows) => {
    const window = rows.slice(Math.max(0, index - 6), index + 1);
    return { ...row, average: Math.round((window.reduce((sum, item) => sum + item.count, 0) / window.length) * 10) / 10 };
  });
  const peak = daily.reduce<(typeof daily)[number] | null>((best, row) => row.count > 0 && (!best || row.count > best.count) ? row : best, null);
  const activeDays = daily.filter(row => row.count > 0).length;

  // Range labels follow the data on screen, which can briefly be the previous range while a new one loads.
  const period = data?.days ?? days;

  return <div className={`workspace-page system-dashboard${reader.stale ? " is-stale" : ""}`} aria-busy={reader.loading}>
    <header className="dash-hero">
      <div className="dash-hero-title">
        <h1 id="workspace-page-title">Tổng quan hệ thống</h1>
        <p className="dashboard-updated">{data ? `Cập nhật ${time(data.generated_at)} UTC` : "Thống kê hệ thống · UTC"}</p>
      </div>
      <div className="dash-hero-side">
        <div className="dash-toolbar">
          {data && <p className="dash-pill dash-dates"><Calendar size={16} aria-hidden="true" /><span className="sr-only">Kỳ thống kê: </span>
            <time dateTime={data.start_date}>{fullDay(data.start_date)}</time><span aria-hidden="true">–</span>
            <time dateTime={data.generated_at}>{fullDay(data.generated_at)}</time></p>}
          <div ref={rangeRef} className="dashboard-range" role="radiogroup" aria-label="Khoảng thống kê">
            {([7, 30, 90] as const).map(value => <label key={value}>
              <input type="radio" name="dashboard-period" checked={days === value} value={value} onChange={() => setDays(value)} />
              <span>{value} ngày</span></label>)}
          </div>
          <button type="button" className="page-icon-button dashboard-refresh" title="Làm mới tổng quan" aria-label="Làm mới tổng quan" disabled={reader.loading} data-busy={reader.loading || undefined} onClick={refresh}>
            <RefreshCw size={18} aria-hidden="true" /></button>
        </div>
      </div>
    </header>
    {reader.error && <div className="dashboard-error" role="alert"><CircleAlert size={18} aria-hidden="true" /><span>{reader.error}{data && " Đang hiển thị lần đọc trước."}</span>
      <button type="button" onClick={refresh} disabled={reader.loading}>Thử lại</button></div>}
    {!data && reader.loading && <DashboardSkeleton />}
    {data && <div className="dash-layout">
      <div className="dash-main">
        <section className="dash-kpis" aria-label="Số liệu toàn bộ thời gian">
          <button type="button" className="dash-card dash-kpi" onClick={() => onNavigate("data")}>
            <CardTitle icon={Database}>Tổng mẫu đã lưu</CardTitle>
            {targetTotal > 0 ? <Figure value={decimal(percent(coveredTotal, targetTotal))} unit="%" caption="Hoàn thành hạn mức" />
              : <Figure value={number(data.period.samples)} caption={`Mẫu trong ${period} ngày`} />}
            <div className="dash-stats"><Stat value={number(data.totals.samples)} label="Đã lưu" />
              <Stat value={targetTotal > 0 ? number(targetTotal) : "—"} label="Mục tiêu" align="end" /></div>
            <Meter target={targetTotal} segments={[{ value: data.totals.samples - data.period.samples, tone: "ink" }, { value: data.period.samples, tone: "accent" }]} />
          </button>
          <button type="button" className="dash-card dash-kpi is-gauge" onClick={() => onNavigate("data")}>
            <CardTitle icon={Boxes}>Bộ dữ liệu</CardTitle>
            <div className="dash-stats"><Stat value={number(data.totals.datasets_sealed)} label="Đã chốt" />
              <Stat value={number(data.totals.datasets_draft)} label="Bản nháp" align="end" /></div>
            <div className="dash-gauge-wrap"><Gauge value={datasets ? data.totals.datasets_sealed / datasets : 0} />
              {datasets ? <Figure value={decimal(percent(data.totals.datasets_sealed, datasets))} unit="%" caption={`Đã chốt · ${number(datasets)} bộ`} />
                : <Figure value="0" caption="Chưa có bộ dữ liệu" />}</div>
          </button>
          <button type="button" className="dash-card dash-kpi" onClick={() => onNavigate("evaluation")}>
            <CardTitle icon={BarChart3}>Lượt đánh giá</CardTitle>
            <Figure value={number(data.totals.evaluations)} caption="Toàn bộ thời gian" />
            <div className="dash-stats"><Stat value={number(data.period.evaluations)} label={`Trong ${period} ngày`} />
              <Stat value={number(data.totals.models)} label="Mô hình đăng ký" align="end" /></div>
            <Meter target={data.totals.evaluations} segments={[{ value: data.period.evaluations, tone: "accent" }, { value: data.totals.evaluations - data.period.evaluations, tone: "ink" }]} />
          </button>
        </section>

        <section className="dash-card dash-chart-card" aria-labelledby="daily-samples-title">
          <div className="dash-card-head"><CardTitle icon={Activity} id="daily-samples-title">Mẫu thu theo ngày</CardTitle>
            <span className="dash-card-note">{day(data.start_date)} – {day(data.generated_at)} · UTC</span></div>
          <div className="dash-chart-stats">
            <div className="dash-stat-column"><Stat value={number(data.period.samples)} label="Mẫu trong kỳ" /><Stat value={`${number(activeDays)}/${number(daily.length)}`} label="Ngày có mẫu" /></div>
            <Figure value={decimal(data.period.samples / Math.max(daily.length, 1))} caption="Mẫu mỗi ngày (TB)" />
            <div className="dash-stat-column"><Stat value={peak ? number(peak.count) : "—"} label="Cao nhất" align="end" /><Stat value={peak ? day(peak.date) : "—"} label="Ngày cao nhất" align="end" /></div>
          </div>
          <div className="dashboard-chart" role="img" aria-label={`Biểu đồ mẫu thu trong ${period} ngày: ${number(data.period.samples)} mẫu`}>
            <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 600, height: 200 }}>
              <ComposedChart data={daily} margin={{ top: 8, right: 4, left: -28, bottom: 0 }} barCategoryGap="30%" accessibilityLayer>
                <CartesianGrid vertical={false} stroke="var(--line)" />
                <XAxis dataKey="date" tickFormatter={day} tickLine={false} axisLine={false} minTickGap={40} tick={chartTick} />
                <YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={chartTick} domain={[0, (max: number) => Math.max(4, max)]} />
                <Tooltip cursor={{ fill: "var(--soft)" }} contentStyle={tooltipStyle} labelFormatter={value => `${day(String(value))} UTC`}
                  formatter={(value, name) => [decimal(Number(value)), name === "average" ? "TB 7 ngày" : "Mẫu đã lưu"]} />
                {peak && <ReferenceLine x={peak.date} stroke="var(--lime)" strokeWidth={2} />}
                <Bar dataKey="count" maxBarSize={8} radius={[4, 4, 0, 0]} isAnimationActive={false}>
                  {daily.map(row => <Cell key={row.date} fill={peak && row.date === peak.date ? "var(--lime)" : "var(--black-20)"} />)}
                </Bar>
                <Line type="monotone" dataKey="average" stroke="var(--ink)" strokeWidth={2} dot={false} activeDot={{ r: 4 }} isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <div className="dash-legend" aria-hidden="true"><span><i className="is-bar" />Mẫu mỗi ngày</span><span><i className="is-line" />Trung bình 7 ngày</span>
            {peak && <span><i className="is-accent" />Ngày cao nhất</span>}</div>
          {data.period.samples === 0 && <p className="dashboard-empty-note">Chưa có mẫu thu trong kỳ</p>}
          <details className="dashboard-data-table"><summary>Số liệu theo ngày</summary><table><thead><tr><th>Ngày UTC</th><th>Mẫu đã lưu</th></tr></thead><tbody>
            {data.daily_samples.map(row => <tr key={row.date}><td>{day(row.date)}</td><td>{number(row.count)}</td></tr>)}</tbody></table></details>
        </section>

        <section className="dash-card dash-chart-card" aria-labelledby="label-distribution-title">
          <div className="dash-card-head"><CardTitle icon={BarChart3} id="label-distribution-title">Phân bố ký hiệu</CardTitle>
            <LinkButton label="Xem dữ liệu" onClick={() => onNavigate("data")} /></div>
          <div className="dash-chart-stats">
            <Stat value={number(labels.length)} label="Ký hiệu" />
            <Figure value={labels.length ? `${number(reachedLabels)}/${number(labels.length)}` : "0"} caption="Đạt hạn mức" />
            <Stat value={chartLabels[0]?.label ?? "—"} label="Nhiều mẫu nhất" align="end" />
          </div>
          {chartLabels.length ? <>
            <div className="dashboard-chart" role="img" aria-label="Biểu đồ số mẫu theo ký hiệu">
              <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 420, height: 200 }}>
                <BarChart data={chartLabels} layout="vertical" margin={{ top: 0, right: 12, left: 0, bottom: 0 }} accessibilityLayer>
                  <CartesianGrid horizontal={false} stroke="var(--line)" />
                  <XAxis type="number" allowDecimals={false} tickLine={false} axisLine={false} tick={chartTick} />
                  <YAxis type="category" dataKey="label" width={88} interval={0} tickFormatter={value => String(value).length > 12 ? `${String(value).slice(0, 11)}…` : String(value)}
                    tickLine={false} axisLine={false} tick={{ ...chartTick, fill: "var(--text-secondary)" }} />
                  <Tooltip cursor={{ fill: "var(--soft)" }} contentStyle={tooltipStyle} formatter={value => [number(Number(value)), "Mẫu đã lưu"]} />
                  <Bar dataKey="count" maxBarSize={10} radius={[0, 4, 4, 0]} isAnimationActive={false}>
                    {chartLabels.map(row => <Cell key={row.label} fill={row.target > 0 && row.count >= row.target ? "var(--lime)" : "var(--ink)"} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="dash-legend" aria-hidden="true"><span><i className="is-ink" />Chưa đạt hạn mức</span><span><i className="is-accent" />Đã đạt hạn mức</span></div>
          </> : <div className="dashboard-chart-empty"><Database size={24} aria-hidden="true" /><p>Chưa có dữ liệu ký hiệu</p></div>}
        </section>

        <section className="dash-card dash-list-card" aria-labelledby="quota-title">
          <div className="dash-card-head"><CardTitle icon={Database} id="quota-title">Tiến độ hạn mức</CardTitle><span className="dash-card-note">Tất cả bộ dữ liệu</span></div>
          {labels.length ? <div className="dashboard-quota-list">{labels.map(row => <div key={row.label} className="dashboard-quota">
            <div><strong>{row.label}</strong><span>{number(row.count)} / {number(row.target)} mẫu</span></div>
            <Meter size="small" label={`Hạn mức ${row.label}`} valueNow={row.count} target={row.target}
              segments={[{ value: row.count, tone: row.target > 0 && row.count >= row.target ? "accent" : "ink" }]} />
          </div>)}</div> : <p className="dashboard-empty">Chưa có hạn mức thu mẫu</p>}
        </section>

        <section className="dash-card dash-list-card" aria-labelledby="recent-evaluations-title">
          <div className="dash-card-head"><CardTitle icon={BarChart3} id="recent-evaluations-title">Đánh giá gần đây</CardTitle>
            <button className="dash-text-link" type="button" onClick={() => onNavigate("evaluation")}>Tất cả<ArrowUpRight size={14} aria-hidden="true" /></button></div>
          {data.recent_evaluations.length ? <ul className="dashboard-recent-list">{data.recent_evaluations.map(row => <li key={row.id}>
            <span className="dash-avatar" aria-hidden="true"><Robot size={18} /></span>
            <div><strong>{row.model_version}</strong><time dateTime={row.created_at}>{time(row.created_at)} UTC</time></div>
            <span className={`dashboard-status status-${row.status}`}>{evaluationStatus[row.status] ?? row.status}{row.status === "running" ? ` · ${row.progress}%` : ""}</span>
          </li>)}</ul> : <p className="dashboard-empty">Chưa có lượt đánh giá trong kỳ</p>}
        </section>
      </div>

      <aside className="dash-card dash-side" aria-label="Vận hành">
        <section aria-labelledby="operations-title">
          <div className="dash-card-head"><CardTitle icon={Cpu} id="operations-title">Vận hành dịch vụ</CardTitle><LinkButton label="Giám sát" onClick={() => onNavigate("monitoring")} /></div>
          <div className="dash-runtime">
            <span className="dash-avatar is-accent" aria-hidden="true"><Robot size={22} /></span>
            <div><strong>{metadata ? metadata.model_version : "Chưa xác nhận metadata runtime"}</strong>
              {metadata && <span>{metadata.backend} · {metadata.labels.length} ký hiệu · Protocol {metadata.protocol_version}</span>}</div>
          </div>
          <ul className="dashboard-service-grid">
            <li><span>Dịch vụ nhận dạng</span><strong className={healthy ? "is-online" : "is-offline"}>{healthy ? <CircleCheck size={16} aria-hidden="true" /> : <CircleAlert size={16} aria-hidden="true" />}
              {runtime.checkedAt === null ? "Đang kiểm tra" : healthy ? "Đang hoạt động" : "Chưa kết nối"}</strong></li>
            {([["deployment", "Worker triển khai"], ["evaluation", "Worker đánh giá"], ["integration", "Worker tích hợp"]] as const).map(([key, label]) =>
              <li key={key}><span>{label}</span><strong className={data.workers[key] === "online" ? "is-online" : "is-offline"}>
                {data.workers[key] === "online" ? <CircleCheck size={16} aria-hidden="true" /> : <CircleAlert size={16} aria-hidden="true" />}{workerStatus[data.workers[key]]}</strong></li>)}
          </ul>
          {data.workers.deployment !== "online" && <p className="dashboard-warning">Worker triển khai chưa sẵn sàng<span>Triển khai và rollback vẫn bị chặn.</span></p>}
        </section>
        <section className="dash-activity" aria-labelledby="recent-activity-title">
          <div className="dash-card-head"><CardTitle icon={Activity} id="recent-activity-title">Hoạt động hệ thống</CardTitle>
            <button className="dash-text-link" type="button" onClick={() => onNavigate("activity")}>Nhật ký<ArrowUpRight size={14} aria-hidden="true" /></button></div>
          <p className="dash-card-note">{number(data.period.events)} sự kiện trong {period} ngày</p>
          {data.recent_activity.length ? <ol className="dash-timeline">{data.recent_activity.map(row => <li key={row.id} className={row.outcome === "success" ? "is-success" : "is-failure"}>
            <div><strong>{eventNames[row.event_type] ?? row.event_type}</strong><time dateTime={row.occurred_at}>{time(row.occurred_at)} UTC</time></div>
            <span className={`dashboard-status status-${row.outcome}`}>{row.outcome === "success" ? "Thành công" : "Thất bại"}</span>
          </li>)}</ol> : <p className="dashboard-empty">Chưa có hoạt động trong kỳ</p>}
        </section>
      </aside>
    </div>}
  </div>;
}
