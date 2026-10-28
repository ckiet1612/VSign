import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, Pause, Play } from "../icons";
import { workspaceHref } from "../lib/appRoutes";
import { FILM_CHAPTERS, chapterAt, chapterFill } from "./filmChapters";
import { cssVars, prefersReducedMotion, useInView, useScrollProgress } from "./landingMotion";

const MEDIA = `${import.meta.env.BASE_URL}media/`;
const TITLE_LINES = [["Đôi", "tay"], ["cũng", "biết", "nói."]];

// The five rounded strokes of the mark, drifting around the headline; depth scales the pointer parallax.
const STROKES = [
  { color: "orange", x: "6%", y: "58%", length: 13, angle: -62, depth: 1.4 },
  { color: "indigo", x: "15%", y: "16%", length: 7, angle: 90, depth: 0.8 },
  { color: "blue", x: "82%", y: "12%", length: 9, angle: 66, depth: 1.1 },
  { color: "blue", x: "90%", y: "46%", length: 7, angle: 42, depth: 0.6 },
  { color: "green", x: "76%", y: "74%", length: 11, angle: -22, depth: 1.6 },
] as const;

const filmProgress = (rect: DOMRect, viewport: number) => (viewport - rect.top) / (viewport * 0.7);

export function FilmHero() {
  const hero = useRef<HTMLElement>(null);
  usePointerParallax(hero);

  let wordIndex = 0;
  return (
    <>
      <header className="landing-hero" ref={hero}>
        <div className="landing-hero-strokes" aria-hidden="true">
          {STROKES.map((stroke, index) => (
            <span key={index} className={`landing-stroke landing-stroke-${stroke.color}`} style={cssVars({
              "--x": stroke.x, "--y": stroke.y, "--len": stroke.length, "--angle": `${stroke.angle}deg`,
              "--depth": stroke.depth, "--i": index,
            })} />
          ))}
        </div>
        <p className="landing-eyebrow"><span className="landing-live-dot" aria-hidden="true" />Phiên dịch ngôn ngữ ký hiệu tại quầy</p>
        <h1 className="landing-hero-title" aria-label="Đôi tay cũng biết nói.">
          {TITLE_LINES.map((line, lineIndex) => (
            <span key={lineIndex} className="landing-hero-line" aria-hidden="true">
              {line.map(word => (
                <span key={word} className="landing-word"><span style={cssVars({ "--i": wordIndex++ })}>{word}</span></span>
              ))}
            </span>
          ))}
        </h1>
        <p className="landing-hero-lede">
          VSign nhìn đôi tay qua camera, nhận ra từng ký hiệu và ghép thành câu tiếng Việt, để người khiếm thính và nhân viên
          quầy hiểu nhau ngay tại chỗ.
        </p>
        <div className="landing-hero-actions">
          <a className="landing-button landing-button-primary" href={workspaceHref()}>Bắt đầu với VSign<ArrowRight size={18} aria-hidden="true" /></a>
          <a className="landing-button landing-button-ghost" href="#phim"><Play size={18} aria-hidden="true" />Xem phim 60 giây</a>
        </div>
      </header>
      <FilmPlayer />
    </>
  );
}

function FilmPlayer() {
  const section = useRef<HTMLElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const fills = useRef<(HTMLSpanElement | null)[]>([]);
  const userPaused = useRef(prefersReducedMotion());
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(true);
  const [chapter, setChapter] = useState(0);
  const inView = useInView(section, "-15% 0px");
  useScrollProgress(section, "--film-in", filmProgress);

  const paint = useCallback((time: number) => {
    fills.current.forEach((fill, index) => fill?.style.setProperty("--fill", chapterFill(index, time).toFixed(4)));
    setChapter(chapterAt(time));
  }, []);

  // Muted autoplay only while the film is on screen, unless the visitor paused it or asked for reduced motion.
  useEffect(() => {
    const element = video.current;
    if (!element) return;
    if (inView && !userPaused.current) element.play().catch(() => undefined);
    else if (!inView && !element.paused) element.pause();
  }, [inView]);

  useEffect(() => {
    if (!playing) return;
    let frame = 0;
    const tick = () => {
      if (video.current) paint(video.current.currentTime);
      frame = window.requestAnimationFrame(tick);
    };
    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, [playing, paint]);

  function togglePlay() {
    const element = video.current;
    if (!element) return;
    if (element.paused) {
      userPaused.current = false;
      element.play().catch(() => undefined);
    } else {
      userPaused.current = true;
      element.pause();
    }
  }

  function toggleSound() {
    const element = video.current;
    if (!element) return;
    element.muted = !element.muted;
    setMuted(element.muted);
    if (!element.muted && element.paused) {
      userPaused.current = false;
      element.play().catch(() => undefined);
    }
  }

  function seek(index: number) {
    const element = video.current;
    if (!element) return;
    element.currentTime = FILM_CHAPTERS[index].start;
    paint(element.currentTime);
    userPaused.current = false;
    element.play().catch(() => undefined);
  }

  return (
    <section className="landing-film" id="phim" ref={section} aria-label="Phim giới thiệu VSign">
      <div className="landing-film-frame">
        <video
          ref={video}
          className="landing-film-video"
          src={`${MEDIA}vsign-brand-film-60s.mp4`}
          poster={`${MEDIA}vsign-brand-film-60s-poster.jpg`}
          muted
          loop
          playsInline
          preload="metadata"
          aria-label="Phim VSign 60 giây"
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onSeeked={event => paint(event.currentTarget.currentTime)}
          onClick={togglePlay}
        />
        <div className="landing-film-controls">
          <button type="button" className="landing-film-button" onClick={togglePlay} aria-label={playing ? "Tạm dừng phim" : "Phát phim"}>
            {playing ? <Pause size={20} aria-hidden="true" /> : <Play size={20} aria-hidden="true" />}
          </button>
          <span className="landing-film-now" aria-live="polite">
            <span className="landing-film-count">{String(chapter + 1).padStart(2, "0")}</span>
            <span key={chapter} className="landing-film-label">{FILM_CHAPTERS[chapter].label}</span>
          </span>
          <button type="button" className="landing-film-button landing-film-sound" onClick={toggleSound} aria-pressed={!muted}>
            <SoundIcon muted={muted} />
            <span>{muted ? "Bật tiếng" : "Tắt tiếng"}</span>
          </button>
        </div>
      </div>
      <ol className="landing-film-chapters" aria-label="Chương của phim">
        {FILM_CHAPTERS.map((item, index) => (
          <li key={item.label}>
            <button type="button" aria-current={index === chapter ? "step" : undefined} onClick={() => seek(index)}>
              <span className="landing-film-track"><span ref={node => { fills.current[index] = node; }} /></span>
              <span className="landing-film-chapter-label">{item.label}</span>
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}

function SoundIcon({ muted }: { muted: boolean }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M4 9.5v5h3.5L12 18.5v-13L7.5 9.5z" />
      {muted ? <path d="m16 9.5 5 5m0-5-5 5" /> : <path d="M16 9a4 4 0 0 1 0 6m2.5-8.5a7.5 7.5 0 0 1 0 11" />}
    </svg>
  );
}

/** Writes the pointer position over the hero (−1…1) to --mx/--my for the drifting strokes. */
function usePointerParallax(target: React.RefObject<HTMLElement | null>) {
  useEffect(() => {
    const element = target.current;
    if (!element || prefersReducedMotion() || !window.matchMedia?.("(pointer: fine)").matches) return;
    let frame = 0;
    let x = 0;
    let y = 0;
    const write = () => {
      frame = 0;
      element.style.setProperty("--mx", x.toFixed(3));
      element.style.setProperty("--my", y.toFixed(3));
    };
    const move = (event: PointerEvent) => {
      const rect = element.getBoundingClientRect();
      x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      y = ((event.clientY - rect.top) / rect.height) * 2 - 1;
      if (!frame) frame = window.requestAnimationFrame(write);
    };
    element.addEventListener("pointermove", move);
    return () => {
      element.removeEventListener("pointermove", move);
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, [target]);
}
