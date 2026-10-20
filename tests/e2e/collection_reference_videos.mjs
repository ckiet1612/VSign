import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const require = createRequire(process.env.VSIGN_PLAYWRIGHT_FROM || import.meta.url);
const { chromium } = require("playwright");
const labels = JSON.parse(await readFile(new URL("../../contracts/v1/sales30.labels.json", import.meta.url)));
const manifest = JSON.parse(await readFile(new URL("../../apps/web/public/reference-videos/sales30/manifest.json", import.meta.url)));
const output = process.env.VSIGN_SMOKE_OUTPUT || "/tmp/vsign-collection-reference-videos";
await mkdir(output, { recursive: true });

const browser = await chromium.launch({ channel: "chrome", headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1365, height: 900 } });
  const pageErrors = [];
  const savedSamples = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("request", (request) => {
    if (request.url().endsWith("/collection/samples")) savedSamples.push(request.url());
  });
  await page.addInitScript(() => {
    window.WebSocket = class {
      static OPEN = 1;
      readyState = 0;
      onopen = null;
      onmessage = null;
      onclose = null;
      onerror = null;
      send() { throw new Error("Video preview must not send inference"); }
      close() { this.readyState = 3; }
    };
  });
  await page.route("**/metadata", (route) => route.fulfill({ json: {
    backend: "onnx", model_version: "sales30-reference-preview-fixture",
    protocol_version: "1.0", frame_count: 16, frame_width: 224, frame_height: 224,
    supported_image_formats: ["image/jpeg", "image/webp"],
    confidence_threshold: 0.7, margin_threshold: 0.15,
    labels, collection_labels: labels, candidate_labels_unverified: false,
    mock: false, collection_enabled: true, collection_target_per_hand: 50,
    sentence_ai_enabled: false,
  } }));
  await page.route("**/collection/summary?batch=personal-100", (route) => route.fulfill({ json: {
    enabled: true, batch: "personal-100", target_per_label: 100, target_per_hand: 50, counts: {},
  } }));
  await page.goto(process.env.VSIGN_SMOKE_URL || "http://localhost:5173");
  assert.equal(await page.getByLabel(/Video mẫu cho từ/).count(), 0);
  await page.locator('summary[aria-label="Công cụ"]').click();
  await page.getByRole("button", { name: "Thu dữ liệu AI", exact: true }).click();
  const select = page.locator("#collection-label");
  const playback = [];
  for (const clip of manifest.videos) {
    await select.selectOption(clip.label);
    const video = page.getByLabel(`Video mẫu cho từ ${clip.label}`, { exact: true });
    const source = await video.locator("source").getAttribute("src");
    assert.equal(new URL(source, page.url()).pathname, `/reference-videos/sales30/${clip.file}`);
    await video.evaluate(async (element) => { await element.play(); });
    await page.waitForFunction(() => {
      const video = document.querySelector(".reference-player video");
      return video && video.currentTime > 0.1 && video.videoWidth > 0 && video.videoHeight > 0;
    });
    const state = await video.evaluate((element) => {
      element.pause();
      return {
        width: element.videoWidth, height: element.videoHeight,
        duration: element.duration, currentTime: element.currentTime,
        controls: element.controls, loop: element.loop, muted: element.muted,
        playsInline: element.playsInline, hasCameraStream: element.srcObject !== null,
      };
    });
    assert.equal(state.controls, true);
    assert.equal(state.loop, true);
    assert.equal(state.muted, true);
    assert.equal(state.playsInline, true);
    assert.equal(state.hasCameraStream, false);
    assert.ok(Math.abs(state.duration - clip.duration_s) < 0.15);
    playback.push({ label: clip.label, file: clip.file, ...state });
  }
  await select.selectOption("Không ký hiệu");
  assert.equal(await page.getByLabel(/Video mẫu cho từ/).count(), 0);
  assert.equal(await page.getByText(/Không làm một từ nào: đứng yên/).count(), 1);
  await select.selectOption("Điện thoại");
  await page.getByLabel("Video mẫu cho từ Điện thoại").evaluate(async (element) => {
    await element.play();
    element.pause();
  });
  const layouts = [];
  for (const width of [320, 390, 768, 1365]) {
    await page.setViewportSize({ width, height: 900 });
    const layout = await page.evaluate(() => {
      const video = document.querySelector(".reference-player video");
      const box = video.getBoundingClientRect();
      return {
        width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
        videoWidth: box.width, videoHeight: box.height,
        videoWithinViewport: box.left >= 0 && box.right <= innerWidth,
      };
    });
    assert.equal(layout.scrollWidth, layout.width);
    assert.equal(layout.videoWithinViewport, true);
    assert.ok(layout.videoWidth > 0 && layout.videoHeight > 0);
    layouts.push(layout);
    await page.screenshot({ path: path.join(output, `collection-videos-${width}.png`), fullPage: true });
  }
  await page.getByRole("button", { name: "Nhận dạng", exact: true }).click();
  assert.equal(await page.getByLabel(/Video mẫu cho từ/).count(), 0);
  assert.deepEqual(savedSamples, []);
  assert.deepEqual(pageErrors, []);
  const report = {
    passed: true, playback, layouts, pageErrors, savedSamples,
    negativeGuidancePreserved: true, recognitionScreenUnchanged: true,
    note: "Real local MP4 playback in Chrome; metadata/progress fixtures. No webcam, sample writes, or model-quality claim.",
  };
  await writeFile(path.join(output, "report.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
} finally {
  await browser.close();
}
