import { useCallback, useEffect, useRef, useState, type FormEvent, type SyntheticEvent } from "react";
import {
  DISPLAY_CLOSE,
  type DeviceState,
  type DisplayStateMessage,
  type ServerDisplayMessage,
} from "../../../../contracts/v1/display";
import { useCamera } from "../hooks/useCamera";
import { displaySocketUrl, useDisplayChannel } from "../hooks/useDisplayChannel";
import { useDisplaySender } from "../hooks/useDisplayPeer";
import { centeredSquareRect } from "../lib/cameraGeometry";
import { TriangleAlert, UsersRound, Video } from "../icons";
import { WorkspaceApiError, workspaceRequest } from "../lib/workspaceApi";
import "./display.css";

const POLL_MS = 2000;
// After an unexpected drop the camera stays on this long, so a brief network blip does not restart everything.
const RECONNECT_GRACE_MS = 30000;

const phaseHint: Partial<Record<DisplayStateMessage["phase"], string>> = {
  capturing: "Đang ghi nhận ký hiệu…",
  processing: "Đang nhận dạng…",
  uncertain: "Chưa rõ. Hãy ký lại chậm hơn.",
  no_hands: "Hãy đưa hai tay vào khung.",
  bad_framing: "Hãy ngồi vào giữa khung hình.",
  error: "Chưa nhận được. Hãy ký lại.",
};

const unpairedText: Record<string, string> = {
  revoked: "Màn hình này đã bị huỷ. Nhập mã mới để đăng ký lại.",
  rejected: "Nhân viên đã từ chối kết nối. Hãy nhập mã mới.",
  expired: "Mã đã hết hạn. Hãy xin nhân viên mã mới.",
};

type Content = Pick<DisplayStateMessage, "word" | "words" | "sentence" | "phase" | "guide">;
const EMPTY: Content = { word: null, words: [], sentence: "", phase: "ready", guide: "fixed" };

const MARK = `${import.meta.env.BASE_URL}brand/vsign-mark.svg`;

function Brand() {
  return <span className="display-brand"><img src={MARK} alt="" width="28" height="28" draggable={false} />VSign</span>;
}

function readLinkToken(): string | null {
  const token = new URLSearchParams(window.location.hash.slice(1)).get("token");
  return token && /^[A-Za-z0-9_-]{43}$/.test(token) ? token : null;
}

/** The customer-facing counter screen: pairing once, then the customer's camera and the recognized words. */
export function CustomerDisplay({ platformUrl }: { platformUrl: string }) {
  const [device, setDevice] = useState<DeviceState | null>(null);
  const [loadError, setLoadError] = useState("");
  const [notice, setNotice] = useState("");
  const [attempt, setAttempt] = useState(0);

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const { body } = await workspaceRequest<DeviceState>(platformUrl, "/api/v1/displays/me", { cache: "no-store" }, signal);
      if (!body) throw new Error("empty");
      setDevice(body);
      setLoadError("");
      if (body.state === "unpaired" && body.reason) setNotice(unpairedText[body.reason] ?? "");
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) setLoadError("Chưa kết nối được máy chủ. Đang thử lại…");
    }
  }, [platformUrl]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load, attempt]);

  // Waiting for staff to confirm, or for the server to come back: poll quietly.
  useEffect(() => {
    if (device?.state !== "awaiting_confirmation" && !loadError) return;
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [device?.state, loadError, load]);

  // The server refused this screen: ask it again what this device is (revoked, or still paired after a blip).
  const unpair = useCallback((message: string) => {
    setNotice(message);
    window.setTimeout(() => setAttempt(value => value + 1), 1000);
  }, []);

  if (!device) {
    return <main className="customer-display is-message">
      <div className="display-card is-quiet"><Brand /><p role="status">{loadError || "Đang mở màn hình quầy…"}</p></div>
    </main>;
  }
  if (device.state === "unpaired") {
    return <PairingForm platformUrl={platformUrl} notice={notice} onClaimed={state => { setNotice(""); setDevice(state); }} />;
  }
  if (device.state === "awaiting_confirmation") {
    return (
      <main className="customer-display is-message" aria-labelledby="display-confirm-title">
        <div className="display-card">
          <Brand />
          <p className="display-eyebrow">{device.workspace_name} · Bước 3/3</p>
          <h1 id="display-confirm-title">Chờ nhân viên xác nhận</h1>
          <p>Máy nhân viên đang hiện mã đối chiếu. Hai mã giống nhau thì nhân viên sẽ xác nhận.</p>
          <strong className="display-verification" aria-label={`Mã đối chiếu ${device.verification.split("").join(" ")}`}>{device.verification}</strong>
          <p className="display-muted">Đăng ký thành “{device.name}”</p>
        </div>
      </main>
    );
  }
  return <CounterScreen key={attempt} platformUrl={platformUrl} display={device.display} onUnpaired={unpair} />;
}

function PairingForm({ platformUrl, notice, onClaimed }: {
  platformUrl: string; notice: string; onClaimed: (state: DeviceState) => void;
}) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const linkToken = useRef(readLinkToken());

  const claim = useCallback(async (secret: { code: string } | { link_token: string }) => {
    setBusy(true);
    setError("");
    try {
      const { body } = await workspaceRequest<DeviceState>(platformUrl, "/api/v1/displays/claim", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(secret),
      });
      if (body) onClaimed(body);
    } catch (cause) {
      setError(cause instanceof WorkspaceApiError ? cause.message : "Chưa gửi được mã. Hãy thử lại.");
    } finally {
      setBusy(false);
    }
  }, [onClaimed, platformUrl]);

  // A QR link carries its secret in the fragment; it is used once and removed from the address bar.
  useEffect(() => {
    const token = linkToken.current;
    if (!token) return;
    linkToken.current = null;
    window.history.replaceState(window.history.state, "", window.location.pathname + window.location.search);
    void claim({ link_token: token });
  }, [claim]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (/^\d{6}$/.test(code) && !busy) void claim({ code });
  };

  return (
    <main className="customer-display is-message" aria-labelledby="display-pair-title">
      <form className="display-card" onSubmit={submit}>
        <Brand />
        <p className="display-eyebrow">Màn hình khách · Bước 2/3</p>
        <h1 id="display-pair-title">Đăng ký màn hình quầy</h1>
        <p>Nhập mã 6 số nhân viên vừa tạo trong Cài đặt → Màn hình khách. Chỉ cần làm một lần cho máy này.</p>
        {notice && <p className="display-notice" role="status">{notice}</p>}
        <label className="display-code">
          <span className="sr-only">Mã 6 số</span>
          <input inputMode="numeric" autoComplete="one-time-code" pattern="\d{6}" maxLength={6} required autoFocus
            value={code} disabled={busy} onChange={event => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
            placeholder="••••••" aria-describedby={error ? "display-pair-error" : undefined} />
        </label>
        {error && <p id="display-pair-error" className="display-error" role="alert">{error}</p>}
        <button type="submit" className="display-primary is-block" disabled={busy || code.length !== 6}>
          {busy ? "Đang gửi…" : "Đăng ký"}
        </button>
      </form>
    </main>
  );
}

function CounterScreen({ platformUrl, display, onUnpaired }: {
  platformUrl: string; display: { id: string; name: string }; onUnpaired: (message: string) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const camera = useCamera(videoRef);
  const [staff, setStaff] = useState<{ online: boolean; name: string | null }>({ online: false, name: null });
  const [lost, setLost] = useState(false);
  const [replaced, setReplaced] = useState(false);
  const [content, setContent] = useState<Content>(EMPTY);
  const [iceServers, setIceServers] = useState<RTCIceServer[]>([]);
  const [videoSize, setVideoSize] = useState({ width: 1280, height: 720 });
  const conversation = useRef("");
  const revision = useRef(-1);
  const signalRef = useRef<(message: Extract<ServerDisplayMessage, { type: "signal" }>) => void>(() => undefined);

  const onMessage = useCallback((message: ServerDisplayMessage) => {
    switch (message.type) {
      case "welcome":
        setIceServers(message.ice_servers);
        break;
      case "peer":
        if (message.role !== "staff") break;
        setStaff({ online: message.online, name: message.name });
        if (message.online) setLost(false);
        else {
          // Nothing on screen may outlive the staff connection: the next customer must not see this one's words.
          setContent(EMPTY);
          setLost(current => current || camera.status === "ready");
        }
        break;
      case "display_state":
        if (message.conversation_id !== conversation.current) { conversation.current = message.conversation_id; revision.current = -1; }
        if (message.revision <= revision.current) break;
        revision.current = message.revision;
        setContent({ word: message.word, words: message.words, sentence: message.sentence, phase: message.phase, guide: message.guide });
        break;
      case "command":
        setContent(EMPTY);
        conversation.current = message.conversation_id;
        revision.current = -1;
        if (message.name === "end_session") { setLost(false); setStaff({ online: false, name: null }); }
        break;
      case "signal":
        signalRef.current(message);
        break;
      default:
        break;
    }
  }, [camera.status]);

  const onEnded = useCallback((code: number) => {
    setContent(EMPTY);
    if (code === DISPLAY_CLOSE.revoked || code === 1008) onUnpaired(unpairedText.revoked);
    else if (code === DISPLAY_CLOSE.replaced) setReplaced(true);
  }, [onUnpaired]);

  const [session, setSession] = useState(0);
  const channel = useDisplayChannel({
    url: replaced ? null : `${displaySocketUrl(platformUrl, display.id, "device")}${session ? `&s=${session}` : ""}`,
    onMessage, onEnded,
  });
  const online = channel.status === "open";
  // Whether the previous render was serving; read by the effect below before this render's value is stored.
  const servingRef = useRef(false);
  useEffect(() => {
    if (online) return;
    // Our own connection dropped mid-service: same as staff dropping, wait a little before giving up.
    if (servingRef.current) setLost(true);
    setStaff({ online: false, name: null });
    setContent(EMPTY);
  }, [online]);
  useEffect(() => { servingRef.current = online && staff.online; });

  // The camera runs only while someone is serving, plus a short grace period after an unexpected drop.
  const wantCamera = online && staff.online || lost;
  const { enable, disable } = camera;
  useEffect(() => {
    if (wantCamera) void enable();
    else disable();
  }, [wantCamera, enable, disable]);
  useEffect(() => {
    if (!lost) return;
    const timer = window.setTimeout(() => setLost(false), RECONNECT_GRACE_MS);
    return () => window.clearTimeout(timer);
  }, [lost]);

  const stream = camera.status === "ready" ? videoRef.current?.srcObject as MediaStream | null ?? null : null;
  const sender = useDisplaySender({ stream, staffOnline: online && staff.online, iceServers, send: channel.send });
  signalRef.current = sender.handleSignal;

  const updateSize = (event: SyntheticEvent<HTMLVideoElement>) => {
    const { videoWidth: width, videoHeight: height } = event.currentTarget;
    if (width && height) setVideoSize(current => current.width === width && current.height === height ? current : { width, height });
  };
  const square = centeredSquareRect({ x: 0, y: 0, ...videoSize });
  const serving = online && staff.online;
  const sentence = content.sentence || content.words.join(" ");
  const hint = phaseHint[content.phase];

  const lostNow = lost && !serving;
  const status = replaced ? { text: "Đang mở ở cửa sổ khác", tone: "off" }
    : lostNow ? { text: "Mất kết nối", tone: "off" }
    : !online ? { text: "Đang kết nối…", tone: "wait" }
    : serving ? { text: staff.name ? `Nhân viên ${staff.name}` : "Đang phục vụ", tone: "ok" }
    : { text: "Chờ nhân viên", tone: "wait" };

  return (
    <main className={`customer-display is-counter${serving ? " is-serving" : ""}`} aria-labelledby="display-counter-title">
      <header className="display-topbar">
        <Brand />
        <h1 id="display-counter-title">{display.name}</h1>
        <span className={`display-status tone-${status.tone}`}><i aria-hidden="true" />{status.text}</span>
      </header>
      <div className={`display-body${serving ? "" : " is-idle"}`}>
        <section className={`display-stage${camera.status === "ready" ? " is-live" : ""}`} aria-label="Camera của bạn">
          <video ref={videoRef} autoPlay muted playsInline onLoadedMetadata={updateSize} onResize={updateSize}
            aria-label="Hình ảnh camera của bạn" hidden={camera.status !== "ready"} />
          {camera.status === "ready" && content.guide === "fixed" && (
            <svg className="display-guide" viewBox={`0 0 ${videoSize.width} ${videoSize.height}`} preserveAspectRatio="xMidYMid meet" aria-hidden="true">
              <rect x={square.x} y={square.y} width={square.width} height={square.height} rx={Math.min(24, square.width / 20)} />
            </svg>
          )}
          {replaced ? (
            <div className="display-overlay" role="alert">
              <div className="display-overlay-card">
                <span className="display-overlay-icon" aria-hidden="true"><Video size={28} /></span>
                <strong>Màn hình quầy đang mở ở cửa sổ khác</strong>
                <button type="button" className="display-primary" onClick={() => { setReplaced(false); setSession(value => value + 1); }}>
                  Dùng cửa sổ này
                </button>
              </div>
            </div>
          ) : lostNow ? (
            <div className="display-overlay is-warning" role="alert">
              <div className="display-overlay-card">
                <span className="display-overlay-icon" aria-hidden="true"><TriangleAlert size={28} /></span>
                <strong>Mất kết nối với máy nhân viên</strong>
                <span>Đang chờ nối lại…</span>
              </div>
            </div>
          ) : !online ? (
            <div className="display-overlay" role="status">
              <div className="display-overlay-card"><span className="display-spinner" aria-hidden="true" /><strong>Đang kết nối máy chủ…</strong></div>
            </div>
          ) : !staff.online ? (
            <div className="display-overlay is-welcome" role="status">
              <div className="display-overlay-card">
                <span className="display-overlay-icon" aria-hidden="true"><UsersRound size={36} /></span>
                <strong>Xin chào!</strong>
                <span>Nhân viên sẽ kết nối trong giây lát.</span>
              </div>
            </div>
          ) : camera.status !== "ready" ? (
            <div className="display-overlay" role="status">
              <div className="display-overlay-card">
                {camera.status === "requesting" || camera.status === "off" ? <span className="display-spinner" aria-hidden="true" />
                  : <span className="display-overlay-icon" aria-hidden="true"><TriangleAlert size={28} /></span>}
                <strong>{camera.status === "requesting" || camera.status === "off" ? "Đang bật camera…" : "Camera chưa sẵn sàng"}</strong>
                {camera.status !== "requesting" && camera.status !== "off" && <span>{camera.message}</span>}
              </div>
            </div>
          ) : null}
          {serving && hint && camera.status === "ready" && <p className="display-hint" role="status">{hint}</p>}
        </section>
        {/* Nothing to read while nobody serves: the welcome takes the whole screen. */}
        {serving && <section className="display-captions" aria-live="polite" aria-label="Kết quả nhận dạng">
          <div className="display-caption">
            <span className="display-caption-label">Từ vừa nhận</span>
            <p className="display-word">{content.word ?? " "}</p>
          </div>
          <div className="display-caption is-sentence">
            <span className="display-caption-label">Câu</span>
            <p className={`display-sentence${sentence ? "" : " is-empty"}`}>{sentence || "Hãy bắt đầu ký"}</p>
          </div>
        </section>}
      </div>
    </main>
  );
}
