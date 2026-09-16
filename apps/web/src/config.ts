export const config = {
  publicDemo: import.meta.env.VITE_PUBLIC_DEMO === "true",
  inferenceWsUrl:
    import.meta.env.VITE_INFERENCE_WS_URL ?? "ws://localhost:8000/ws/inference",
  inferenceHttpUrl:
    import.meta.env.VITE_INFERENCE_HTTP_URL ?? "http://localhost:8000",
} as const;
