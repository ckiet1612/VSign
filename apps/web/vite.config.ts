import path from "node:path";
import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  base: process.env.VITE_BASE_PATH ?? "/",
  plugins: [react()],
  resolve: {
    alias: {
      "@contracts": fileURLToPath(
        new URL("../../contracts/v1/inference.ts", import.meta.url),
      ),
      "@workspace-contracts": fileURLToPath(
        new URL("../../contracts/v1/workspace.ts", import.meta.url),
      ),
      "@src": path.resolve(fileURLToPath(new URL(".", import.meta.url)), "src"),
    },
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: true,
  },
});
