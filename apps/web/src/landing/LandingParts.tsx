import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "../icons";
import { cssVars, prefersReducedMotion, useInView } from "./landingMotion";

const COUNT_MS = 1400;

const STATS = [
  { value: 30, label: "ký hiệu cho quầy bán hàng", tone: "blue" },
  { value: 16, label: "khung hình đọc mỗi ký hiệu", tone: "indigo" },
  { value: 2, label: "màn hình cho một quầy", tone: "green" },
  { value: 0, label: "video lưu trên máy chủ", tone: "orange" },
] as const;

export function StatBand() {
  return (
    <section className="landing-stats" aria-label="VSign trong vài con số">
      {STATS.map((stat, index) => (
        <div key={stat.label} className={`landing-stat landing-tone-${stat.tone}`} data-reveal style={cssVars({ "--i": index })}>
          <CountUp to={stat.value} />
          <span>{stat.label}</span>
        </div>
      ))}
    </section>
  );
}

/** Counts from zero to `to` with an ease-out the first time it scrolls into view. */
export function CountUp({ to }: { to: number }) {
  const element = useRef<HTMLSpanElement>(null);
  const inView = useInView(element);
  const [value, setValue] = useState(() => (prefersReducedMotion() ? to : 0));
  const started = useRef(false);

  useEffect(() => {
    if (!inView || started.current || prefersReducedMotion()) return;
    started.current = true;
    const begin = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - begin) / COUNT_MS);
      setValue(Math.round(to * (1 - (1 - t) ** 4)));
      if (t < 1) frame = window.requestAnimationFrame(tick);
    };
    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, [inView, to]);

  return <strong ref={element} className="landing-count" aria-label={String(to)}>{value}</strong>;
}

const PLACES = [
  ["Siêu thị", "Điện máy", "Điện thoại & laptop", "Ngân hàng", "Quán cà phê", "Quầy thu ngân"],
  ["Quầy dịch vụ", "Cửa hàng tiện lợi", "Gian hàng", "Quầy đổi trả", "Quầy thông tin", "Nhà sách"],
];

export function PlaceMarquee() {
  return (
    <section className="landing-marquee" aria-label="Nơi VSign có thể đứng quầy">
      {PLACES.map((row, rowIndex) => (
        <div key={rowIndex} className="landing-marquee-row" data-direction={rowIndex % 2 ? "reverse" : undefined}>
          {/* The row is drawn twice so the loop is seamless; the copy is hidden from assistive technology. */}
          {[0, 1].map(copy => (
            <ul key={copy} className="landing-marquee-track" aria-hidden={copy === 1 || undefined}>
              {row.map((place, index) => (
                <li key={place} className={`landing-tone-${["blue", "green", "indigo", "orange"][(index + rowIndex) % 4]}`}>{place}</li>
              ))}
            </ul>
          ))}
        </div>
      ))}
    </section>
  );
}

const QUESTIONS = [
  {
    question: "VSign có lưu video của khách không?",
    answer: "Không. Video giữa màn hình nhân viên và màn hình khách đi thẳng giữa hai máy, VSign không lưu video trên máy chủ.",
  },
  {
    question: "VSign hiểu được những ký hiệu nào?",
    answer: "Bộ hiện tại gồm 30 ký hiệu thường gặp ở quầy bán hàng, như Chào, Mua, Điện thoại, Rẻ, Đắt và Cảm ơn. Bạn có thể xem cách ký từng từ ở phần trên.",
  },
  {
    question: "Cửa hàng cần chuẩn bị thiết bị gì?",
    answer: "Một máy tính có camera cho nhân viên là đủ để bắt đầu. Màn hình thứ hai hướng về phía khách giúp khách đọc câu trả lời dễ hơn.",
  },
  {
    question: "Câu được ghép như thế nào?",
    answer: "Mỗi ký hiệu được đọc từ 16 khung hình. Các từ nhận dạng được nối thành câu, AI hoàn thiện câu tiếng Việt và nhân viên kiểm tra trước khi dùng.",
  },
  {
    question: "Làm sao để nhân viên bắt đầu dùng?",
    answer: "Chủ cửa hàng hoặc quản trị viên mời nhân viên qua email. Nhân viên mở lời mời, đăng nhập và bắt đầu ngay tại quầy.",
  },
];

export function LandingFaq() {
  return (
    <section className="landing-section landing-faq" id="cau-hoi">
      <div className="landing-section-head" data-reveal>
        <p className="landing-kicker">Câu hỏi thường gặp</p>
        <h2 className="landing-h2">Điều bạn<br />muốn biết.</h2>
      </div>
      <div className="landing-faq-list" data-reveal>
        {QUESTIONS.map(item => (
          <details key={item.question} className="landing-faq-item" name="landing-faq">
            <summary>{item.question}<span className="landing-faq-icon"><ChevronDown size={20} aria-hidden="true" /></span></summary>
            <p>{item.answer}</p>
          </details>
        ))}
      </div>
    </section>
  );
}
