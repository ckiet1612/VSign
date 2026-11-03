import { afterEach, describe, expect, it, vi } from "vitest";
import { config } from "./config";

afterEach(() => { vi.unstubAllEnvs(); vi.resetModules(); });

describe("frontend service URLs", () => {
  it("keeps workspace APIs on the platform server when inference uses a candidate port", () => {
    expect(config.platformHttpUrl).toBe("http://localhost:8000");
  });

  it("loads the optional AWS endpoint independently of Modal", async () => {
    vi.stubEnv("VITE_INFERENCE_AWS_HTTP_URL", "https://aws.example///");
    vi.stubEnv("VITE_INFERENCE_AWS_WS_URL", "wss://aws.example/ws/inference");
    vi.resetModules();
    const { config: configured } = await import("./config");
    expect(configured.awsRuntime).toEqual({ httpUrl: "https://aws.example", wsUrl: "wss://aws.example/ws/inference" });
  });

  it("does not configure AWS from only one URL", async () => {
    vi.stubEnv("VITE_INFERENCE_AWS_HTTP_URL", "https://aws.example");
    vi.stubEnv("VITE_INFERENCE_AWS_WS_URL", "");
    vi.resetModules();
    const { config: configured } = await import("./config");
    expect(configured.awsRuntime).toBeNull();
  });
});
