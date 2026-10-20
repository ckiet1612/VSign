import { useEffect, useRef, useState } from "react";
import { ArrowLeft, Camera, CameraOff, Download, Play, Plus, RefreshCw, Save, Square, Trash2, Video, X } from "../icons";
import type { CaptureDistance, CaptureLighting, CollectionHand, NegativeAction } from "@contracts";
import { config } from "../config";
import { useCamera } from "../hooks/useCamera";
import { useSignCapture } from "../hooks/useSignCapture";
import { useServerModel } from "../hooks/useServerModel";
import { ServerModelSelector } from "../components/ServerModelSelector";
import { centeredSquareRect, containedVideoRect } from "../lib/cameraGeometry";
import { chooseCapturePipeline } from "../lib/inferenceRoute";
import { outcomeText, type TestContext, type Trial } from "./types";
import { useManualTests } from "./useManualTests";
import "./dev-test.css";

const idle = "Không ký hiệu";
const actions: [NegativeAction, string][] = [["still", "Đứng yên"], ["hand_enter_exit", "Tay vào / ra"],
  ["adjust_hair_glasses", "Sửa tóc / kính"], ["touch_face", "Chạm mặt"], ["turn_body", "Quay thân"],
  ["random_motion", "Chuyển động ngẫu nhiên"], ["overlap_hands", "Chồng tay"], ["other_sign", "Ký ngoài bộ từ"]];
const percent = (value: number | null) => value === null ? "—" : `${value.toFixed(1)}%`;
const probability = (value: number | null) => percent(value === null ? null : value * 100);
const time = (value: number) => new Date(value).toLocaleString("vi-VN");

function initialSession() {
  const existing = sessionStorage.getItem("vsign-dev-test-session");
  const value = existing ?? crypto.randomUUID();
  sessionStorage.setItem("vsign-dev-test-session", value);
  return value;
}

function ClipReview({ trial, api, reviewer, onSave, onClose }: {
  trial: Trial; api: string; reviewer: string;
  onSave: (valid: boolean, notes: string, person: string) => Promise<boolean>; onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [valid, setValid] = useState(trial.review.valid);
  const [notes, setNotes] = useState(trial.review.notes);
  const [person, setPerson] = useState(reviewer);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    const element = dialog.current;
    if (element?.showModal) element.showModal();
    else if (element) element.open = true;
    return () => element?.close?.();
  }, []);
  return <dialog ref={dialog} className="dt-review" aria-label="Kiểm định clip" onCancel={event => {
    event.preventDefault(); if (!saving) onClose();
  }}>
    <div className="dt-dialog-header"><h2>Kiểm định clip</h2><button title="Đóng" aria-label="Đóng" disabled={saving} onClick={onClose}><X size={18} /></button></div>
    {trial.video_available ? <video src={`${api}/trials/${trial.trial_id}/video`} controls preload="metadata" /> : <p>Không có clip cho lỗi này.</p>}
    <p><strong>{trial.expected_label}</strong> · {outcomeText[trial.outcome]} · {trial.prediction?.label ?? "—"}</p>
    <label className="dt-check"><input type="checkbox" checked={valid} onChange={event => setValid(event.target.checked)} />Clip hợp lệ</label>
    <label>Ghi chú<textarea value={notes} maxLength={2000} onChange={event => setNotes(event.target.value)} /></label>
    <label>Người kiểm định<input value={person} maxLength={80} onChange={event => setPerson(event.target.value)} /></label>
    <div className="dt-dialog-actions"><span>{trial.review_history.length} lần kiểm định</span><button className="dt-primary" disabled={saving || !person.trim() || !valid && !notes.trim()} onClick={async () => {
      setSaving(true);
      const success = await onSave(valid, notes, person);
      setSaving(false); if (success) onClose();
    }}><Save size={16} />{saving ? "Đang lưu…" : "Lưu kiểm định"}</button></div>
  </dialog>;
}

export default function DevTestApp() {
  const serverModel = useServerModel(config.serverModels);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [session, setSession] = useState(initialSession);
  const tests = useManualTests(serverModel.active.httpUrl, session);
  const camera = useCamera(videoRef);
  const [label, setLabel] = useState("");
  const [signer, setSigner] = useState("");
  const [hand, setHand] = useState<CollectionHand>("right");
  const [distance, setDistance] = useState<CaptureDistance>("standard");
  const [lighting, setLighting] = useState<CaptureLighting>("normal");
  const [action, setAction] = useState<NegativeAction>("still");
  const [allSessions, setAllSessions] = useState(false);
  const [filter, setFilter] = useState("all");
  const [reviewing, setReviewing] = useState<Trial | null>(null);
  const [dimensions, setDimensions] = useState({ width: 1280, height: 720 });
  const snapshot = useRef<{ context: TestContext; capturedAt: number } | null>(null);
  const cancellationReason = useRef("Lượt thu đã bị hủy");
  const runtime = tests.runtime;
  const selectedLabel = runtime?.labels.includes(label) ? label : runtime?.labels[0] ?? "";
  const verified = runtime !== null && !runtime.mock && !runtime.candidate_labels_unverified;
  const pipeline = chooseCapturePipeline({ purpose: "recognize", inferenceRoute: "server" });
  const capture = useSignCapture({ videoRef, canStart: !serverModel.switching && verified && camera.status === "ready" && !tests.busy && !tests.pending && !!signer.trim(),
    captureContextKey: `${session}:${selectedLabel}:${serverModel.active.id}`, samplingStrategy: pipeline.sampling, preserveSourceFrames: true,
    onCaptureStart: () => { cancellationReason.current = "Lượt thu đã bị hủy"; snapshot.current = { context: { expected_label: selectedLabel, signer_id: signer.trim(), hand,
      distance, lighting, negative_action: selectedLabel === idle ? action : null }, capturedAt: Date.now() }; },
    onCaptureCancel: () => { const value = snapshot.current; snapshot.current = null;
      if (value) void tests.saveFailure(value.context, cancellationReason.current, value.capturedAt); },
    onTooShort: message => { const value = snapshot.current; snapshot.current = null;
      if (value) void tests.saveFailure(value.context, message, value.capturedAt); },
    onError: message => { const value = snapshot.current; snapshot.current = null;
      if (value) void tests.saveFailure(value.context, message, value.capturedAt); },
    onFrames: frames => { const value = snapshot.current; snapshot.current = null;
      if (!value) return;
      const stream = videoRef.current?.srcObject as MediaStream | null;
      if (!stream?.active || !stream.getVideoTracks().some(track => track.readyState === "live")) {
        void tests.saveFailure(value.context, "Camera bị ngắt trong lượt thu", value.capturedAt);
      } else { void tests.saveCapture(value.context, frames, value.capturedAt); }
    },
  });
  const { status: captureStatus, cancel: cancelCapture } = capture;
  useEffect(() => {
    if (captureStatus !== "idle" && camera.status !== "ready") {
      cancellationReason.current = "Camera bị ngắt trong lượt thu";
      cancelCapture();
    }
  }, [camera.status, captureStatus, cancelCapture]);
  const locked = capture.status !== "idle" || tests.busy || tests.pending !== null;
  const switchLabels = serverModel.verifiedLabels.length === 31 ? serverModel.verifiedLabels : runtime?.labels ?? [];
  const modelLocked = locked || reviewing !== null || switchLabels.length !== 31;
  const last = tests.lastTrial?.session_id === session ? tests.lastTrial : null;
  const rows = tests.trials.filter(row => (allSessions || row.session_id === session) && (filter === "all" || row.outcome === filter));
  const groups = tests.summary.groups.filter(group => allSessions || group.session_id === session);
  const guide = centeredSquareRect(containedVideoRect(1600, 900, dimensions.width, dimensions.height));

  return <div className="dev-test-shell">
    <header className="dt-header"><a href="/" title="Về nhận dạng"><ArrowLeft size={18} />VSign</a><h1>Kiểm thử thủ công</h1><strong className="dt-dev-tag">DEV</strong></header>
    {config.serverModels.length > 1 && <ServerModelSelector options={config.serverModels} value={serverModel.active.id}
      disabled={modelLocked} switching={serverModel.switching} error={serverModel.error}
      onChange={id => { if (!modelLocked) void serverModel.choose(id, switchLabels, true); }} />}
    <div className="dt-runtime"><span>{runtime?.model_version ?? "Chưa kết nối backend test"}</span>
      {runtime && <span>Confidence {probability(runtime.confidence_threshold)} · Margin {probability(runtime.margin_threshold)}</span>}
      <span className="dt-session">Phiên {session.slice(0, 8)}</span><button title="Phiên mới" aria-label="Phiên mới" disabled={locked} onClick={() => {
        const value = crypto.randomUUID(); sessionStorage.setItem("vsign-dev-test-session", value); setSession(value);
      }}><Plus size={16} /></button>
    </div>
    {runtime && !verified && <p className="dt-alert" role="alert">Model mô phỏng hoặc nhãn chưa xác minh. Test nhận dạng bị khóa.</p>}
    <main className="dt-content">
      <div className="dt-capture-layout">
        <section className="dt-camera-section" aria-label="Camera test">
          <div className="dt-camera"><video ref={videoRef} autoPlay playsInline muted onLoadedMetadata={event => {
            const video = event.currentTarget; if (video.videoWidth && video.videoHeight) setDimensions({ width: video.videoWidth, height: video.videoHeight });
          }} /><div className="dt-guide" style={{ left: `${guide.x / 16}%`, top: `${guide.y / 9}%`, width: `${guide.width / 16}%`, height: `${guide.height / 9}%` }} />
            <span className={`dt-camera-status ${capture.status === "capturing" ? "dt-recording" : ""}`}>{capture.status === "capturing" ? "Đang thu" : camera.message}</span>
          </div>
          <div className="dt-camera-actions">
            <button disabled={camera.status === "requesting" || tests.busy || capture.status === "encoding"} onClick={() => {
              if (camera.status === "ready") { capture.cancel(); camera.disable(); } else void camera.enable();
            }}>{camera.status === "ready" ? <CameraOff size={17} /> : <Camera size={17} />}{camera.status === "ready" ? "Tắt camera" : "Bật camera"}</button>
            {capture.status === "capturing" ? <button className="dt-stop" onClick={capture.stop}><Square size={17} />Kết thúc test</button>
              : <button className="dt-primary" disabled={locked || !verified || camera.status !== "ready" || !signer.trim()} onClick={capture.start}><Play size={17} />{capture.status === "encoding" ? "Đang mã hóa…" : tests.busy ? "Đang xử lý…" : "Bắt đầu test"}</button>}
          </div>
        </section>
        <section className="dt-test-settings" aria-label="Thiết lập lượt test">
          <fieldset disabled={locked}><label>Từ kỳ vọng<select value={selectedLabel} onChange={event => setLabel(event.target.value)}>{(runtime?.labels ?? []).map(word => <option key={word}>{word}</option>)}</select></label>
            <label>Người ký<input value={signer} onChange={event => setSigner(event.target.value)} maxLength={80} autoComplete="off" /></label>
            <div className="dt-field-pair"><label>Tay ký<select value={hand} onChange={event => setHand(event.target.value as CollectionHand)}><option value="right">Phải</option><option value="left">Trái</option></select></label>
              <label>Khoảng cách<select value={distance} onChange={event => setDistance(event.target.value as CaptureDistance)}><option value="standard">Tiêu chuẩn</option><option value="near">Gần</option><option value="far">Xa</option></select></label></div>
            <label>Ánh sáng<select value={lighting} onChange={event => setLighting(event.target.value as CaptureLighting)}><option value="normal">Bình thường</option><option value="low">Yếu</option><option value="side">Chiếu bên</option></select></label>
            {selectedLabel === idle && <label>Chuyển động nền<select value={action} onChange={event => setAction(event.target.value as NegativeAction)}>{actions.map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select></label>}
          </fieldset>
          <div className="dt-last-result" aria-live="polite">{last ? <><strong className={`dt-outcome dt-${last.outcome}`}>{outcomeText[last.outcome]}</strong><dl>
            <div><dt>Kỳ vọng</dt><dd>{last.expected_label}</dd></div><div><dt>Nhận dạng</dt><dd>{last.prediction?.label ?? "—"}</dd></div>
            <div><dt>Confidence</dt><dd>{probability(last.prediction?.confidence ?? null)}</dd></div><div><dt>Model + xử lý</dt><dd>{last.inference_ms === null ? "—" : `${Math.round(last.inference_ms)} ms`}</dd></div>
          </dl></> : <span>Chưa có kết quả trong phiên</span>}</div>
        </section>
      </div>
      {(tests.notice || tests.pending) && <div className="dt-notice" role="status"><span>{tests.notice}</span>{tests.pending && <button disabled={tests.busy} onClick={() => void tests.retry()}><RefreshCw size={16} />Thử lưu lại</button>}{tests.rejected && <button disabled={tests.busy} onClick={tests.discardRejected}><Trash2 size={16} />Bỏ lượt bị từ chối</button>}</div>}
      <div className="dt-section-toolbar"><h2>Kết quả</h2><label className="dt-check"><input type="checkbox" checked={allSessions} onChange={event => setAllSessions(event.target.checked)} />Tất cả phiên</label>
        <button title="Tải lại kết quả" aria-label="Tải lại kết quả" disabled={capture.status !== "idle" || tests.busy} onClick={() => void tests.reload()}><RefreshCw size={16} /></button>
        <a href={`${tests.api}/export?format=csv${allSessions ? "" : `&session_id=${session}`}`} download><Download size={16} />CSV</a>
        <a href={`${tests.api}/export?format=json${allSessions ? "" : `&session_id=${session}`}`} download><Download size={16} />JSON</a>
      </div>
      <section aria-label="Thống kê từng từ">{groups.length === 0 ? <p className="dt-empty">Chưa có lượt test được lưu trong phạm vi này.</p> : groups.map(group => <div className="dt-group" key={`${group.runtime_key}:${group.session_id}`}>
        <div className="dt-group-title"><strong>{group.model_version}</strong><span>Phiên {group.session_id.slice(0, 8)} · {probability(group.confidence_threshold)} / {probability(group.margin_threshold)}</span></div>
        <div className="dt-metrics"><span>Đúng <strong>{percent(group.positive.correct_pct)}</strong></span><span>Nhầm <strong>{percent(group.positive.wrong_pct)}</strong></span><span>Không xác định <strong>{percent(group.positive.uncertain_pct)}</strong></span><span>Nền chấp nhận sai <strong>{percent(group.negative.false_accept_pct)}</strong></span></div>
        <div className="dt-table-scroll"><table><thead><tr><th>Từ</th><th>Đã ghi</th><th>Loại</th><th>Lỗi kỹ thuật</th><th>Đã đánh giá</th><th>Đúng %</th><th>Nhầm %</th><th>Không xác định %</th><th>Nhầm thành</th></tr></thead><tbody>{group.per_word.map(word => <tr key={word.label}><th>{word.label}</th><td>{word.recorded}</td><td>{word.excluded}</td><td>{word.technical_error}</td><td>{word.evaluated}</td><td>{percent(word.label === idle ? word.correct_rejection_pct : word.correct_pct)}</td><td>{percent(word.label === idle ? word.false_accept_pct : word.wrong_pct)}</td><td>{word.label === idle ? "—" : percent(word.uncertain_pct)}</td><td>{Object.entries(word.wrong_labels).map(([value, count]) => `${value}: ${count}`).join(", ") || "—"}</td></tr>)}</tbody></table></div>
      </div>)}</section>
      <section aria-label="Lịch sử test"><div className="dt-section-toolbar"><h2>Lịch sử test</h2><label>Kết quả<select value={filter} onChange={event => setFilter(event.target.value)}><option value="all">Tất cả</option>{Object.entries(outcomeText).map(([value, text]) => <option value={value} key={value}>{text}</option>)}</select></label><span>{rows.length} lượt</span></div>
        <div className="dt-table-scroll"><table><thead><tr><th>Thời điểm</th><th>Người ký</th><th>Kỳ vọng</th><th>Nhận dạng</th><th>Kết quả</th><th>Clip</th><th>Kiểm định</th></tr></thead><tbody>{rows.map(row => <tr key={row.trial_id}>
          <td>{time(row.captured_at)}</td><td>{row.signer_id}</td><th>{row.expected_label}</th><td>{row.prediction?.label ?? "—"}</td><td><span className={`dt-outcome dt-${row.outcome}`}>{outcomeText[row.outcome]}</span></td>
          <td><button title="Xem clip" aria-label="Xem clip" onClick={() => setReviewing(row)}><Video size={17} /></button></td><td>{row.review.valid ? row.review.reviewer ? "Đã kiểm định" : "Chưa kiểm định" : "Loại khỏi thống kê"}</td>
        </tr>)}</tbody></table></div>
      </section>
    </main>
    {reviewing && <ClipReview trial={reviewing} api={tests.api} reviewer={signer} onClose={() => setReviewing(null)} onSave={(valid, notes, person) => tests.review(reviewing.trial_id, valid, notes, person)} />}
  </div>;
}
