import { useEffect, useRef, useState } from "react";
import { ArrowUpRight, BarChart3, Lock, MessageReply, UsersRound } from "../icons";
import { cssVars, useInView, useReducedMotion } from "./landingMotion";

const LINE_MS = 2400;

// One exchange at the counter, replayed: what the customer signs and what the staff answers.
const EXCHANGE = [
  { who: "Khách", text: "Tôi muốn mua tủ lạnh." },
  { who: "Nhân viên", text: "Dạ, mời anh xem mẫu này ạ." },
  { who: "Khách", text: "Cảm ơn." },
];

const FEATURES = [
  { icon: MessageReply, title: "Trả lời nhanh", text: "Mẫu câu soạn sẵn, bấm một lần là hiện trên màn hình khách." },
  { icon: BarChart3, title: "Báo cáo sử dụng", text: "Xem quầy nào, ai đang dùng VSign và dùng trong bao lâu." },
  { icon: UsersRound, title: "Đội ngũ", text: "Mời nhân viên qua email và phân quyền theo vai trò." },
];

export function CounterShowcase() {
  const devices = useRef<HTMLDivElement>(null);
  const inView = useInView(devices);
  const reduced = useReducedMotion();
  // Lines arrive one by one, hold for a beat once all are shown, then the exchange starts over.
  const [step, setStep] = useState(0);
  const shown = reduced ? EXCHANGE.length - 1 : Math.min(step, EXCHANGE.length - 1);

  useEffect(() => {
    if (!inView || reduced) return;
    const timer = window.setTimeout(() => setStep(value => (value + 1) % (EXCHANGE.length + 1)), LINE_MS);
    return () => window.clearTimeout(timer);
  }, [inView, reduced, step]);

  return (
    <section className="landing-counter" id="tai-quay">
      <div className="landing-section-head" data-reveal>
        <p className="landing-kicker">Tại quầy</p>
        <h2 className="landing-h2">Một quầy.<br />Hai màn hình.</h2>
        <p className="landing-section-lede">Nhân viên ở một phía, khách ở phía kia. Mỗi người nhìn thấy đúng điều mình cần.</p>
      </div>

      <div className="landing-devices" ref={devices} data-reveal>
        <figure className="landing-device">
          <div className="landing-device-bar"><span /><span /><span /><em>Màn hình nhân viên</em></div>
          <div className="landing-device-body landing-device-staff">
            <div className="landing-device-camera"><span className="landing-device-person" /></div>
            <ol className="landing-device-log">
              {EXCHANGE.map((line, index) => (
                <li key={index} data-shown={index <= shown || undefined}><small>{line.who}</small>{line.text}</li>
              ))}
            </ol>
          </div>
        </figure>

        <div className="landing-device-link" aria-hidden="true">
          <svg viewBox="0 0 200 60" preserveAspectRatio="none"><path d="M4 50 Q100 -20 196 50" /></svg>
        </div>

        <figure className="landing-device landing-device-light">
          <div className="landing-device-bar"><span /><span /><span /><em>Màn hình khách</em></div>
          <div className="landing-device-body landing-device-customer">
            {EXCHANGE.map((line, index) => (
              <p key={index} className="landing-device-caption" data-current={index === shown || undefined} aria-hidden={index !== shown}>
                <small>{line.who}</small>{line.text}
              </p>
            ))}
          </div>
        </figure>
      </div>

      <p className="landing-privacy" data-reveal>
        <Lock size={18} aria-hidden="true" />Video đi thẳng giữa hai máy. Không lưu trên máy chủ.
      </p>

      <div className="landing-feature-cards">
        {FEATURES.map(({ icon: Icon, title, text }, index) => (
          <article key={title} className="landing-feature-card" data-reveal style={cssVars({ "--i": index })}>
            <span className="landing-feature-icon"><Icon size={22} aria-hidden="true" /></span>
            <h3>{title}</h3>
            <p>{text}</p>
            <a className="landing-pill-link" href="/">Mở VSign<ArrowUpRight size={16} aria-hidden="true" /></a>
          </article>
        ))}
      </div>
    </section>
  );
}
