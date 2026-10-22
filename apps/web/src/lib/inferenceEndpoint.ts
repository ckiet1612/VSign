import type { InferenceMetadata } from "@contracts";

export type InferenceEndpointKind = "gpu" | "mac";

/** How often the Mac re-checks the GPU runtime while someone is signing. */
export const GPU_PROBE_INTERVAL_MS = 15_000;
/** A cold GPU container loads the model before it answers; the probe also wakes it. */
export const GPU_PROBE_TIMEOUT_MS = 45_000;
/** Without recognition for this long the GPU socket closes so Modal can scale to zero. */
export const GPU_IDLE_RELEASE_MS = 10 * 60_000;
/** A GPU socket that stays down this long falls back to the Mac. */
export const GPU_FAILURE_GRACE_MS = 6_000;
/** Renew the signed token (by reconnecting between signs) this long before it expires. */
export const GPU_TOKEN_RENEW_MARGIN_MS = 5 * 60_000;

function sameList(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

/** The GPU runtime may stand in for the Mac only when it serves the identical model and input contract. */
export function gpuRuntimeMatches(gpu: InferenceMetadata, mac: InferenceMetadata): boolean {
  return !gpu.mock && !mac.mock &&
    gpu.model_version === mac.model_version &&
    gpu.protocol_version === mac.protocol_version &&
    (gpu.input_framing ?? "center-square") === (mac.input_framing ?? "center-square") &&
    gpu.candidate_labels_unverified === mac.candidate_labels_unverified &&
    sameList(gpu.labels, mac.labels);
}

export function withInferenceToken(wsUrl: string, token: string): string {
  const url = new URL(wsUrl);
  url.searchParams.set("token", token);
  return url.toString();
}
