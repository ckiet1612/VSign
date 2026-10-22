/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_INFERENCE_WS_URL?: string;
  readonly VITE_INFERENCE_HTTP_URL?: string;
  readonly VITE_PLATFORM_HTTP_URL?: string;
  readonly VITE_INFERENCE_MODAL_HTTP_URL?: string;
  readonly VITE_INFERENCE_MODAL_WS_URL?: string;
  readonly VITE_SEATED_INFERENCE_WS_URL?: string;
  readonly VITE_SEATED_INFERENCE_HTTP_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
