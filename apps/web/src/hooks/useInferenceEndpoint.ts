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

export type GpuProvider = "modal" | "aws";

export interface InferenceEndpointOptions {
  /** The Modal GPU runtime, or null when none is configured. */
  gpu: GpuRuntime | null;
  aws?: GpuRuntime | null;
  macWsUrl: string | null;
  platformUrl: string;
  /** Metadata of the Mac runtime; the GPU runtime must serve the identical model. */
  macMetadata: InferenceMetadata | null;
  enabled: boolean;
  socketStatus: ConnectionStatus;
  /** The socket actually serving requests; a parked Mac socket can still report connected. */
  activeWsUrl?: string | null;
  /** True while a sign is being captured or awaits its prediction; switches wait for it. */
  isBusy: () => boolean;
  fetcher?: typeof fetch;
}

export interface InferenceEndpoint {
  kind: InferenceEndpointKind;
  provider: GpuProvider | null;
  wsUrl: string | null;
  /** Called when a sign is sent or the camera starts, so an idle tab releases the GPU. */
  noteActivity: () => void;
}

interface GpuSocket {
  provider: GpuProvider;
  wsUrl: string;
  expiresAt: number;
  metadata: InferenceMetadata;
}

interface TokenResponse {
  token: string;
  expires_at: number;
}

const TICK_MS = 3_000;

/**
 * Modal > AWS > Mac. Independent probes let AWS serve while Modal cold-starts.
 * Switches happen between signs; the Mac remains the source of metadata and login.
 */
export function useInferenceEndpoint(options: InferenceEndpointOptions): InferenceEndpoint {
  const [gpuSocket, setGpuSocket] = useState<GpuSocket | null>(null);
  const latest = useRef(options);
  latest.current = options;
  const gpuRef = useRef(gpuSocket);
  gpuRef.current = gpuSocket;
  const lastActivity = useRef(Date.now());
  const lastProbe = useRef(new Map<GpuProvider, number>());
  const downSince = useRef<number | null>(null);
  const inFlight = useRef(new Map<GpuProvider, AbortController>());
  const available = useRef(new Map<GpuProvider, GpuSocket>());

  const select = useCallback((socket: GpuSocket | null) => {
    if (gpuRef.current === socket) return;
    const connectionChanged = gpuRef.current?.wsUrl !== socket?.wsUrl;
    gpuRef.current = socket;
    if (connectionChanged) downSince.current = null;
    setGpuSocket(socket);
  }, []);

  const reconcile = useCallback(() => {
    const fresh = latest.current;
    if (!fresh.enabled || fresh.isBusy() || !fresh.macMetadata) return;
    if (Date.now() - lastActivity.current > GPU_IDLE_RELEASE_MS) return;
    for (const provider of ["modal", "aws"] as const) {
      const runtime = provider === "modal" ? fresh.gpu : fresh.aws;
      const ready = available.current.get(provider);
      if (runtime && ready && ready.expiresAt > Date.now() &&
          ready.wsUrl.split("?")[0] === runtime.wsUrl.split("?")[0] &&
          gpuRuntimeMatches(ready.metadata, fresh.macMetadata)) {
        select(ready);
        return;
      }
    }
    select(null);
  }, [select]);

  useEffect(() => {
    const selectedConnected = options.socketStatus === "connected" &&
      (options.activeWsUrl === undefined ||
        options.activeWsUrl === gpuSocket?.wsUrl);
    if (!gpuSocket || selectedConnected) downSince.current = null;
    else downSince.current ??= Date.now();
  }, [gpuSocket, options.socketStatus, options.activeWsUrl]);

  const probe = useCallback(async (provider: GpuProvider, runtime: GpuRuntime) => {
    const request = new AbortController();
    inFlight.current.set(provider, request);
    const timeout = window.setTimeout(() => request.abort(), GPU_PROBE_TIMEOUT_MS);
    const { platformUrl, fetcher = fetch } = latest.current;
    try {
      const metadataResponse = await fetcher(`${runtime.httpUrl}/metadata`, { signal: request.signal });
      if (!metadataResponse.ok) throw new Error("GPU metadata unavailable");
      const metadata = await metadataResponse.json() as InferenceMetadata;
      const mac = latest.current.macMetadata;
      if (!mac || !gpuRuntimeMatches(metadata, mac)) {
        available.current.delete(provider);
        reconcile();
        return;
      }
      const previous = available.current.get(provider);
      let socket = previous ? { ...previous, metadata } : undefined;
      if (!previous || previous.wsUrl.split("?")[0] !== runtime.wsUrl.split("?")[0] ||
          previous.expiresAt - Date.now() <= GPU_TOKEN_RENEW_MARGIN_MS) {
        const response = await fetcher(`${platformUrl}/api/v1/inference/token`, {
          method: "POST", credentials: "include", signal: request.signal,
        });
        if (!response.ok) throw new Error("inference token unavailable");
        const body = await response.json() as TokenResponse;
        if (!body.token || !Number.isFinite(body.expires_at) || body.expires_at * 1000 <= Date.now()) {
          throw new Error("invalid inference token");
        }
        socket = { provider, metadata, wsUrl: withInferenceToken(runtime.wsUrl, body.token), expiresAt: body.expires_at * 1000 };
      }
      const fresh = latest.current;
      const configured = provider === "modal" ? fresh.gpu : fresh.aws;
      if (socket && !request.signal.aborted && fresh.enabled && configured?.wsUrl === runtime.wsUrl &&
          configured.httpUrl === runtime.httpUrl && fresh.macMetadata && gpuRuntimeMatches(metadata, fresh.macMetadata)) {
        available.current.set(provider, socket);
        reconcile();
      }
    } catch {
      if (!request.signal.aborted) {
        // An HTTP probe failure alone must not interrupt a working socket.
        if (gpuRef.current?.provider !== provider) {
          available.current.delete(provider);
          reconcile();
        }
      }
    } finally {
      window.clearTimeout(timeout);
      if (inFlight.current.get(provider) === request) inFlight.current.delete(provider);
    }
  }, [reconcile]);

  const tick = useCallback(async () => {
    const { enabled, gpu, aws, macMetadata, isBusy } = latest.current;
    const current = gpuRef.current;
    const now = Date.now();
    if (!enabled || (!gpu && !aws) || !macMetadata) {
      for (const request of inFlight.current.values()) request.abort();
      available.current.clear();
      if (current) select(null);
      return;
    }
    const idle = now - lastActivity.current > GPU_IDLE_RELEASE_MS;
    if (isBusy()) return;
    if (idle) {
      for (const request of inFlight.current.values()) request.abort();
      available.current.clear();
      select(null);
      return;
    }
    if (current && downSince.current !== null && now - downSince.current > GPU_FAILURE_GRACE_MS) {
      available.current.delete(current.provider);
      inFlight.current.get(current.provider)?.abort();
      lastProbe.current.set(current.provider, now);
      select(null);
    }
    for (const provider of ["modal", "aws"] as const) {
      const runtime = provider === "modal" ? gpu : aws;
      if (!runtime) {
        available.current.delete(provider);
        continue;
      }
      if (inFlight.current.has(provider) ||
          now - (lastProbe.current.get(provider) ?? Number.NEGATIVE_INFINITY) < GPU_PROBE_INTERVAL_MS) continue;
      lastProbe.current.set(provider, now);
      void probe(provider, runtime);
    }
    reconcile();
  }, [probe, reconcile, select]);

  const hasMacMetadata = options.macMetadata !== null;
  const runtimeKey = `${options.gpu?.httpUrl}|${options.gpu?.wsUrl}|${options.aws?.httpUrl}|${options.aws?.wsUrl}`;
  useEffect(() => {
    void tick();
  }, [tick, hasMacMetadata, options.enabled, runtimeKey]);

  useEffect(() => {
    const requests = inFlight.current;
    const interval = window.setInterval(() => void tick(), TICK_MS);
    return () => {
      window.clearInterval(interval);
      for (const request of requests.values()) request.abort();
      requests.clear();
    };
  }, [tick]);

  const noteActivity = useCallback(() => {
    lastActivity.current = Date.now();
  }, []);

  const configured = gpuSocket?.provider === "aws" ? options.aws : options.gpu;
  const useGpu = gpuSocket !== null && options.enabled && configured != null &&
    gpuSocket.wsUrl.split("?")[0] === configured.wsUrl.split("?")[0];
  return {
    kind: useGpu ? "gpu" : "mac",
    provider: useGpu ? gpuSocket.provider : null,
    wsUrl: useGpu ? gpuSocket.wsUrl : options.macWsUrl,
    noteActivity,
  };
}
