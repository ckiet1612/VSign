import { useMemo, useRef, useState, type ReactNode } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useTabMotion } from "../hooks/useTabMotion";
import { useUsageReport } from "../hooks/useUsageReport";
import { Calendar, ChartPie, CircleAlert, CircleCheck, Clock, Lock, MessageReply, RefreshCw, Tag, TriangleAlert, UsersRound } from "../icons";
import { CardTitle, Count, Meter, Stat } from "./DashboardParts";
import { Bone, SkeletonRegion, TextBone } from "./Skeleton";
// Cards, figures, meters and the range switch come from the overview; reports.css only adds the report layout.
import "../styles/system-dashboard.css";
import "../styles/reports.css";

interface Props {
  platformUrl: string;
  workspaceId: string;
  enabled: boolean;
}

const LOCAL = "Asia/Ho_Chi_Minh";
const number = (value: number) => value.toLocaleString("vi-VN");
const decimal = (value: number) => value.toLocaleString("vi-VN", { maximumFractionDigits: 1 });
const share = (part: number, whole: number) => whole > 0 ? Math.round((part / whole) * 1000) / 10 : 0;
// Report dates are calendar days in Vietnam time, sent as YYYY-MM-DD.
const day = (value: string) => `${value.slice(8, 10)}/${value.slice(5, 7)}`;
const fullDay = (value: string) => `${value.slice(8, 10)}.${value.slice(5, 7)}.${value.slice(0, 4)}`;
const localDate = (value: string) => new Date(value).toLocaleDateString("sv-SE", { timeZone: LOCAL });
const time = (value: string) => new Date(value).toLocaleString("vi-VN", { timeZone: LOCAL });
const duration = (seconds: number) => seconds >= 60 ? `${Math.floor(seconds / 60)} phút ${Math.round(seconds % 60)} giây` : `${Math.round(seconds)} giây`;
const checkedRange = (root: HTMLElement) => root.querySelector<HTMLInputElement>("input:checked")?.parentElement ?? null;
const chartTick = { fontSize: 11, fill: "var(--muted)" };
const tooltipStyle = { borderRadius: 12, border: "1px solid var(--line)", fontSize: 12, boxShadow: "var(--shadow-drop-1)" };
const chartMargin = { top: 8, right: 0, left: -28, bottom: 0 };
const chartDomain: [number, (max: number) => number] = [0, max => Math.max(4, max)];
const barRadius: [number, number, number, number] = [4, 4, 0, 0];
// Situations ranked by share: the leading one takes the overview's accent, the rest step down the grey scale.
const SHARE_TONES = ["var(--lime)", "var(--black-100)", "var(--black-40)", "var(--black-20)", "var(--black-10)"];

/** A day-by-day trend under a summary figure, scaled to its own range so the shape stays readable. */
function Sparkline({ values, accent = false }: { values: number[]; accent?: boolean }) {
  if (values.length < 2) return <span className="report-spark" aria-hidden="true" />;
  const max = Math.max(...values), min = Math.min(...values);
  const span = max - min || 1;
  const points = values.map((value, index) => `${(index / (values.length - 1)) * 100},${30 - ((value - min) / span) * 26}`).join(" ");
  return <svg className={`report-spark${accent ? " is-accent" : ""}`} viewBox="0 0 100 32" preserveAspectRatio="none" aria-hidden="true">
    <polygon points={`0,32 ${points} 100,32`} /><polyline points={points} /></svg>;
}

function Metric({ icon, label, value, percent = false, note, children }: {
  icon: typeof Tag; label: string; value: number; percent?: boolean; note: string; children: ReactNode;
}) {
  return <div className="report-metric">
    <CardTitle icon={icon}>{label}</CardTitle>
    <div className="dash-figure report-metric-figure"><strong><Count value={value} format={percent ? decimal : number} />{percent && <sup>%</sup>}</strong>
      <span>{note}</span></div>
    {children}
  </div>;
}

/** Same grid as the loaded report: the summary strip, then the cards. */
function ReportSkeleton() {
  return <SkeletonRegion label="Đang tải báo cáo" className="report-body">
    <div className="dash-card report-summary">{[0, 1, 2, 3].map(key => <div key={key} className="report-metric">
      <TextBone w="50%" /><Bone w="40%" h={36} r={8} /><TextBone w="70%" size={12} line={16} /><Bone h={32} r={8} /></div>)}</div>
    {["report-traffic", "report-scenarios"].map(name => <div key={name} className={`dash-card report-card ${name}`}>
      <TextBone w="35%" /><Bone h={220} r={16} /></div>)}
  </SkeletonRegion>;
}

/** F08: what the counter was used for, and where it did not work, without keeping any conversation content. */
export function WorkspaceReports({ platformUrl, workspaceId, enabled }: Props) {
  const [days, setDays] = useState<7 | 30 | 90>(30);
  const rangeRef = useRef<HTMLDivElement>(null);
  useTabMotion(rangeRef, days, { pick: checkedRange });
  const report = useUsageReport(platformUrl, workspaceId, enabled, days);
  const data = report.data;
  const totals = data?.totals;
  // Range labels follow the data on screen, which can briefly be the previous range while a new one loads.
  const period = data?.days ?? days;

  const dailyRows = data?.daily;
  const daily = useMemo(() => (dailyRows ?? []).map(row => ({ date: row.date, ok: row.conversations - row.unhandled, bad: row.unhandled })), [dailyRows]);
  const activeDays = (dailyRows ?? []).filter(row => row.conversations > 0);
  const handledRate = activeDays.map(row => (row.conversations - row.unhandled) / row.conversations);
  const peak = activeDays.reduce<{ date: string; conversations: number } | null>(
    (best, row) => !best || row.conversations > best.conversations ? row : best, null);
  const scenarios = [...(data?.scenarios ?? [])].sort((a, b) => b.conversations - a.conversations);
  const scenarioTotal = scenarios.reduce((sum, row) => sum + row.conversations, 0);
  const handled = totals ? totals.conversations - totals.unhandled_conversations : 0;
  const words = data?.top_words ?? [];
  const topWord = Math.max(...words.map(row => row.count), 1);
  const unhandledShare = totals ? share(totals.unhandled_conversations, totals.conversations) : 0;

  return <div className={`workspace-page system-dashboard reports-page${report.stale ? " is-stale" : ""}`} aria-busy={report.loading}>
    <header className="dash-hero">
      <div className="dash-hero-title">
        <h1 id="workspace-page-title">Báo cáo sử dụng</h1>
        <p className="dashboard-updated">{data ? `Cập nhật ${time(data.generated_at)} · Giờ Việt Nam` : "Hội thoại tại quầy · Giờ Việt Nam"}</p>
      </div>
      <div className="dash-hero-side">
        <div className="dash-toolbar">
          {data && <p className="dash-pill dash-dates"><Calendar size={16} aria-hidden="true" /><span className="sr-only">Kỳ thống kê: </span>
            <time dateTime={data.start_date}>{fullDay(data.start_date)}</time><span aria-hidden="true">–</span>
            <time dateTime={data.generated_at}>{fullDay(localDate(data.generated_at))}</time></p>}
          <div ref={rangeRef} className="dashboard-range" role="radiogroup" aria-label="Khoảng thống kê">
            {([7, 30, 90] as const).map(value => <label key={value}>
              <input type="radio" name="report-period" checked={days === value} value={value} onChange={() => setDays(value)} />
              <span>{value} ngày</span></label>)}
          </div>
          <button type="button" className="page-icon-button dashboard-refresh" title="Làm mới báo cáo" aria-label="Làm mới báo cáo"
            disabled={report.loading} data-busy={report.loading || undefined} onClick={report.refresh}>
            <RefreshCw size={18} aria-hidden="true" /></button>
        </div>
      </div>
    </header>
    {report.error && <div className="dashboard-error" role="alert"><CircleAlert size={18} aria-hidden="true" />
      <span>{report.error}{data && " Đang hiển thị lần đọc trước."}</span>
      <button type="button" onClick={report.refresh} disabled={report.loading}>Thử lại</button></div>}
    {!data && report.loading && <ReportSkeleton />}
    {data && totals && <div className="report-body">
      {/* The report's own signature: one strip of four figures, each with its day-by-day trend. */}
      <section className="dash-card report-summary" aria-label={`Tóm tắt ${period} ngày`}>
        <Metric icon={UsersRound} label="Cuộc hội thoại" value={totals.conversations}
          note={`${number(totals.counter_conversations)} qua màn hình quầy · TB ${duration(totals.avg_duration_seconds)}`}>
          <Sparkline values={data.daily.map(row => row.conversations)} /></Metric>
        <Metric icon={Tag} label="Từ đã nhận dạng" value={totals.words} note={`TB ${decimal(totals.avg_words)} từ mỗi cuộc`}>
          <Sparkline values={data.daily.map(row => row.words)} /></Metric>
        <Metric icon={MessageReply} label="Câu trả lời của nhân viên" value={totals.replies} note={`${number(totals.voice_replies)} câu nhập bằng giọng nói`}>
          <Meter size="small" target={totals.replies} segments={[{ value: totals.voice_replies, tone: "accent" },
            { value: totals.replies - totals.voice_replies, tone: "ink" }]} /></Metric>
        <Metric icon={CircleCheck} label="Xử lý được" value={share(handled, totals.conversations)} percent
          note={`${number(totals.unhandled_conversations)} cuộc chưa xử lý tốt`}>
          <Sparkline values={handledRate} accent /></Metric>
      </section>

      <section className="dash-card report-card report-traffic" aria-labelledby="report-daily-title">
        <div className="dash-card-head"><CardTitle icon={Clock} id="report-daily-title">Lưu lượng theo ngày</CardTitle>
          <span className="dash-card-note">{day(data.start_date)} – {day(localDate(data.generated_at))}</span></div>
        <div className="dash-stats">
          <Stat value={peak ? <Count value={peak.conversations} /> : "—"} label={peak ? `Cao nhất · ${day(peak.date)}` : "Cao nhất"} />
          <Stat value={<Count value={totals.conversations / Math.max(data.daily.length, 1)} format={decimal} />} label="Cuộc mỗi ngày (TB)" />
          <Stat value={<><Count value={activeDays.length} />/<Count value={data.daily.length} /></>} label="Ngày có hội thoại" align="end" />
        </div>
        <div className="dashboard-chart report-chart" role="img" aria-label={`Số cuộc hội thoại mỗi ngày trong ${period} ngày: ${number(totals.conversations)} cuộc`}>
          <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 640, height: 220 }}>
            <BarChart data={daily} margin={chartMargin} barCategoryGap="24%" accessibilityLayer>
              <CartesianGrid vertical={false} stroke="var(--line)" />
              <XAxis dataKey="date" tickFormatter={day} tickLine={false} axisLine={false} minTickGap={32} tick={chartTick} />
              <YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={chartTick} domain={chartDomain} />
              <Tooltip cursor={{ fill: "var(--soft)" }} contentStyle={tooltipStyle} labelFormatter={value => day(String(value))}
                formatter={(value, name) => [number(Number(value)), name === "ok" ? "Xử lý được" : "Chưa xử lý tốt"]} />
              <Bar dataKey="ok" stackId="day" maxBarSize={14} fill="var(--black-20)" isAnimationActive={false} />
              <Bar dataKey="bad" stackId="day" maxBarSize={14} fill="var(--secondary-orange)" radius={barRadius} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="dash-legend" aria-hidden="true"><span><i className="is-bar" />Xử lý được</span><span><i className="is-caution" />Chưa xử lý tốt</span></div>
        <details className="dashboard-data-table"><summary>Số liệu theo ngày</summary><table>
          <thead><tr><th>Ngày</th><th>Hội thoại</th><th>Từ</th><th>Chưa tốt</th></tr></thead>
          <tbody>{data.daily.map(row => <tr key={row.date}><td>{day(row.date)}</td><td>{number(row.conversations)}</td>
            <td>{number(row.words)}</td><td>{number(row.unhandled)}</td></tr>)}</tbody></table></details>
      </section>

      <section className="dash-card report-card report-scenarios" aria-labelledby="report-scenarios-title">
        <div className="dash-card-head"><CardTitle icon={ChartPie} id="report-scenarios-title">Nhóm tình huống</CardTitle></div>
        {scenarioTotal ? <>
          <div className="report-share" aria-hidden="true">{scenarios.filter(row => row.conversations).map((row, index) =>
            <i key={row.id} style={{ flexGrow: row.conversations, background: SHARE_TONES[index] }} />)}</div>
          <table className="report-table">
            <thead><tr><th scope="col">Tình huống</th><th scope="col">Hội thoại</th><th scope="col">Tỷ trọng</th></tr></thead>
            <tbody>{scenarios.map((row, index) => <tr key={row.id}>
              <th scope="row"><i style={{ background: SHARE_TONES[index] }} aria-hidden="true" />{row.label}</th>
              <td>{number(row.conversations)}</td><td>{decimal(share(row.conversations, scenarioTotal))}%</td></tr>)}</tbody>
          </table>
          <p className="dash-card-note report-wrap-note">Một cuộc hội thoại có thể thuộc nhiều nhóm; tỷ trọng tính trên tổng lượt thuộc nhóm.</p>
        </> : <p className="dashboard-empty">Chưa có nhóm tình huống</p>}
      </section>

      <section className="dash-card report-card report-words" aria-labelledby="report-words-title">
        <div className="dash-card-head"><CardTitle icon={Tag} id="report-words-title">Từ được dùng nhiều</CardTitle>
          <span className="dash-card-note">{number(totals.words)} từ trong kỳ</span></div>
        {words.length ? <ol className="report-rank">{words.map((row, index) => <li key={row.label}>
          <b>{index + 1}</b><span>{row.label}</span>
          <Meter size="small" target={topWord} label={`${row.label}: ${row.count} lần`} valueNow={row.count}
            segments={[{ value: row.count, tone: index === 0 ? "accent" : "ink" }]} />
          <strong>{number(row.count)}</strong>
        </li>)}</ol> : <p className="dashboard-empty">Chưa có từ nào được ghi nhận</p>}
      </section>

      <section className="dash-card report-card report-issues" aria-labelledby="report-issues-title">
        <div className="dash-card-head"><CardTitle icon={TriangleAlert} id="report-issues-title">Cần cải thiện</CardTitle>
          <span className="dash-card-note">{decimal(unhandledShare)}% cuộc chưa xử lý tốt</span></div>
        <ul className="dashboard-service-grid report-issue-grid">
          <li><span>Không nhận được từ nào</span><strong>{number(data.unhandled.no_word)}</strong></li>
          <li><span>Chưa rõ hoặc hoàn tác nhiều hơn số từ giữ lại</span><strong>{number(data.unhandled.mostly_unclear)}</strong></li>
          <li><span>Đoạn ký hiệu chưa rõ</span><strong>{number(totals.uncertain + totals.failed)}</strong></li>
          <li><span>Lượt hoàn tác · {number(totals.customer_undos)} do khách</span><strong>{number(totals.undos)}</strong></li>
        </ul>
        <h3>Từ hay bị hoàn tác</h3>
        {data.unhandled.undone_labels.length ? <ul className="report-chips">{data.unhandled.undone_labels.map(row =>
          <li key={row.label} className="dashboard-status">{row.label}<b>{number(row.count)}</b></li>)}</ul>
          : <p className="dashboard-empty">Chưa có từ nào bị hoàn tác</p>}
        {unhandledShare > 20 && <p className="dashboard-warning">Hơn 20% cuộc hội thoại chưa xử lý tốt
          <span>Ưu tiên thu thêm mẫu cho các từ hay bị hoàn tác.</span></p>}
      </section>

      <p className="report-scope"><Lock size={14} aria-hidden="true" />Mỗi cuộc hội thoại được máy nhân viên tổng hợp thành số đếm và nhãn từ khi kết thúc.
        Báo cáo không chứa video, hình ảnh hay nội dung câu trả lời. Ngày tính theo giờ Việt Nam.</p>
    </div>}
  </div>;
}
