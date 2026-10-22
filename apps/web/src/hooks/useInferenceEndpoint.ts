import { useCallback, useEffect, useRef, useState } from "react";
import type { InferenceMetadata } from "@contracts";
import type { ConnectionStatus } from "./useInferenceSocket";
import {
  GPU_FAILURE_GRACE_MS,
  GPU_IDLE_RELEASE_MS,
  GPU_PROBE_INTERVAL_MS,
  GPU_PROBE_TIMEOUT_MS,
  GPU_TOKEN_RENEW_MARGIN_MS,
  gpuRuntimeMatches,
  withInferenceToken,
  type InferenceEndpointKind,
} from "../lib/inferenceEndpoint";

export interface GpuRuntime {
  httpUrl: string;
  wsUrl: string;
}

export interface InferenceEndpointOptions {
  /** The Modal GPU runtime, or null when none is configured. */
  gpu: GpuRuntime | null;
  macWsUrl: string | null;
  platformUrl: string;
  /** Metadata of the Mac runtime; the GPU runtime must serve the identical model. */
  macMetadata: InferenceMetadata | null;
  enabled: boolean;
  socketStatus: ConnectionStatus;
  /** True while a sign is being captured or awaits its prediction; switches wait for it. */
  isBusy: () => boolean;
  fetcher?: typeof fetch;
}

export interface InferenceEndpoint {
  kind: InferenceEndpointKind;
  wsUrl: string | null;
  /** Called when a sign is sent or the camera starts, so an idle tab releases the GPU. */
  noteActivity: () => void;
}

interface GpuSocket {
  wsUrl: string;
  expiresAt: number;
}

interface TokenResponse {
  token: string;
  expires_at: number;
}

const TICK_MS = 3_000;

/**
 * Prefers the Modal GPU runtime and falls back to the Mac when it is stopped, failing or still
 * starting. Switches happen between signs; the Mac stays the source of metadata and login.
 */
export function useInferenceEndpoint(options: InferenceEndpointOptions): InferenceEndpoint {
  const [gpuSocket, setGpuSocket] = useState<GpuSocket | null>(null);
  const latest = useRef(options);
  latest.current = options;
  const gpuRef = useRef(gpuSocket);
  gpuRef.current = gpuSocket;
  const lastActivity = useRef(Date.now());
  const lastProbe = useRef(Number.NEGATIVE_INFINITY);
  const downSince = useRef<number | null>(null);
  const inFlight = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!gpuSocket || options.socketStatus === "connected") downSince.current = null;
    else downSince.current ??= Date.now();
  }, [gpuSocket, options.socketStatus]);

  const requestToken = useCallback(async (signal: AbortSignal): Promise<GpuSocket | null> => {
    const { gpu, platformUrl, fetcher = fetch } = latest.current;
    if (!gpu) return null;
    const response = await fetcher(`${platformUrl}/api/v1/inference/token`, {
      method: "POST", credentials: "include", signal,
    });
    if (!response.ok) throw new Error("inference token unavailable");
    const body = await response.json() as TokenResponse;
    return { wsUrl: withInferenceToken(gpu.wsUrl, body.token), expiresAt: body.expires_at * 1000 };
  }, []);

  const tick = useCallback(async () => {
    const { enabled, gpu, macMetadata, isBusy, fetcher = fetch } = latest.current;
    const current = gpuRef.current;
    const now = Date.now();
    if (!enabled || !gpu || !macMetadata) {
      if (current) setGpuSocket(null);
      return;
    }
    if (inFlight.current) return;
    const idle = now - lastActivity.current > GPU_IDLE_RELEASE_MS;

    if (current) {
      if (downSince.current !== null && now - downSince.current > GPU_FAILURE_GRACE_MS) {
        lastProbe.current = now;
        setGpuSocket(null);
        return;
      }
      if (isBusy()) return;
      if (idle) {
        setGpuSocket(null);
        return;
      }
      if (current.expiresAt - now > GPU_TOKEN_RENEW_MARGIN_MS) return;
      const request = new AbortController();
      inFlight.current = request;
      try {
        const renewed = await requestToken(request.signal);
        if (gpuRef.current === current && !latest.current.isBusy()) setGpuSocket(renewed);
      } catch {
        if (!request.signal.aborted && gpuRef.current === current) setGpuSocket(null);
      } finally {
        if (inFlight.current === request) inFlight.current = null;
      }
      return;
    }

    if (idle || now - lastProbe.current < GPU_PROBE_INTERVAL_MS) return;
    lastProbe.current = now;
    const request = new AbortController();
    inFlight.current = request;
    const timeout = window.setTimeout(() => request.abort(), GPU_PROBE_TIMEOUT_MS);
    try {
      const response = await fetcher(`${gpu.httpUrl}/metadata`, { signal: request.signal });
      if (!response.ok) return;
      const gpuMetadata = await response.json() as InferenceMetadata;
      const mac = latest.current.macMetadata;
      if (!mac || !gpuRuntimeMatches(gpuMetadata, mac)) return;
      const socket = await requestToken(request.signal);
      const fresh = latest.current;
      if (socket && fresh.enabled && fresh.gpu?.wsUrl === gpu.wsUrl && !fresh.isBusy()) setGpuSocket(socket);
    } catch {
      // Stopped, cold or unreachable: stay on the Mac and probe again later.
    } finally {
      window.clearTimeout(timeout);
      if (inFlight.current === request) inFlight.current = null;
    }
  }, [requestToken]);

  const hasMacMetadata = options.macMetadata !== null;
  useEffect(() => {
    void tick();
  }, [tick, hasMacMetadata, options.enabled]);

  useEffect(() => {
    const interval = window.setInterval(() => void tick(), TICK_MS);
    return () => {
      window.clearInterval(interval);
      inFlight.current?.abort();
      inFlight.current = null;
    };
  }, [tick]);

  const noteActivity = useCallback(() => {
    lastActivity.current = Date.now();
  }, []);

  const useGpu = gpuSocket !== null && options.enabled && options.gpu !== null;
  return {
    kind: useGpu ? "gpu" : "mac",
    wsUrl: useGpu ? gpuSocket.wsUrl : options.macWsUrl,
    noteActivity,
  };
}
