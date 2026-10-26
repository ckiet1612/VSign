import { type KeyboardEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Sparkles } from "../icons";
import { deckOffset } from "./landingLayout";
import { cssVars, useInView, useReducedMotion } from "./landingMotion";

const ADVANCE_MS = 5600;

interface Step {
  title: string;
  tone: "blue" | "indigo" | "green" | "orange" | "dark";
  text: string;
  art: ReactNode;
}

const STEPS: readonly Step[] = [
  { title: "Nhìn", tone: "blue", text: "Camera theo dõi bàn tay, cánh tay và dáng người trong khung vuông ở giữa.", art: <SeeArt /> },
  { title: "16 khung hình", tone: "indigo", text: "Mỗi lần ký, VSign lấy đều 16 khung hình để đọc trọn một chuyển động.", art: <FramesArt /> },
  { title: "Một từ", tone: "green", text: "Mô hình chọn ký hiệu khớp nhất, kèm độ tin cậy và các gợi ý gần đúng.", art: <WordArt /> },
  { title: "Một câu", tone: "orange", text: "Các từ nối thành câu; AI hoàn thiện câu tiếng Việt để nhân viên kiểm tra.", art: <SentenceArt /> },
  { title: "Hai màn hình", tone: "dark", text: "Câu của khách và lời đáp của nhân viên hiện trên hai màn hình ở quầy.", art: <ScreensArt /> },
];

export function StepDeck() {
  const section = useRef<HTMLElement>(null);
  const [active, setActive] = useState(0);
  const [held, setHeld] = useState(false);
  const reduced = useReducedMotion();
  const inView = useInView(section, "-20% 0px");
  const autoplay = inView && !held && !reduced;

  useEffect(() => {
    if (!autoplay) return;
    const timer = window.setTimeout(() => setActive(index => (index + 1) % STEPS.length), ADVANCE_MS);
    return () => window.clearTimeout(timer);
  }, [autoplay, active]);

  const go = (index: number) => setActive((index + STEPS.length) % STEPS.length);
  function onKeyDown(event: KeyboardEvent) {
    if (event.key === "ArrowRight") go(active + 1);
    else if (event.key === "ArrowLeft") go(active - 1);
    else return;
    event.preventDefault();
  }

  return (
    <section className="landing-section landing-steps" id="cach-hoat-dong" ref={section} aria-roledescription="carousel" aria-label="Cách VSign hiểu một ký hiệu">
      <div className="landing-section-head" data-reveal>
        <p className="landing-kicker">Cách hoạt động</p>
        <h2 className="landing-h2">Từ một cử chỉ<br />đến một câu nói.</h2>
      </div>
      <div
        className="landing-deck"
        onPointerEnter={() => setHeld(true)}
        onPointerLeave={() => setHeld(false)}
        onFocus={() => setHeld(true)}
        onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setHeld(false); }}
        onKeyDown={onKeyDown}
        data-reveal
      >
        {STEPS.map((step, index) => {
          const offset = deckOffset(index, active, STEPS.length);
          return (
            <article
              key={step.title}
              className={`landing-step landing-tone-${step.tone}`}
              data-active={offset === 0 || undefined}
              aria-roledescription="slide"
              aria-label={`${index + 1} / ${STEPS.length}: ${step.title}`}
              aria-hidden={offset !== 0}
              style={cssVars({ "--o": offset, "--ao": Math.abs(offset) })}
              onClick={offset === 0 ? undefined : () => go(index)}
            >
              <div className="landing-step-art" aria-hidden="true">{step.art}</div>
              <div className="landing-step-copy">
                <span className="landing-step-number">{String(index + 1).padStart(2, "0")}</span>
                <h3>{step.title}</h3>
                <p>{step.text}</p>
              </div>
            </article>
          );
        })}
      </div>
      <div className="landing-deck-nav">
        <button type="button" className="landing-round-button" onClick={() => go(active - 1)} aria-label="Bước trước"><ArrowLeft size={20} aria-hidden="true" /></button>
        <div className="landing-deck-dots" role="tablist" aria-label="Chọn bước">
          {STEPS.map((step, index) => (
            <button
              key={step.title}
              type="button"
              role="tab"
              aria-selected={index === active}
              aria-label={step.title}
              className="landing-deck-dot"
              data-running={(index === active && autoplay) || undefined}
              style={cssVars({ "--advance": `${ADVANCE_MS}ms` })}
              onClick={() => go(index)}
            ><span key={index === active ? active : undefined} /></button>
          ))}
        </div>
        <button type="button" className="landing-round-button" onClick={() => go(active + 1)} aria-label="Bước sau"><ArrowRight size={20} aria-hidden="true" /></button>
      </div>
    </section>
  );
}

// Hand landmarks in a 100 × 100 box: wrist, then four joints per finger from thumb to little finger.
const FINGERS = [
  [[38, 80], [28, 70], [22, 61], [17, 53]],
  [[42, 60], [40, 45], [39, 35], [38, 26]],
  [[50, 58], [50, 41], [50, 30], [50, 20]],
  [[58, 60], [60, 45], [61, 35], [62, 27]],
  [[65, 65], [70, 54], [73, 46], [76, 39]],
];
const WRIST = [50, 88];

function SeeArt() {
  let dot = 0;
  return (
    <div className="art-see">
      <span className="art-corner" /><span className="art-corner" /><span className="art-corner" /><span className="art-corner" />
      <svg viewBox="0 0 100 100" className="art-hand">
        {FINGERS.map((finger, index) => (
          <polyline key={index} points={[WRIST, ...finger].map(point => point.join(",")).join(" ")} />
        ))}
        {[WRIST, ...FINGERS.flat()].map(([x, y]) => (
          <circle key={`${x}-${y}`} cx={x} cy={y} r={2.2} style={cssVars({ "--i": dot++ })} />
        ))}
      </svg>
      <span className="art-scan" />
      <span className="art-tag">Đang nhìn bàn tay</span>
    </div>
  );
}

function FramesArt() {
  return (
    <div className="art-frames">
      <div className="art-frame-grid">
        {Array.from({ length: 16 }, (_, index) => <span key={index} style={cssVars({ "--i": index })}>{index + 1}</span>)}
      </div>
      <span className="art-tag">16 khung hình · 1 ký hiệu</span>
    </div>
  );
}

function WordArt() {
  return (
    <div className="art-word">
      <div className="art-word-card">
        <span className="art-word-caption">Kết quả nhận dạng</span>
        <strong>Mua</strong>
        <span className="art-word-meter"><span /></span>
        <span className="art-word-caption">Độ tin cậy 91%</span>
        <div className="art-word-alternatives"><span>Mua bán 6%</span><span>Muốn 2%</span></div>
        <span className="art-word-add">Thêm vào câu</span>
      </div>
    </div>
  );
}

function SentenceArt() {
  return (
    <div className="art-sentence">
      <div className="art-sentence-words">
        {["Tôi", "muốn", "mua", "tủ lạnh"].map((word, index) => <span key={word} style={cssVars({ "--i": index })}>{word}</span>)}
      </div>
      <span className="art-sentence-ai"><Sparkles size={14} aria-hidden="true" />Hoàn thiện bằng AI</span>
      <span className="art-sentence-final">Tôi muốn mua tủ lạnh.</span>
    </div>
  );
}

function ScreensArt() {
  return (
    <div className="art-screens">
      <div className="art-screen"><span className="art-screen-bar" /><span className="art-screen-line" /><span className="art-screen-line art-short" /></div>
      <svg className="art-link" viewBox="0 0 120 40" preserveAspectRatio="none"><path d="M4 34 Q60 -10 116 34" /></svg>
      <div className="art-screen art-screen-customer"><span className="art-screen-caption">Cảm ơn</span></div>
    </div>
  );
}
