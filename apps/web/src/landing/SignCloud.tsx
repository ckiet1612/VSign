import { useState } from "react";
import { REFERENCE_SIGNS, referenceVideoFor } from "../referenceSigns";
import { chipScatter } from "./landingLayout";
import { cssVars } from "./landingMotion";

const TONES = ["blue", "green", "indigo", "orange"] as const;

export function SignCloud() {
  const [selected, setSelected] = useState("Mua");
  const index = REFERENCE_SIGNS.findIndex(sign => sign.label === selected);
  const video = referenceVideoFor(selected);

  return (
    <section className="landing-section landing-signs" id="ky-hieu">
      <div className="landing-section-head" data-reveal>
        <p className="landing-kicker">Bộ ký hiệu Sales30</p>
        <h2 className="landing-h2">30 ký hiệu<br />cho quầy bán hàng.</h2>
        <p className="landing-section-lede">Chọn một từ để xem cách ký. Đây là những ký hiệu VSign nhận dạng hôm nay.</p>
      </div>
      <div className="landing-signs-body">
        <div className="landing-chip-cloud" data-reveal>
          {REFERENCE_SIGNS.map((sign, chip) => {
            const { rotate, lift } = chipScatter(chip);
            return (
              <button
                key={sign.label}
                type="button"
                className={`landing-chip landing-tone-${TONES[chip % TONES.length]}`}
                aria-pressed={sign.label === selected}
                style={cssVars({ "--r": `${rotate}deg`, "--lift": `${lift}px`, "--i": chip })}
                onClick={() => setSelected(sign.label)}
              >{sign.label}</button>
            );
          })}
        </div>
        <figure className="landing-sign-preview" data-reveal>
          {video ? <video key={selected} src={video} autoPlay muted loop playsInline preload="metadata" aria-label={`Cách ký “${selected}”`} /> : null}
          <figcaption>
            <span className="landing-sign-count">{String(index + 1).padStart(2, "0")} / {REFERENCE_SIGNS.length}</span>
            <strong key={selected}>{selected}</strong>
          </figcaption>
        </figure>
      </div>
    </section>
  );
}
