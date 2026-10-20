/// <reference types="node" />
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import sales30Labels from "../../../contracts/v1/sales30.labels.json";
import sales30Manifest from "../public/reference-videos/sales30/manifest.json";
import { REFERENCE_SIGNS, referenceVideoFor } from "./referenceSigns";

afterEach(() => vi.unstubAllEnvs());

describe("Sales30 reference videos", () => {
  it("covers the complete collection vocabulary without duplicate labels", () => {
    expect(REFERENCE_SIGNS.map((sign) => sign.label)).toEqual(sales30Labels);
    expect(new Set(REFERENCE_SIGNS.map((sign) => sign.label)).size).toBe(30);
  });

  it.each(sales30Manifest.videos)("serves the original clip for $label", (clip) => {
    const videoUrl = referenceVideoFor(clip.label);
    expect(videoUrl).not.toBeNull();
    const url = new URL(videoUrl!, "http://localhost");
    expect(url.pathname).toBe(`/reference-videos/sales30/${clip.file}`);
    const bytes = readFileSync(path.join(process.cwd(), "public", url.pathname));
    expect(createHash("sha256").update(bytes).digest("hex")).toBe(clip.sha256);
  });

  it("respects a nested deployment base path", () => {
    vi.stubEnv("BASE_URL", "/VSign/");
    expect(referenceVideoFor("Điện thoại")).toMatch(
      /^\/VSign\/reference-videos\/sales30\/11-dien-thoai\.mp4\?v=/,
    );
  });

  it("does not substitute another vocabulary's clip for missing or negative labels", () => {
    expect(referenceVideoFor("Không ký hiệu")).toBeNull();
    expect(referenceVideoFor("Xin lỗi")).toBeNull();
    expect(referenceVideoFor("Nhãn chưa biết")).toBeNull();
  });
});
