import { useEffect, useRef, useState } from "react";
import { SignWordmark } from "../components/SignWordmark";
import { workspaceHref } from "../lib/appRoutes";
import { ArrowRight, Play } from "../icons";
import { CounterShowcase } from "./CounterShowcase";
import { FilmHero } from "./FilmHero";
import { LandingFaq, PlaceMarquee, StatBand } from "./LandingParts";
import { cssVars, useRevealOnScroll, useScrollProgress } from "./landingMotion";
import { SignCloud } from "./SignCloud";
import { Statement } from "./Statement";
import { StepDeck } from "./StepDeck";
import "./landing.css";

const NAV_LINKS = [
  { href: "#cach-hoat-dong", label: "Cách hoạt động" },
  { href: "#ky-hieu", label: "Ký hiệu" },
  { href: "#tai-quay", label: "Tại quầy" },
  { href: "#cau-hoi", label: "Câu hỏi" },
];

export function LandingPage() {
  const page = useRef<HTMLDivElement>(null);
  useRevealOnScroll(page);

  useEffect(() => {
    const previousTitle = document.title;
    document.title = "VSign · Đôi tay cũng biết nói";
    document.documentElement.classList.add("landing-document");
    return () => {
      document.title = previousTitle;
      document.documentElement.classList.remove("landing-document");
    };
  }, []);

  return (
    <div className="landing" ref={page}>
      <a className="landing-skip" href="#noi-dung">Bỏ qua đến nội dung</a>
      <LandingNav />
      <main id="noi-dung">
        <FilmHero />
        <Statement />
        <StepDeck />
        <SignCloud />
        <StatBand />
        <CounterShowcase />
        <PlaceMarquee />
        <LandingFaq />
        <CtaBand />
      </main>
      <LandingFooter />
    </div>
  );
}

function Lockup({ className }: { className?: string }) {
  return (
    <span className={`landing-lockup ${className ?? ""}`} role="img" aria-label="VSign">
      <img className="landing-lockup-mark" src="/brand/vsign-mark.svg" alt="" draggable={false} />
      <SignWordmark className="landing-lockup-sign" />
    </span>
  );
}

function LandingNav() {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const update = () => setScrolled(window.scrollY > 24);
    update();
    window.addEventListener("scroll", update, { passive: true });
    return () => window.removeEventListener("scroll", update);
  }, []);

  return (
    <nav className="landing-nav" data-scrolled={scrolled || undefined} aria-label="VSign">
      <a className="landing-nav-home" href="#noi-dung" aria-label="Lên đầu trang"><Lockup /></a>
      <ul className="landing-nav-links">
        {NAV_LINKS.map(link => <li key={link.href}><a href={link.href}>{link.label}</a></li>)}
      </ul>
      <a className="landing-button landing-button-primary landing-nav-cta" href={workspaceHref()}>Đăng nhập</a>
    </nav>
  );
}

// The CTA strokes swing into the mark's own angles as the band scrolls into place.
const CTA_STROKES = [
  { color: "orange", angle: -64, x: "7%", y: "70%", length: 11 },
  { color: "indigo", angle: 90, x: "11%", y: "20%", length: 6 },
  { color: "blue", angle: 68, x: "90%", y: "16%", length: 8 },
  { color: "blue", angle: 44, x: "93%", y: "48%", length: 6 },
  { color: "green", angle: -22, x: "82%", y: "86%", length: 10 },
] as const;

const ctaProgress = (rect: DOMRect, viewport: number) => (viewport - rect.top) / (viewport * 0.8);

function CtaBand() {
  const band = useRef<HTMLElement>(null);
  useScrollProgress(band, "--cta-in", ctaProgress);
  return (
    <section className="landing-cta" ref={band}>
      <div className="landing-cta-strokes" aria-hidden="true">
        {CTA_STROKES.map((stroke, index) => (
          <span key={index} className={`landing-stroke landing-stroke-${stroke.color}`} style={cssVars({
            "--x": stroke.x, "--y": stroke.y, "--len": stroke.length, "--angle": `${stroke.angle}deg`, "--i": index,
          })} />
        ))}
      </div>
      <p className="landing-kicker">Bắt đầu</p>
      <h2 className="landing-cta-title">Mỗi cuộc trò chuyện<br />cần một nhịp cầu.</h2>
      <div className="landing-hero-actions">
        <a className="landing-button landing-button-primary" href={workspaceHref()}>Đăng nhập VSign<ArrowRight size={18} aria-hidden="true" /></a>
        <a className="landing-button landing-button-ghost" href="#phim"><Play size={18} aria-hidden="true" />Xem lại phim</a>
      </div>
    </section>
  );
}

function LandingFooter() {
  return (
    <footer className="landing-footer">
      <div className="landing-footer-top">
        <p className="landing-footer-tagline">Để mọi cử chỉ<br />đều được hiểu.</p>
        <ul className="landing-footer-links">
          {NAV_LINKS.map(link => <li key={link.href}><a href={link.href}>{link.label}</a></li>)}
          <li><a href={workspaceHref()}>Đăng nhập</a></li>
        </ul>
      </div>
      <div className="landing-footer-mark" data-reveal><Lockup className="landing-lockup-giant" /></div>
      <div className="landing-footer-bottom">
        <span>© {new Date().getFullYear()} VSign · vsign.io.vn</span>
        <span>Chuyển động ký hiệu dựng từ landmark của bộ dữ liệu VSL-472 (CC BY 4.0).</span>
      </div>
    </footer>
  );
}
