import { useEffect, useRef, useState } from "react";

interface LoginGateProps {
  workspaceName: string;
  busy?: boolean;
  error?: string;
  embedded?: boolean;
  onLogin: (email: string, password: string) => Promise<void>;
}

export function LoginGate({ workspaceName, busy = false, error = "", embedded = false, onLogin }: LoginGateProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitError, setSubmitError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const mountedRef = useRef(true);

  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);
  const Container = embedded ? "section" : "main";
  const Heading = embedded ? "h2" : "h1";

  return (
    <Container className={`login-gate${embedded ? " login-gate-embedded" : ""}`} aria-labelledby="login-title">
      <section className="login-surface">
        <span className="sidebar-kicker">WORKSPACE</span>
        <Heading id="login-title">Đăng nhập {workspaceName}</Heading>
        <p>Đăng nhập để truy cập workspace VSign.</p>
        <form onSubmit={async event => {
          event.preventDefault();
          if (submitting) return;
          setSubmitError("");
          setSubmitting(true);
          try {
            await onLogin(email, password);
          } catch (loginError) {
            if (mountedRef.current) setSubmitError(loginError instanceof Error ? loginError.message : "Không thể đăng nhập");
          } finally {
            if (mountedRef.current) setSubmitting(false);
          }
        }}>
          <label>
            Email
            <input type="email" value={email} autoComplete="username" required onChange={event => setEmail(event.target.value)} />
          </label>
          <label>
            Mật khẩu
            <input type="password" value={password} autoComplete="current-password" minLength={1} required disabled={busy || submitting} onChange={event => setPassword(event.target.value)} />
          </label>
          {(submitError || error) && <p className="login-error" role="alert">{submitError || error}</p>}
          <button type="submit" disabled={busy || submitting}>{busy || submitting ? "Đang đăng nhập…" : "Đăng nhập"}</button>
        </form>
      </section>
    </Container>
  );
}
