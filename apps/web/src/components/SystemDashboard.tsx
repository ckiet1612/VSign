import type { AuthenticatedUser } from "@workspace-contracts";
import type { RuntimeSnapshot } from "../hooks/useRuntimeStatus";
import type { WorkspaceView } from "../lib/workspaceNavigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis, matchByDataKey } from "recharts";
import { Activity, ArrowUpRight, BarChart3, Calendar, CircleAlert, CircleCheck, Clock, Database, FileCheck, Folder, Radar, RefreshCw, Robot, Stack, Tag } from "../icons";
import { useSystemDashboard } from "../hooks/useSystemDashboard";
import { useTabMotion } from "../hooks/useTabMotion";
import { activityLabel } from "../lib/activityLabels";
import { CardTitle, Count, Figure, Gauge, LinkButton, Meter, Stat } from "./DashboardParts";
import { morphDateBars, morphDateLine } from "../lib/chartMorph";
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
const chartTick = { fontSize: 11, fill: "var(--muted)" };
const checkedRange = (root: HTMLElement) => root.querySelector<HTMLInputElement>("input:checked")?.parentElement ?? null;
const tooltipStyle = { borderRadius: 12, border: "1px solid var(--line)", fontSize: 12, boxShadow: "var(--shadow-drop-1)" };
// Stable chart props: a new object or function each render would restart a morph that is under way.
const byDate = matchByDataKey("date");
const dailyMargin = { top: 8, right: 4, left: -28, bottom: 0 };
const dailyDomain: [number, (max: number) => number] = [0, max => Math.max(4, max)];
const dailyBarRadius: [number, number, number, number] = [4, 4, 0, 0];
const dailyActiveDot = { r: 4 };
const chartCursor = { fill: "var(--soft)" };
const dailyTooltipLabel = (value: unknown) => `${day(String(value))} UTC`;
const dailyTooltipValue = (value: unknown, name: unknown) => [decimal(Number(value)), name === "average" ? "TB 7 ngày" : "Mẫu đã lưu"] as [string, string];
const MORPH_MS = 600;
const reducedMotion = () => typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;

export function SystemDashboard({ platformUrl, workspaceId, user, runtime, onNavigate }: Props) {
  const [days, setDays] = useState<7 | 30 | 90>(30);
  const rangeRef = useRef<HTMLDivElement>(null);
  useTabMotion(rangeRef, days, { pick: checkedRange });
  const reader = useSystemDashboard(platformUrl, workspaceId, user, days);
  const data = reader.data;
  // Charts morph between ranges but do not replay an entrance each time the overview opens.
  const [morph, setMorph] = useState(false);
  const hasData = !!data;
  useEffect(() => { if (hasData && !reducedMotion()) setMorph(true); }, [hasData]);
  const dailyChartRef = useRef<HTMLDivElement>(null);
  const morphing = useMemo(() => ({
    start: () => dailyChartRef.current?.classList.add("is-morphing"),
    end: () => dailyChartRef.current?.classList.remove("is-morphing"),
  }), []);
  const healthy = runtime.checkedAt !== null && !runtime.healthError && runtime.health !== null;
  const refresh = () => { reader.refresh(); if ("refresh" in runtime && typeof runtime.refresh === "function") void runtime.refresh(); };
  const metadata = runtime.metadata && !runtime.metadataError ? runtime.metadata : null;

  const labels = data?.label_progress ?? [];
  const chartLabels = labels.slice(0, 8);
  const targetTotal = labels.reduce((sum, row) => sum + row.target, 0);
  const coveredTotal = labels.reduce((sum, row) => sum + Math.min(row.count, row.target), 0);
  const reachedLabels = labels.filter(row => row.target > 0 && row.count >= row.target).length;
  const datasets = data ? data.totals.datasets_draft + data.totals.datasets_sealed : 0;
  // Memoised so unrelated re-renders (runtime polling) do not restart a morph in progress.
  const dailySamples = data?.daily_samples;
  const daily = useMemo(() => (dailySamples ?? []).map((row, index, rows) => {
    const window = rows.slice(Math.max(0, index - 6), index + 1);
    return { ...row, average: Math.round((window.reduce((sum, item) => sum + item.count, 0) / window.length) * 10) / 10 };
  }), [dailySamples]);
  const peak = daily.reduce<(typeof daily)[number] | null>((best, row) => row.count > 0 && (!best || row.count > best.count) ? row : best, null);
  const activeDays = daily.filter(row => row.count > 0).length;
  const peakDate = peak?.date;
  const dailyCells = useMemo(() => daily.map(row =>
    <Cell key={row.date} fill={row.date === peakDate ? "var(--lime)" : "var(--black-20)"} />), [daily, peakDate]);

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
            {targetTotal > 0 ? <Figure value={<Count value={percent(coveredTotal, targetTotal)} format={decimal} />} unit="%" caption="Hoàn thành hạn mức" />
              : <Figure value={<Count value={data.period.samples} />} caption={`Mẫu trong ${period} ngày`} />}
            <div className="dash-stats"><Stat value={<Count value={data.totals.samples} />} label="Đã lưu" />
              <Stat value={targetTotal > 0 ? <Count value={targetTotal} /> : "—"} label="Mục tiêu" align="end" /></div>
            <Meter target={targetTotal} segments={[{ value: data.totals.samples - data.period.samples, tone: "ink" }, { value: data.period.samples, tone: "accent" }]} />
          </button>
          <button type="button" className="dash-card dash-kpi is-gauge" onClick={() => onNavigate("data")}>
            <CardTitle icon={Folder}>Bộ dữ liệu</CardTitle>
            <div className="dash-stats"><Stat value={<Count value={data.totals.datasets_sealed} />} label="Đã chốt" />
              <Stat value={<Count value={data.totals.datasets_draft} />} label="Bản nháp" align="end" /></div>
            <div className="dash-gauge-wrap"><Gauge value={datasets ? data.totals.datasets_sealed / datasets : 0} />
              {datasets ? <Figure value={<Count value={percent(data.totals.datasets_sealed, datasets)} format={decimal} />} unit="%" caption={`Đã chốt · ${number(datasets)} bộ`} />
                : <Figure value="0" caption="Chưa có bộ dữ liệu" />}</div>
          </button>
          <button type="button" className="dash-card dash-kpi" onClick={() => onNavigate("evaluation")}>
            <CardTitle icon={BarChart3}>Lượt đánh giá</CardTitle>
            <Figure value={<Count value={data.totals.evaluations} />} caption="Toàn bộ thời gian" />
            <div className="dash-stats"><Stat value={<Count value={data.period.evaluations} />} label={`Trong ${period} ngày`} />
              <Stat value={<Count value={data.totals.models} />} label="Mô hình đăng ký" align="end" /></div>
            <Meter target={data.totals.evaluations} segments={[{ value: data.period.evaluations, tone: "accent" }, { value: data.totals.evaluations - data.period.evaluations, tone: "ink" }]} />
          </button>
        </section>

        <section className="dash-card dash-chart-card" aria-labelledby="daily-samples-title">
          <div className="dash-card-head"><CardTitle icon={Clock} id="daily-samples-title">Mẫu thu theo ngày</CardTitle>
            <span className="dash-card-note">{day(data.start_date)} – {day(data.generated_at)} · UTC</span></div>
          <div className="dash-chart-stats">
            <div className="dash-stat-column"><Stat value={<Count value={data.period.samples} />} label="Mẫu trong kỳ" />
              <Stat value={<><Count value={activeDays} />/<Count value={daily.length} /></>} label="Ngày có mẫu" /></div>
            <Figure value={<Count value={data.period.samples / Math.max(daily.length, 1)} format={decimal} />} caption="Mẫu mỗi ngày (TB)" />
            <div className="dash-stat-column"><Stat value={peak ? <Count value={peak.count} /> : "—"} label="Cao nhất" align="end" /><Stat value={peak ? day(peak.date) : "—"} label="Ngày cao nhất" align="end" /></div>
          </div>
          <div ref={dailyChartRef} className="dashboard-chart" role="img" aria-label={`Biểu đồ mẫu thu trong ${period} ngày: ${number(data.period.samples)} mẫu`}>
            <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 600, height: 200 }}>
              <ComposedChart data={daily} margin={dailyMargin} barCategoryGap="30%" accessibilityLayer>
                <CartesianGrid vertical={false} stroke="var(--line)" />
                <XAxis dataKey="date" tickFormatter={day} tickLine={false} axisLine={false} minTickGap={40} tick={chartTick} />
                <YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={chartTick} domain={dailyDomain} />
                <Tooltip cursor={chartCursor} contentStyle={tooltipStyle} labelFormatter={dailyTooltipLabel}
                  formatter={dailyTooltipValue} />
                {peak && <ReferenceLine x={peak.date} stroke="var(--lime)" strokeWidth={2} />}
                <Bar dataKey="count" maxBarSize={8} radius={dailyBarRadius} isAnimationActive={morph} animationDuration={MORPH_MS} animationEasing="ease-in-out"
                  animationMatchBy={byDate} animationInterpolateFn={morphDateBars} onAnimationStart={morphing.start} onAnimationEnd={morphing.end}>
                  {dailyCells}
                </Bar>
                <Line type="monotone" dataKey="average" stroke="var(--ink)" strokeWidth={2} dot={false} activeDot={dailyActiveDot} isAnimationActive={morph}
                  animationDuration={MORPH_MS} animationEasing="ease-in-out" animationMatchBy={byDate} animationInterpolateFn={morphDateLine} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <div className="dash-chart-foot">
            <div className="dash-legend" aria-hidden="true"><span><i className="is-bar" />Mẫu mỗi ngày</span><span><i className="is-line" />Trung bình 7 ngày</span>
              {peak && <span><i className="is-accent" />Ngày cao nhất</span>}</div>
            {data.period.samples === 0 && <p className="dashboard-empty-note">Chưa có mẫu thu trong kỳ</p>}
          </div>
          <details className="dashboard-data-table"><summary>Số liệu theo ngày</summary><table><thead><tr><th>Ngày UTC</th><th>Mẫu đã lưu</th></tr></thead><tbody>
            {data.daily_samples.map(row => <tr key={row.date}><td>{day(row.date)}</td><td>{number(row.count)}</td></tr>)}</tbody></table></details>
        </section>

        <section className="dash-card dash-chart-card" aria-labelledby="label-distribution-title">
          <div className="dash-card-head"><CardTitle icon={Tag} id="label-distribution-title">Phân bố ký hiệu</CardTitle>
            <LinkButton label="Xem dữ liệu" onClick={() => onNavigate("data")} /></div>
          <div className="dash-chart-stats">
            <Stat value={<Count value={labels.length} />} label="Ký hiệu" />
            <Figure value={labels.length ? <><Count value={reachedLabels} />/<Count value={labels.length} /></> : "0"} caption="Đạt hạn mức" />
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
            <div className="dash-chart-foot"><div className="dash-legend" aria-hidden="true"><span><i className="is-ink" />Chưa đạt hạn mức</span><span><i className="is-accent" />Đã đạt hạn mức</span></div></div>
          </> : <div className="dashboard-chart-empty"><Database size={24} aria-hidden="true" /><p>Chưa có dữ liệu ký hiệu</p></div>}
        </section>

        <section className="dash-card dash-list-card" aria-labelledby="quota-title">
          <div className="dash-card-head"><CardTitle icon={Stack} id="quota-title">Tiến độ hạn mức</CardTitle><span className="dash-card-note">Tất cả bộ dữ liệu</span></div>
          {labels.length ? <div className="dashboard-quota-list dash-scroll-fade">{labels.map(row => <div key={row.label} className="dashboard-quota">
            <div><strong>{row.label}</strong><span>{number(row.count)} / {number(row.target)} mẫu</span></div>
            <Meter size="small" label={`Hạn mức ${row.label}`} valueNow={row.count} target={row.target}
              segments={[{ value: row.count, tone: row.target > 0 && row.count >= row.target ? "accent" : "ink" }]} />
          </div>)}</div> : <p className="dashboard-empty">Chưa có hạn mức thu mẫu</p>}
        </section>

        <section className="dash-card dash-list-card" aria-labelledby="recent-evaluations-title">
          <div className="dash-card-head"><CardTitle icon={FileCheck} id="recent-evaluations-title">Đánh giá gần đây</CardTitle>
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
          <div className="dash-card-head"><CardTitle icon={Radar} id="operations-title">Vận hành dịch vụ</CardTitle><LinkButton label="Giám sát" onClick={() => onNavigate("monitoring")} /></div>
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
          <p className="dash-card-note"><Count value={data.period.events} /> sự kiện trong {period} ngày</p>
          {data.recent_activity.length ? <ol className="dash-timeline dash-scroll-fade">{data.recent_activity.map(row => <li key={row.id} className={row.outcome === "success" ? "is-success" : "is-failure"}>
            <div><strong>{activityLabel(row.event_type) ?? row.event_type}</strong><time dateTime={row.occurred_at}>{time(row.occurred_at)} UTC</time></div>
            <span className={`dashboard-status status-${row.outcome}`}>{row.outcome === "success" ? "Thành công" : "Thất bại"}</span>
          </li>)}</ol> : <p className="dashboard-empty">Chưa có hoạt động trong kỳ</p>}
        </section>
      </aside>
    </div>}
  </div>;
}
