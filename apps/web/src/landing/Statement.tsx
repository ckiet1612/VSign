import { useRef } from "react";
import { parseStatement } from "./landingLayout";
import { cssVars, useScrollProgress } from "./landingMotion";

// [phrase|tone] marks words that light up in a brand colour instead of ink.
const STATEMENT = "Ở quầy, một cử chỉ có thể là [mua,|blue] [cảm ơn|green] hay một câu hỏi. VSign đọc từng chuyển động của đôi tay, "
  + "ghép thành [câu tiếng Việt|indigo] rõ ràng và đặt nó lên màn hình cho người đối diện. Cuộc trò chuyện cứ thế [tiếp tục.|orange]";

const WORDS = parseStatement(STATEMENT);
const statementProgress = (rect: DOMRect, viewport: number) => (viewport * 0.82 - rect.top) / (rect.height + viewport * 0.3);

export function Statement() {
  const paragraph = useRef<HTMLParagraphElement>(null);
  useScrollProgress(paragraph, "--p", statementProgress);
  return (
    <section className="landing-statement" aria-label="VSign làm gì">
      <p ref={paragraph} className="landing-statement-text" style={cssVars({ "--n": WORDS.length })}>
        {WORDS.map((word, index) => (
          <span key={index} className={word.tone ? `landing-lit landing-lit-${word.tone}` : "landing-lit"} style={cssVars({ "--w": index })}>
            {word.text}{" "}
          </span>
        ))}
      </p>
    </section>
  );
}
