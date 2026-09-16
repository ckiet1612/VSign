/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_INFERENCE_WS_URL?: string;
  readonly VITE_INFERENCE_HTTP_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
