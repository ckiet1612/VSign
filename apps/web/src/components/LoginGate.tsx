import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { ArrowRight, Eye, EyeOff, Lock, User } from "../icons";
import { LoginSignDemo } from "./LoginSignDemo";
import { SignWordmark } from "./SignWordmark";

interface LoginGateProps {
  workspaceName: string;
  busy?: boolean;
  error?: string;
  embedded?: boolean;
  onLogin: (email: string, password: string) => Promise<void>;
}

// The page backdrop, after the brand film: finger strokes drifting at the edges, fingertip dots, and the bridge
// between two people with a frame travelling along it. Purely decorative.
const BRIDGE = "M24 112C120 28 268 28 364 112";
function Backdrop() {
  return (
    <div className="login-backdrop" aria-hidden="true">
      {["orange", "indigo", "blue", "sky", "green"].map(tone => <i key={tone} className={`login-float-stroke is-${tone}`} />)}
      {[0, 1, 2, 3, 4, 5].map(i => <b key={i} className={`login-tip login-tip-${i}`} />)}
      <svg className="login-bridge" viewBox="0 0 388 140" focusable="false">
        <path d={BRIDGE} pathLength={2} className="is-left" />
        <path d={BRIDGE} pathLength={2} className="is-right" />
        <circle cx="24" cy="112" r="11" className="is-left-node" />
        <circle cx="364" cy="112" r="11" className="is-right-node" />
        <circle r="5" className="login-packet">
          <animateMotion dur="2.8s" repeatCount="indefinite" path={BRIDGE} calcMode="spline" keyPoints="0;1" keyTimes="0;1" keySplines="0.45 0 0.55 1" />
        </circle>
      </svg>
    </div>
  );
}

function BrandPanel() {
  return (
    <div className="login-brand">
      <span className="login-lockup" role="img" aria-label="VSign">
        <img src={`${import.meta.env.BASE_URL}brand/vsign-mark.svg`} alt="" draggable={false} />
        <SignWordmark />
      </span>
      <LoginSignDemo />
    </div>
  );
}

export function LoginGate({ workspaceName, busy = false, error = "", embedded = false, onLogin }: LoginGateProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitError, setSubmitError] = useState("");
  const [errorCount, setErrorCount] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  const mountedRef = useRef(true);
  const id = useId();

  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);
  const Container = embedded ? "section" : "main";
  const Heading = embedded ? "h2" : "h1";
  const pending = busy || submitting;
  const message = submitError || error;
  const trackCapsLock = (event: KeyboardEvent<HTMLInputElement>) => setCapsLock(event.getModifierState?.("CapsLock") ?? false);

  return (
    <Container className={`login-gate${embedded ? " login-gate-embedded" : ""}`} aria-labelledby="login-title">
      {!embedded && <Backdrop />}
      <div className="login-card">
        {!embedded && <BrandPanel />}
        <section className="login-surface">
          {embedded && <img className="login-mark" src={`${import.meta.env.BASE_URL}brand/vsign-mark.svg`} alt="" width="40" height="40" />}
          <Heading id="login-title">Đăng nhập {workspaceName}</Heading>
          <form onSubmit={async event => {
            event.preventDefault();
            if (submitting) return;
            setSubmitError("");
            setSubmitting(true);
            try {
              await onLogin(username, password);
              if (mountedRef.current) setPassword("");
            } catch (loginError) {
              if (mountedRef.current) {
                setSubmitError(loginError instanceof Error ? loginError.message : "Không thể đăng nhập");
                setErrorCount(count => count + 1);
              }
            } finally {
              if (mountedRef.current) setSubmitting(false);
            }
          }}>
            <div className="login-field">
              <label htmlFor={`${id}-user`}>Tên đăng nhập</label>
              <div className="login-input">
                <User size={18} aria-hidden="true" />
                <input id={`${id}-user`} type="text" value={username} autoComplete="username" autoCapitalize="none" spellCheck={false}
                  maxLength={320} required disabled={pending} onChange={event => setUsername(event.target.value)} />
              </div>
            </div>
            <div className="login-field">
              <label htmlFor={`${id}-password`}>Mật khẩu</label>
              <div className="login-input">
                <Lock size={18} aria-hidden="true" />
                <input id={`${id}-password`} type={showPassword ? "text" : "password"} value={password} autoComplete="current-password"
                  minLength={1} required disabled={pending} onChange={event => setPassword(event.target.value)}
                  onKeyDown={trackCapsLock} onKeyUp={trackCapsLock} onBlur={() => setCapsLock(false)} />
                <button type="button" className="login-reveal" onClick={() => setShowPassword(value => !value)} disabled={pending}
                  aria-label={showPassword ? "Ẩn mật khẩu" : "Hiện mật khẩu"} aria-pressed={showPassword} title={showPassword ? "Ẩn mật khẩu" : "Hiện mật khẩu"}>
                  {showPassword ? <EyeOff size={18} aria-hidden="true" /> : <Eye size={18} aria-hidden="true" />}
                </button>
              </div>
              {capsLock && <p className="login-hint" role="status">Caps Lock đang bật</p>}
            </div>
            {message && <p key={errorCount} className="login-error" role="alert">{message}</p>}
            <button type="submit" className="login-submit" disabled={pending}>
              {pending ? <span className="login-spinner" aria-hidden="true" /> : null}
              {pending ? "Đang đăng nhập…" : "Đăng nhập"}
              {!pending && <ArrowRight size={18} aria-hidden="true" />}
            </button>
          </form>
        </section>
      </div>
    </Container>
  );
}
