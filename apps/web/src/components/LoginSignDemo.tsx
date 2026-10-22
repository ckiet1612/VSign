import { useEffect, useRef, useState } from "react";

// A real signer as VSign's tracking overlay sees them, looping through Sales30 signs: the hands move, the
// recogniser's 16 sampled frames light up with the sign's progress, then the recognised word appears.
// Landmarks: src/lib/signSamples.json (Sales30 reference clips, VSL-472, CC BY 4.0), loaded only on this screen.

interface Clip { label: string; fps: number; pose: number[][]; hands: number[][][] }

// Fingers base -> tip, drawn in the colours of the mark's strokes (thumb, index, middle, ring, little finger).
const FINGERS = [[0, 1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12], [13, 14, 15, 16], [0, 17, 18, 19, 20]];
const FINGER_COLORS = ["var(--secondary-orange)", "var(--secondary-indigo)", "var(--logo-1)", "var(--logo-1)", "var(--secondary-green)"];
// Pose points: nose, shoulders L/R, elbows L/R, wrists L/R, hips L/R.
const BONES = [[1, 2], [1, 3], [3, 5], [2, 4], [4, 6], [1, 7], [2, 8], [7, 8]];
const JOINTS = [1, 2, 3, 4, 5, 6];
const SLOWER = 1.15; // a touch slower than life, so it reads at a glance
const HOLD = 1.6; // seconds the recognised word stays before the next sign
const FRAMES = 16;

// Landmarks are stored x1000 in a square frame; the stage's viewBox is 0..100.
function sample(frames: number[][], u: number): number[] {
  const f = Math.min(1, Math.max(0, u)) * (frames.length - 1);
  const i = Math.min(frames.length - 2, Math.floor(f));
  const k = f - i;
  return frames[i].map((v, j) => (v + (frames[i + 1][j] - v) * k) / 10);
}
const point = (flat: number[], i: number) => [flat[i * 2], flat[i * 2 + 1]];
const path = (pts: number[][]) => `M${pts.map(([x, y]) => `${x.toFixed(2)} ${y.toFixed(2)}`).join("L")}`;

export function LoginSignDemo() {
  const [clips, setClips] = useState<Clip[] | null>(null);
  const [step, setStep] = useState({ index: 0, done: false });
  const head = useRef<SVGCircleElement>(null);
  const neck = useRef<SVGLineElement>(null);
  const bones = useRef<(SVGLineElement | null)[]>([]);
  const joints = useRef<(SVGCircleElement | null)[]>([]);
  const fingers = useRef<(SVGPathElement | null)[]>([]);
  const bars = useRef<(HTMLElement | null)[]>([]);

  useEffect(() => {
    let alive = true;
    void import("../lib/signSamples.json").then(module => { if (alive) setClips(module.default.clips as Clip[]); });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!clips) return;
    const draw = (clip: Clip, u: number, lit: number) => {
      const pose = sample(clip.pose, u);
      const P = (i: number) => point(pose, i);
      const shoulders = [P(1), P(2)];
      const width = Math.hypot(shoulders[0][0] - shoulders[1][0], shoulders[0][1] - shoulders[1][1]);
      const mid = [(shoulders[0][0] + shoulders[1][0]) / 2, (shoulders[0][1] + shoulders[1][1]) / 2];
      const nose = P(0), r = width * 0.34;
      head.current?.setAttribute("cx", nose[0].toFixed(2));
      head.current?.setAttribute("cy", (nose[1] - r * 0.15).toFixed(2));
      head.current?.setAttribute("r", r.toFixed(2));
      neck.current?.setAttribute("x1", mid[0].toFixed(2));
      neck.current?.setAttribute("y1", mid[1].toFixed(2));
      neck.current?.setAttribute("x2", (mid[0] + (nose[0] - mid[0]) * 0.55).toFixed(2));
      neck.current?.setAttribute("y2", (nose[1] + r * 0.85).toFixed(2));
      BONES.forEach(([a, b], i) => {
        const line = bones.current[i];
        if (!line) return;
        const [x1, y1] = P(a), [x2, y2] = P(b);
        line.setAttribute("x1", x1.toFixed(2)); line.setAttribute("y1", y1.toFixed(2));
        line.setAttribute("x2", x2.toFixed(2)); line.setAttribute("y2", y2.toFixed(2));
      });
      JOINTS.forEach((j, i) => {
        const [x, y] = P(j);
        joints.current[i]?.setAttribute("cx", x.toFixed(2));
        joints.current[i]?.setAttribute("cy", y.toFixed(2));
      });
      clip.hands.forEach((frames, h) => {
        const hand = sample(frames, u);
        FINGERS.forEach((idx, f) => fingers.current[h * 5 + f]?.setAttribute("d", path(idx.map(i => point(hand, i)))));
      });
      bars.current.forEach((bar, i) => bar?.classList.toggle("is-lit", i < lit));
    };

    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      draw(clips[0], 0.55, FRAMES);
      setStep({ index: 0, done: true });
      return;
    }
    const lengths = clips.map(clip => (clip.pose.length / clip.fps) * SLOWER);
    const cycle = lengths.reduce((sum, length) => sum + length + HOLD, 0);
    let frame = 0, last = { index: -1, done: false };
    const start = performance.now();
    const tick = (now: number) => {
      let t = ((now - start) / 1000) % cycle, index = 0;
      while (t > lengths[index] + HOLD) { t -= lengths[index] + HOLD; index++; }
      const u = Math.min(1, t / lengths[index]);
      const eased = u * u * (3 - 2 * u);
      const done = u >= 1;
      draw(clips[index], eased, done ? FRAMES : Math.floor(u * FRAMES));
      if (index !== last.index || done !== last.done) { last = { index, done }; setStep(last); }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [clips]);

  // The last recognised word stays until the next sign is recognised.
  const shown = clips ? (step.done ? step.index : (step.index + clips.length - 1) % clips.length) : -1;
  const word = clips?.[shown]?.label;
  return (
    <div className="login-demo" aria-hidden="true">
      <div className="login-stage">
        <svg className="login-guide" viewBox="0 0 100 100" preserveAspectRatio="none" focusable="false">
          <path d="M0 14V0H14M86 0H100V14M100 86V100H86M14 100H0V86" />
        </svg>
        <span className="login-scan" />
        <svg className="login-signer" viewBox="0 0 100 100" focusable="false">
          <circle ref={head} className="is-guide" />
          <line ref={neck} className="is-guide" />
          {BONES.map((_, i) => <line key={i} ref={node => { bones.current[i] = node; }} />)}
          {[0, 1].flatMap(h => FINGER_COLORS.map((color, f) => (
            <path key={`${h}-${f}`} ref={node => { fingers.current[h * 5 + f] = node; }} className="is-finger" style={{ stroke: color }} />
          )))}
          {JOINTS.map((_, i) => <circle key={i} ref={node => { joints.current[i] = node; }} r="1.3" className="is-joint" />)}
        </svg>
      </div>
      <div className="login-caption">
        <span>Từ vừa nhận</span>
        <span className="login-words">{word ? <b key={shown}>{word}</b> : null}</span>
        <span className={`login-meter${step.done ? " is-done" : ""}`}><i /></span>
        <span className="login-frames">{Array.from({ length: FRAMES }, (_, i) => <i key={i} ref={node => { bars.current[i] = node; }} />)}</span>
      </div>
    </div>
  );
}
