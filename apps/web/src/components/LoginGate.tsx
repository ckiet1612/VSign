import { useEffect, useRef, useState } from "react";

interface LoginGateProps {
  workspaceName: string;
  busy?: boolean;
  error?: string;
  embedded?: boolean;
  onLogin: (email: string, password: string) => Promise<void>;
}

export function LoginGate({ workspaceName, busy = false, error = "", embedded = false, onLogin }: LoginGateProps) {
  const [username, setUsername] = useState("");
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
        <img className="login-mark" src={`${import.meta.env.BASE_URL}brand/vsign-mark.svg`} alt="" width="40" height="40" />
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
            if (mountedRef.current) setSubmitError(loginError instanceof Error ? loginError.message : "Không thể đăng nhập");
          } finally {
            if (mountedRef.current) setSubmitting(false);
          }
        }}>
          <label>
            Tên đăng nhập
            <input type="text" value={username} autoComplete="username" autoCapitalize="none" spellCheck={false} maxLength={320} required disabled={busy || submitting} onChange={event => setUsername(event.target.value)} />
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
