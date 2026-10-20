import { describe, expect, it } from "vitest";
import { config } from "./config";

describe("frontend service URLs", () => {
  it("keeps workspace APIs on the platform server when inference uses a candidate port", () => {
    expect(config.platformHttpUrl).toBe("http://localhost:8000");
  });
});
