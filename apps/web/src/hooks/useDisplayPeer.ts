import { useCallback, useEffect, useRef, useState } from "react";
import type { SignalMessage } from "../../../../contracts/v1/display";

/*
 * Peer-to-peer video from the counter display (sender, offerer) to the staff recognizer (receiver).
 * Each negotiation has its own session id, so answers and candidates from an older attempt are ignored.
 */

export type PeerState = "idle" | "connecting" | "connected" | "failed";

// Recognition reads fine detail of hands and face: keep resolution, give the encoder room on a local network.
const MAX_BITRATE = 4_000_000;
const RETRY_MS = 1500;

interface Negotiation {
  pc: RTCPeerConnection;
  session: string;
  remoteSet: boolean;
  pending: RTCIceCandidateInit[];
}

function sessionId(): string {
  return globalThis.crypto?.randomUUID?.().replace(/-/g, "") ?? Math.random().toString(36).slice(2);
}

function candidatePayload(candidate: RTCIceCandidate): SignalMessage["candidate"] {
  return { candidate: candidate.candidate, sdpMid: candidate.sdpMid, sdpMLineIndex: candidate.sdpMLineIndex };
}

function peerState(pc: RTCPeerConnection): PeerState {
  const state = pc.connectionState;
  return state === "connected" ? "connected" : state === "failed" || state === "closed" ? "failed" : "connecting";
}

async function acceptCandidate(entry: Negotiation, candidate: RTCIceCandidateInit) {
  if (!entry.remoteSet) { entry.pending.push(candidate); return; }
  await entry.pc.addIceCandidate(candidate).catch(() => undefined);
}

async function flushCandidates(entry: Negotiation) {
  entry.remoteSet = true;
  const pending = entry.pending.splice(0);
  for (const candidate of pending) await entry.pc.addIceCandidate(candidate).catch(() => undefined);
}

function close(entry: Negotiation | null) {
  if (!entry) return;
  entry.pc.onicecandidate = entry.pc.onconnectionstatechange = entry.pc.ontrack = null;
  entry.pc.close();
}

interface SenderOptions {
  stream: MediaStream | null;
  /** Staff is on the other end of the channel; without them there is no one to send video to. */
  staffOnline: boolean;
  iceServers: RTCIceServer[];
  send: (message: SignalMessage) => boolean;
}

export function useDisplaySender({ stream, staffOnline, iceServers, send }: SenderOptions) {
  const [state, setState] = useState<PeerState>("idle");
  const current = useRef<Negotiation | null>(null);
  const latest = useRef({ stream, staffOnline, iceServers, send });
  latest.current = { stream, staffOnline, iceServers, send };
  const retry = useRef(0);

  const teardown = useCallback(() => {
    window.clearTimeout(retry.current);
    close(current.current);
    current.current = null;
    setState("idle");
  }, []);

  const negotiate = useCallback(async () => {
    teardown();
    const { stream, staffOnline, iceServers, send } = latest.current;
    const track = stream?.getVideoTracks()[0];
    if (!stream || !track || !staffOnline || typeof RTCPeerConnection === "undefined") return;
    const entry: Negotiation = { pc: new RTCPeerConnection({ iceServers }), session: sessionId(), remoteSet: false, pending: [] };
    current.current = entry;
    setState("connecting");
    const sender = entry.pc.addTrack(track, stream);
    entry.pc.onicecandidate = event => {
      if (event.candidate?.candidate && current.current === entry) {
        latest.current.send({ type: "signal", session: entry.session, kind: "candidate", candidate: candidatePayload(event.candidate) });
      }
    };
    entry.pc.onconnectionstatechange = () => {
      if (current.current !== entry) return;
      const next = peerState(entry.pc);
      setState(next);
      if (next === "failed") retry.current = window.setTimeout(() => void negotiate(), RETRY_MS);
    };
    try {
      const offer = await entry.pc.createOffer();
      if (current.current !== entry) return;
      await entry.pc.setLocalDescription(offer);
      if (current.current !== entry) return;
      send({ type: "signal", session: entry.session, kind: "offer", sdp: entry.pc.localDescription?.sdp ?? offer.sdp ?? "" });
      const parameters = sender.getParameters();
      if (!parameters.encodings?.length) parameters.encodings = [{}];
      parameters.encodings[0].maxBitrate = MAX_BITRATE;
      (parameters as RTCRtpSendParameters & { degradationPreference?: string }).degradationPreference = "maintain-resolution";
      await sender.setParameters(parameters).catch(() => undefined);
    } catch {
      if (current.current === entry) { setState("failed"); retry.current = window.setTimeout(() => void negotiate(), RETRY_MS); }
    }
  }, [teardown]);

  // A new staff member, a new camera stream or new ICE servers all mean a fresh offer.
  useEffect(() => {
    if (stream && staffOnline) void negotiate();
    else teardown();
  }, [stream, staffOnline, iceServers, negotiate, teardown]);
  useEffect(() => teardown, [teardown]);

  const handleSignal = useCallback((message: SignalMessage) => {
    if (message.kind === "request_offer") { void negotiate(); return; }
    const entry = current.current;
    if (!entry || message.session !== entry.session) return;
    if (message.kind === "answer" && message.sdp && !entry.remoteSet) {
      void entry.pc.setRemoteDescription({ type: "answer", sdp: message.sdp })
        .then(() => flushCandidates(entry))
        .catch(() => { if (current.current === entry) void negotiate(); });
    } else if (message.kind === "candidate" && message.candidate) {
      void acceptCandidate(entry, message.candidate);
    }
  }, [negotiate]);

  return { state, handleSignal };
}

interface ReceiverOptions {
  /** Connected to a counter; when false, any video is dropped. */
  active: boolean;
  iceServers: RTCIceServer[];
  send: (message: SignalMessage) => boolean;
}

export function useDisplayReceiver({ active, iceServers, send }: ReceiverOptions) {
  const [state, setState] = useState<PeerState>("idle");
  const [stream, setStream] = useState<MediaStream | null>(null);
  const current = useRef<Negotiation | null>(null);
  const latest = useRef({ active, iceServers, send });
  latest.current = { active, iceServers, send };
  const retry = useRef(0);

  const teardown = useCallback(() => {
    window.clearTimeout(retry.current);
    close(current.current);
    current.current = null;
    setStream(null);
    setState("idle");
  }, []);

  const requestOffer = useCallback(() => {
    window.clearTimeout(retry.current);
    if (latest.current.active) latest.current.send({ type: "signal", session: sessionId(), kind: "request_offer" });
  }, []);

  useEffect(() => { if (!active) teardown(); }, [active, teardown]);
  useEffect(() => teardown, [teardown]);

  const handleSignal = useCallback((message: SignalMessage) => {
    if (!latest.current.active) return;
    if (message.kind === "offer" && message.sdp) {
      close(current.current);
      const entry: Negotiation = { pc: new RTCPeerConnection({ iceServers: latest.current.iceServers }),
        session: message.session, remoteSet: false, pending: [] };
      current.current = entry;
      setStream(null);
      setState("connecting");
      entry.pc.ontrack = event => {
        if (current.current === entry) setStream(event.streams[0] ?? new MediaStream([event.track]));
      };
      entry.pc.onicecandidate = event => {
        if (event.candidate?.candidate && current.current === entry) {
          latest.current.send({ type: "signal", session: entry.session, kind: "candidate", candidate: candidatePayload(event.candidate) });
        }
      };
      entry.pc.onconnectionstatechange = () => {
        if (current.current !== entry) return;
        const next = peerState(entry.pc);
        setState(next);
        // The counter re-offers on request; a frozen picture must never pass for live video meanwhile.
        if (next === "failed") { setStream(null); retry.current = window.setTimeout(requestOffer, RETRY_MS); }
      };
      void (async () => {
        try {
          await entry.pc.setRemoteDescription({ type: "offer", sdp: message.sdp });
          await flushCandidates(entry);
          const answer = await entry.pc.createAnswer();
          if (current.current !== entry) return;
          await entry.pc.setLocalDescription(answer);
          if (current.current !== entry) return;
          latest.current.send({ type: "signal", session: entry.session, kind: "answer", sdp: entry.pc.localDescription?.sdp ?? answer.sdp ?? "" });
        } catch {
          if (current.current === entry) { setState("failed"); retry.current = window.setTimeout(requestOffer, RETRY_MS); }
        }
      })();
      return;
    }
    const entry = current.current;
    if (entry && message.kind === "candidate" && message.candidate && message.session === entry.session) {
      void acceptCandidate(entry, message.candidate);
    }
  }, [requestOffer]);

  return { state, stream, handleSignal, requestOffer, reset: teardown };
}
