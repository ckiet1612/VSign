const inferenceWsUrl = import.meta.env.VITE_INFERENCE_WS_URL ?? "ws://localhost:8000/ws/inference";
const inferenceHttpUrl = import.meta.env.VITE_INFERENCE_HTTP_URL ?? "http://localhost:8000";
const platformHttpUrl = import.meta.env.VITE_PLATFORM_HTTP_URL ?? "http://localhost:8000";
// Optional Modal GPU runtime for recognition; the Mac above stays the fallback and the source of login.
const modalHttpUrl = import.meta.env.VITE_INFERENCE_MODAL_HTTP_URL?.trim().replace(/\/+$/, "");
const modalWsUrl = import.meta.env.VITE_INFERENCE_MODAL_WS_URL?.trim();

export const config = {
  publicDemo: import.meta.env.VITE_PUBLIC_DEMO === "true",
  inferenceWsUrl,
  inferenceHttpUrl,
  platformHttpUrl,
  gpuRuntime: modalHttpUrl && modalWsUrl ? { httpUrl: modalHttpUrl, wsUrl: modalWsUrl } : null,
  platformAuthRequiredHint: import.meta.env.VITE_PLATFORM_AUTH_REQUIRED === "true",
  serverModels: [
    { id: "current" as const, label: "Hiện tại", httpUrl: inferenceHttpUrl, wsUrl: inferenceWsUrl },
    ...(import.meta.env.DEV && import.meta.env.VITE_PUBLIC_DEMO !== "true" ? [{
      id: "seated" as const, label: "Seated + Personal",
      httpUrl: import.meta.env.VITE_SEATED_INFERENCE_HTTP_URL ?? "http://localhost:8003",
      wsUrl: import.meta.env.VITE_SEATED_INFERENCE_WS_URL ?? "ws://localhost:8003/ws/inference",
    }] : []),
  ],
} as const;
