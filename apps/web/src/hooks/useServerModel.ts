import { useCallback, useEffect, useRef, useState } from "react";
import type { InferenceMetadata } from "@contracts";

export interface ServerModelOption {
  id: "current" | "seated";
  label: string;
  httpUrl: string;
  wsUrl: string;
}

function verifiedMetadata(value: unknown, option: ServerModelOption, labels: readonly string[]): InferenceMetadata {
  const body = value as Partial<InferenceMetadata> | null;
  if (!body || body.mock !== false || body.candidate_labels_unverified !== false ||
      body.protocol_version !== "1.0" || body.frame_count !== 16 || body.frame_width !== 224 || body.frame_height !== 224 ||
      body.confidence_threshold !== .7 || body.margin_threshold !== .15 ||
      !Array.isArray(body.labels) || labels.length !== 31 || labels[30] !== "Không ký hiệu" ||
      body.labels.length !== labels.length || body.labels.some((label, index) => label !== labels[index]) ||
      typeof body.model_version !== "string" ||
      (option.id === "seated" && !/^sales30-mvitv2s-seated-personal-v1-head-epoch\d+$/.test(body.model_version))) {
    throw new Error("Model, nhãn hoặc ngưỡng nhận dạng chưa khớp bản đã xác minh.");
  }
  return body as InferenceMetadata;
}

export function useServerModel(options: readonly ServerModelOption[]) {
  const [active, setActive] = useState(options[0]);
  const [switching, setSwitching] = useState(false);
  const [error, setError] = useState("");
  const [verifiedLabels, setVerifiedLabels] = useState<string[]>([]);
  const request = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; request.current?.abort(); };
  }, []);
  const choose = useCallback(async (id: string, labels: readonly string[], devTests = false): Promise<InferenceMetadata | null> => {
    const option = options.find(item => item.id === id);
    if (!option || option.id === active.id || request.current) return null;
    const controller = new AbortController();
    request.current = controller;
    const timer = window.setTimeout(() => controller.abort(), 5000);
    setSwitching(true); setError("");
    try {
      const response = await fetch(`${option.httpUrl}/metadata`, { signal: controller.signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const metadata = verifiedMetadata(await response.json(), option, labels);
      if (import.meta.env.DEV && devTests) {
        const response = await fetch(`${option.httpUrl}/dev-tests/config`, { signal: controller.signal });
        if (!response.ok) throw new Error("Backend chưa bật chế độ test.");
        const runtime = await response.json();
        if (runtime.enabled !== true || runtime.model_version !== metadata.model_version ||
            typeof runtime.runtime_key !== "string" || !runtime.runtime_key ||
            !Array.isArray(runtime.labels) || JSON.stringify(runtime.labels) !== JSON.stringify(metadata.labels)) {
          throw new Error("Cấu hình test không khớp model nhận dạng.");
        }
      }
      if (!mounted.current || controller.signal.aborted) return null;
      setVerifiedLabels([...metadata.labels]);
      setActive(option);
      return metadata;
    } catch (cause) {
      if (mounted.current) setError(`Chưa chuyển được model; giữ lựa chọn cũ. ${cause instanceof Error ? cause.message : String(cause)}`);
      return null;
    } finally {
      window.clearTimeout(timer);
      request.current = null;
      if (mounted.current) setSwitching(false);
    }
  }, [active.id, options]);
  return { active, switching, error, verifiedLabels, choose };
}
