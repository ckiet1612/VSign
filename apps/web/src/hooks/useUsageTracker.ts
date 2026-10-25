import { useCallback, useEffect, useRef } from "react";
import type { ConversationSummaryRequest } from "../../../../contracts/v1/usage";
import { UsageTracker, type UsageContext, type UsageEvent } from "../lib/usageTracker";

const CHECK_MS = 30_000;
const RETRY_MS = 15_000;
const MAX_PENDING = 20;

interface Options extends UsageContext {
  platformUrl: string;
  /** Off for the public demo and while nobody is signed in: there is no workspace to report to. */
  enabled: boolean;
}

/** Sends one summary per conversation to the usage report; summaries that fail are retried a few times. */
export function useUsageTracker({ platformUrl, enabled, channel, displayId }: Options) {
  const tracker = useRef(new UsageTracker());
  const pending = useRef<ConversationSummaryRequest[]>([]);
  const context = useRef<UsageContext>({ channel, displayId });
  context.current = { channel, displayId };
  const target = useRef({ platformUrl, enabled });
  target.current = { platformUrl, enabled };

  const send = useCallback((summary: ConversationSummaryRequest | null) => {
    if (summary) pending.current = [...pending.current, summary].slice(-MAX_PENDING);
    const { platformUrl: url, enabled: on } = target.current;
    if (!on) { pending.current = []; return; }
    for (const item of pending.current) {
      // keepalive lets the last summary leave even while the tab is closing.
      void fetch(`${url.replace(/\/$/, "")}/api/v1/workspace/usage/conversations`, {
        method: "POST", credentials: "include", keepalive: true,
        headers: { "Content-Type": "application/json" }, body: JSON.stringify(item),
      }).then(response => {
        // 4xx will not get better by retrying; only a server or network failure keeps the summary.
        if (response.ok || (response.status >= 400 && response.status < 500)) {
          pending.current = pending.current.filter(row => row.id !== item.id);
        }
      }).catch(() => undefined);
    }
  }, []);

  const note = useCallback((event: UsageEvent) => {
    if (!target.current.enabled) return;
    send(tracker.current.note(event, context.current));
  }, [send]);
  const end = useCallback(() => { send(tracker.current.end()); }, [send]);

  useEffect(() => {
    const check = window.setInterval(() => send(tracker.current.expire()), CHECK_MS);
    const retry = window.setInterval(() => { if (pending.current.length) send(null); }, RETRY_MS);
    const leave = () => send(tracker.current.end());
    window.addEventListener("pagehide", leave);
    return () => {
      window.clearInterval(check);
      window.clearInterval(retry);
      window.removeEventListener("pagehide", leave);
      leave();
    };
  }, [send]);

  // Signing out or switching workspace closes the conversation; after sign-out it can no longer be reported.
  useEffect(() => () => { send(tracker.current.end()); }, [enabled, platformUrl, send]);

  return { note, end };
}
