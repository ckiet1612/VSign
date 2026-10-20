export type InferenceRoute = "server" | "local" | "unavailable";
export type CaptureFramingMode = "fixed" | "adaptive";

export interface CapturePipeline {
  sampling: "uniform" | "motion-weighted";
  framing: CaptureFramingMode;
}

interface InferenceRouteInput {
  publicDemo: boolean;
  serverConnected: boolean;
  localReady: boolean;
}

export function chooseInferenceRoute({
  publicDemo,
  serverConnected,
  localReady,
}: InferenceRouteInput): InferenceRoute {
  if (publicDemo) return localReady ? "local" : "unavailable";
  if (serverConnected) return "server";
  if (localReady) return "local";
  return "unavailable";
}

export function chooseCapturePipeline({
  purpose,
  inferenceRoute,
}: {
  purpose: "recognize" | "collect";
  inferenceRoute: InferenceRoute;
}): CapturePipeline {
  if (purpose === "collect" || inferenceRoute === "server") {
    return { sampling: "uniform", framing: "fixed" };
  }
  return { sampling: "motion-weighted", framing: "adaptive" };
}
