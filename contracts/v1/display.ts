// Counter displays: see contracts/v1/display.py for the server side of every message.

export type DisplayPhase =
  | "ready" | "capturing" | "processing" | "ok" | "uncertain" | "no_hands" | "bad_framing"
  | "busy" | "error" | "disconnected";

export interface CounterDisplay {
  id: string; name: string; online: boolean; staff: string | null;
  last_seen_at: string | null; created_at: string;
}
export interface DisplayEnrollmentRow {
  id: string; name: string; status: "pending" | "awaiting_confirmation";
  expires_at: string; verification: string | null;
}
export interface DisplayOverview {
  api_version: "1"; workspace_id: string; permissions: { manage: boolean };
  displays: CounterDisplay[]; enrollments: DisplayEnrollmentRow[];
}
export interface CreatedEnrollment { id: string; name: string; code: string; link_token: string; expires_at: string }

export type DeviceState =
  | { api_version: "1"; state: "paired"; workspace_name: string; display: { id: string; name: string } }
  | { api_version: "1"; state: "awaiting_confirmation"; workspace_name: string; name: string; verification: string; expires_at: string }
  | { api_version: "1"; state: "unpaired"; reason: "revoked" | "rejected" | "expired" | null };

export interface IceCandidatePayload { candidate: string; sdpMid?: string | null; sdpMLineIndex?: number | null }
export interface SignalMessage {
  type: "signal"; session: string; kind: "offer" | "answer" | "candidate" | "request_offer";
  sdp?: string; candidate?: IceCandidatePayload;
}
export interface DisplayStateMessage {
  type: "display_state"; conversation_id: string; revision: number; phase: DisplayPhase;
  word: string | null; words: string[]; sentence: string; guide: "fixed" | "adaptive";
  /** The staff member's latest answer to the customer; empty until they reply. */
  reply?: string;
}
export const REPLY_MAX = 300;
/** A button pressed on the counter screen; the staff recognizer owns the transcript and applies it. */
export interface CustomerActionMessage { type: "customer_action"; action: "undo_word"; conversation_id: string }
export interface CommandMessage { type: "command"; name: "new_conversation" | "end_session"; conversation_id: string }

export type ServerDisplayMessage =
  | { type: "welcome"; role: "staff" | "device"; display: { id: string; name: string }; ice_servers: RTCIceServer[] }
  | { type: "peer"; role: "staff"; online: boolean; name: string | null }
  | { type: "peer"; role: "device"; online: boolean }
  | { type: "occupied"; staff_name: string }
  | { type: "taken_over"; by: string }
  | { type: "revoked" }
  | { type: "pong" }
  | { type: "error"; detail: string }
  | SignalMessage | DisplayStateMessage | CommandMessage | CustomerActionMessage;

export type ClientDisplayMessage = SignalMessage | DisplayStateMessage | CommandMessage | CustomerActionMessage | { type: "ping" };

/** Close codes the server uses on /ws/display; reconnecting after these would only repeat the refusal. */
export const DISPLAY_CLOSE = {
  replaced: 4001, revoked: 4003, occupied: 4009, takenOver: 4010, ended: 4011,
} as const;

const SERVER_TYPES = new Set(["welcome", "peer", "occupied", "taken_over", "revoked", "pong", "error",
  "signal", "display_state", "command", "customer_action"]);

export function parseServerDisplayMessage(raw: unknown): ServerDisplayMessage | null {
  if (typeof raw !== "string") return null;
  try {
    const value: unknown = JSON.parse(raw);
    return value && typeof value === "object" && "type" in value && SERVER_TYPES.has(String(value.type))
      ? value as ServerDisplayMessage : null;
  } catch {
    return null;
  }
}
