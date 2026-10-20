import { useCallback, useEffect, useRef, useState } from "react";
import { AutomaticSentence, type SentenceCapture, type SentenceDraft, type SentenceRequest } from "../lib/automaticSentence";

interface Options {
  enabled: boolean;
  contextKey: string;
  words: string[];
  blocked: () => boolean;
  compose: (words: string[], signal: AbortSignal) => Promise<string | { sentence: string; warnings?: string[] }>;
}

export function useAutomaticSentence(options: Options) {
  const machine = useRef(new AutomaticSentence());
  const latest = useRef(options);
  const request = useRef<{ controller: AbortController; snapshot: SentenceRequest } | null>(null);
  const requestTimeout = useRef<number | null>(null);
  const previousContext = useRef({ key: options.contextKey, enabled: options.enabled });
  const [drafts, setDrafts] = useState<SentenceDraft[]>([]);
  latest.current = options;
  const wordKey = JSON.stringify(options.words);
  const publish = useCallback(() => setDrafts(machine.current.drafts.map(item => ({ ...item, words: [...item.words] }))), []);
  const abort = useCallback(() => {
    if (requestTimeout.current !== null) window.clearTimeout(requestTimeout.current);
    requestTimeout.current = null;
    request.current?.controller.abort();
    request.current = null;
  }, []);
  const abortStale = useCallback(() => {
    if (request.current && !machine.current.valid(request.current.snapshot)) abort();
  }, [abort]);
  const activity = useCallback(() => {
    if (!latest.current.enabled) return null;
    const capture = machine.current.activity(performance.now());
    abortStale();
    publish();
    return capture;
  }, [abortStale, publish]);
  const finish = useCallback((capture: SentenceCapture, endedAt = performance.now()) => {
    if (!latest.current.enabled) return;
    machine.current.finish(capture, endedAt);
    publish();
  }, [publish]);
  const accept = useCallback((capture: SentenceCapture, words: string[]) => {
    if (!latest.current.enabled) return;
    machine.current.accept(capture, words, performance.now());
    abortStale();
    publish();
  }, [abortStale, publish]);
  const missing = useCallback((message: string, capture?: SentenceCapture) => {
    if (!latest.current.enabled) return;
    machine.current.missing(message, performance.now(), capture);
    abortStale();
    publish();
  }, [abortStale, publish]);
  const cancelPending = useCallback((message: string) => {
    if (!latest.current.enabled) return;
    machine.current.cancelPending(message, performance.now());
    abortStale();
    publish();
  }, [abortStale, publish]);
  const reset = useCallback(() => {
    abort();
    machine.current.reset();
    publish();
  }, [abort, publish]);

  useEffect(() => {
    abort();
    if (previousContext.current.key !== options.contextKey || previousContext.current.enabled !== options.enabled) {
      machine.current.contextChanged("Phiên nhận dạng thay đổi · cần kiểm tra", performance.now());
    }
    previousContext.current = { key: options.contextKey, enabled: options.enabled };
    publish();
    return abort;
  }, [abort, options.contextKey, options.enabled, publish]);
  useEffect(() => {
    if (!options.enabled) return;
    machine.current.sync(latest.current.words, performance.now());
    abortStale();
    publish();
  }, [abortStale, wordKey, options.enabled, options.contextKey, publish]);

  useEffect(() => {
    if (!options.enabled) return;
    const timer = window.setInterval(() => {
      const current = latest.current;
      if (!current.enabled || request.current) return;
      const snapshot = machine.current.prepare(performance.now(), current.blocked());
      if (!snapshot) return;
      const controller = new AbortController();
      request.current = { controller, snapshot };
      const context = current.contextKey;
      publish();
      requestTimeout.current = window.setTimeout(() => {
        if (request.current?.controller !== controller) return;
        machine.current.fail(snapshot, "Ghép câu quá thời gian · cần kiểm tra");
        abort();
        publish();
      }, 20000);
      void Promise.resolve().then(() => current.compose(snapshot.words, controller.signal)).then(composition => {
        if (request.current?.controller !== controller || controller.signal.aborted ||
          !latest.current.enabled || latest.current.contextKey !== context) return;
        machine.current.resolve(snapshot, typeof composition === "string" ? composition : composition.sentence,
          typeof composition === "string" ? [] : composition.warnings);
        publish();
      }).catch((error: unknown) => {
        if (request.current?.controller !== controller || controller.signal.aborted) return;
        machine.current.fail(snapshot, error instanceof Error ? error.message : "Không thể ghép câu");
        publish();
      }).finally(() => { if (request.current?.controller === controller) abort(); });
    }, 100);
    return () => window.clearInterval(timer);
  }, [abort, options.enabled, publish]);
  return { drafts, activity, finish, accept, missing, cancelPending, reset };
}
