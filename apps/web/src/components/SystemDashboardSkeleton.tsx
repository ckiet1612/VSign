import { Bone, PillBone, SkeletonRegion, TextBone } from "./Skeleton";
import "../styles/system-dashboard.css";

// Kept out of the lazy SystemDashboard chunk so the Suspense fallback and the first data load show the same layout.

function TitleBone({ w = 120 }: { w?: number }) {
  return <span className="dash-card-title"><Bone w={18} h={18} r={6} /><TextBone w={w} /></span>;
}

function FigureBone({ size = 44 }: { size?: number }) {
  return <div className="dash-figure"><Bone w={size * 2} h={size} r={10} /><TextBone w={96} size={12} line={16} /></div>;
}

function StatBone({ end = false }: { end?: boolean }) {
  return <div className={`dash-stat${end ? " is-end" : ""}`} style={end ? { justifyItems: "end" } : undefined}>
    <TextBone w={56} size={16} line={22} /><TextBone w={64} size={12} line={16} /></div>;
}

function CardHeadBone({ title, trailing = 72 }: { title: number; trailing?: number }) {
  return <div className="dash-card-head"><TitleBone w={title} /><Bone w={trailing} h={28} r={999} /></div>;
}

function KpiBone() {
  return <div className="dash-card dash-kpi">
    <TitleBone /><FigureBone size={44} />
    <div className="dash-stats"><StatBone /><StatBone end /></div>
    <Bone h={36} r="var(--radius-8)" />
  </div>;
}

function ChartCardBone({ title }: { title: number }) {
  return <div className="dash-card dash-chart-card">
    <CardHeadBone title={title} />
    <div className="dash-chart-stats"><div className="dash-stat-column"><StatBone /><StatBone /></div><FigureBone size={36} />
      <div className="dash-stat-column"><StatBone end /><StatBone end /></div></div>
    <Bone className="dashboard-chart" h={200} r="var(--radius-16)" />
    <div className="dash-legend"><TextBone w={96} size={12} line={16} /><TextBone w={112} size={12} line={16} /></div>
    <TextBone w={120} size={12} line={20} />
  </div>;
}

/** Body of the overview while its first statistics load: same grid, cards and fixed chart heights as the data. */
export function DashboardSkeleton() {
  return <SkeletonRegion label="Đang tải thống kê..." className="dash-layout">
    <div className="dash-main">
      <div className="dash-kpis">
        <KpiBone />
        <div className="dash-card dash-kpi is-gauge">
          <TitleBone w={90} /><div className="dash-stats"><StatBone /><StatBone end /></div>
          <div className="dash-gauge-wrap"><svg className="dash-gauge" viewBox="0 0 220 116" aria-hidden="true">
            <path d="M 18 106 A 92 92 0 0 1 202 106" className="skeleton-arc" /></svg><FigureBone size={44} /></div>
        </div>
        <KpiBone />
      </div>
      <ChartCardBone title={130} />
      <ChartCardBone title={110} />
      <div className="dash-card dash-list-card">
        <CardHeadBone title={120} trailing={110} />
        <div className="dashboard-quota-list">{Array.from({ length: 3 }, (_, index) => <div key={index} className="dashboard-quota">
          <div><TextBone w={90} /><TextBone w={72} size={12} line={16} /></div><Bone h={8} r={4} />
        </div>)}</div>
      </div>
      <div className="dash-card dash-list-card">
        <CardHeadBone title={120} trailing={64} />
        <ul className="dashboard-recent-list">{Array.from({ length: 2 }, (_, index) => <li key={index}>
          <Bone w={40} h={40} r="var(--radius-12)" /><div><TextBone w="55%" /><TextBone w={110} size={12} line={16} /></div><PillBone w={92} />
        </li>)}</ul>
      </div>
    </div>
    <div className="dash-card dash-side">
      <section>
        <CardHeadBone title={120} trailing={32} />
        <div className="dash-runtime"><Bone w={48} h={48} r="var(--radius-16)" /><div style={{ flex: 1 }}><TextBone w="80%" size={16} line={24} /><TextBone w="90%" size={12} line={18} /><TextBone w="50%" size={12} line={18} /></div></div>
        <ul className="dashboard-service-grid">{Array.from({ length: 4 }, (_, index) => <li key={index}>
          <TextBone w={120} /><TextBone w={84} size={12} line={16} /></li>)}</ul>
      </section>
      <section className="dash-activity">
        <CardHeadBone title={130} trailing={72} />
        <TextBone w={140} size={12} line={16} style={{ marginTop: "calc(var(--space-12) * -1)" }} />
        <ol className="dash-timeline skeleton-timeline">{Array.from({ length: 6 }, (_, index) => <li key={index}>
          <div><TextBone w="65%" /><TextBone w={100} size={12} line={16} /></div><PillBone w={80} />
        </li>)}</ol>
      </section>
    </div>
  </SkeletonRegion>;
}

/** Suspense fallback while the dashboard chunk loads: the real hero title over the same skeleton body. */
export function DashboardPageSkeleton() {
  return <div className="workspace-page system-dashboard is-fallback" aria-busy="true">
    <header className="dash-hero">
      <div className="dash-hero-title"><h1 id="workspace-page-title">Tổng quan hệ thống</h1><TextBone w={160} size={12} line={16} style={{ marginTop: "var(--space-12)" }} /></div>
      <div className="dash-hero-side"><div className="dash-toolbar"><Bone w={220} h={40} r="var(--radius-12)" /><Bone w={184} h={40} r="var(--radius-12)" /><Bone w={40} h={40} r="50%" /></div></div>
    </header>
    <DashboardSkeleton />
  </div>;
}
