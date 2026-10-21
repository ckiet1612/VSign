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
    return <main className="customer-display is-message"><p role="status">{loadError || "Đang mở màn hình quầy…"}</p></main>;
  }
  if (device.state === "unpaired") {
    return <PairingForm platformUrl={platformUrl} notice={notice} onClaimed={state => { setNotice(""); setDevice(state); }} />;
  }
  if (device.state === "awaiting_confirmation") {
    return (
      <main className="customer-display is-message" aria-labelledby="display-confirm-title">
        <div className="display-card">
          <p className="display-eyebrow">{device.workspace_name}</p>
          <h1 id="display-confirm-title">Chờ nhân viên xác nhận</h1>
          <p>Nhân viên sẽ thấy mã này trên máy của họ. Hãy kiểm tra hai mã giống nhau.</p>
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
        <p className="display-eyebrow">VSign · Màn hình khách</p>
        <h1 id="display-pair-title">Đăng ký màn hình quầy</h1>
        <p>Nhập mã 6 số nhân viên tạo trong Cài đặt → Màn hình khách. Chỉ cần làm một lần cho máy này.</p>
        {notice && <p className="display-notice" role="status">{notice}</p>}
        <label className="display-code">
          <span className="sr-only">Mã 6 số</span>
          <input inputMode="numeric" autoComplete="one-time-code" pattern="\d{6}" maxLength={6} required autoFocus
            value={code} disabled={busy} onChange={event => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
            placeholder="••••••" aria-describedby={error ? "display-pair-error" : undefined} />
        </label>
        {error && <p id="display-pair-error" className="display-error" role="alert">{error}</p>}
        <button type="submit" className="display-primary" disabled={busy || code.length !== 6}>
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

  return (
    <main className={`customer-display${serving ? " is-serving" : ""}`} aria-labelledby="display-counter-title">
      <h1 id="display-counter-title" className="sr-only">{display.name}</h1>
      <section className="display-stage" aria-label="Camera của bạn">
        <video ref={videoRef} autoPlay muted playsInline onLoadedMetadata={updateSize} onResize={updateSize}
          aria-label="Hình ảnh camera của bạn" hidden={camera.status !== "ready"} />
        {camera.status === "ready" && content.guide === "fixed" && (
          <svg className="display-guide" viewBox={`0 0 ${videoSize.width} ${videoSize.height}`} preserveAspectRatio="xMidYMid meet" aria-hidden="true">
            <rect x={square.x} y={square.y} width={square.width} height={square.height} rx={Math.min(24, square.width / 20)} />
          </svg>
        )}
        {replaced ? (
          <div className="display-overlay" role="alert">
            <strong>Màn hình quầy đang mở ở cửa sổ khác</strong>
            <button type="button" className="display-primary" onClick={() => { setReplaced(false); setSession(value => value + 1); }}>
              Dùng cửa sổ này
            </button>
          </div>
        ) : lost && !(online && staff.online) ? (
          <div className="display-overlay is-warning" role="alert">
            <strong>Mất kết nối với máy nhân viên</strong>
            <span>Đang chờ nối lại…</span>
          </div>
        ) : !online ? (
          <div className="display-overlay" role="status"><strong>Đang kết nối máy chủ…</strong></div>
        ) : !staff.online ? (
          <div className="display-overlay" role="status">
            <span className="display-eyebrow">{display.name}</span>
            <strong>Xin chào!</strong>
            <span>Nhân viên sẽ kết nối trong giây lát.</span>
          </div>
        ) : camera.status !== "ready" ? (
          <div className="display-overlay" role="status">
            <strong>{camera.status === "requesting" || camera.status === "off" ? "Đang bật camera…" : "Camera chưa sẵn sàng"}</strong>
            {camera.status !== "requesting" && camera.status !== "off" && <span>{camera.message}</span>}
          </div>
        ) : null}
        {serving && hint && camera.status === "ready" && <p className="display-hint" role="status">{hint}</p>}
      </section>
      <section className="display-captions" aria-live="polite" aria-label="Kết quả nhận dạng">
        {serving ? <>
          <p className="display-word">{content.word ?? " "}</p>
          <p className={`display-sentence${sentence ? "" : " is-empty"}`}>{sentence || "Hãy bắt đầu ký"}</p>
        </> : <p className="display-sentence is-empty">{display.name}</p>}
      </section>
    </main>
  );
}
