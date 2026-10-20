import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const require = createRequire(process.env.VSIGN_PLAYWRIGHT_FROM || import.meta.url);
const { chromium } = require("playwright");
const cameraFile = process.env.VSIGN_FAKE_CAMERA_FILE;
if (!cameraFile) throw new Error("Set VSIGN_FAKE_CAMERA_FILE to a replay webcam .y4m file.");
const output = process.env.VSIGN_SMOKE_OUTPUT || "/tmp/vsign-auto-transcript-smoke";
await mkdir(output, { recursive: true });
const modelVersion = "auto-transcript-workflow-fixture";
const browser = await chromium.launch({
  channel: "chrome", headless: true,
  args: [
    "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
    `--use-file-for-fake-video-capture=${cameraFile}`,
  ],
});

try {
  const context = await browser.newContext({
    viewport: { width: 320, height: 900 }, permissions: ["camera"],
  });
  await context.addInitScript(({ version }) => {
    const NativeSocket = window.WebSocket;
    window.__transcriptRequests = [];
    class FixtureSocket {
      static CONNECTING = 0;
      static OPEN = 1;
      static CLOSING = 2;
      static CLOSED = 3;
      readyState = 1;
      onopen = null;
      onmessage = null;
      onclose = null;
      constructor(url, protocols) {
        if (!String(url).includes("/ws/inference")) return new NativeSocket(url, protocols);
        queueMicrotask(() => this.onopen?.(new Event("open")));
      }
      send(data) {
        const payload = JSON.parse(data);
        if (payload.type === "frames") window.__transcriptRequests.push({ payload, socket: this });
      }
      close() { this.readyState = 3; }
    }
    window.WebSocket = FixtureSocket;
    window.__replyTranscript = (sequence, label = "Chào") => {
      const request = window.__transcriptRequests.find(({ payload }) => payload.sequence === sequence);
      if (!request) throw new Error(`No request for sequence ${sequence}`);
      request.socket.onmessage?.(new MessageEvent("message", { data: JSON.stringify({
        type: "prediction", sequence, status: "ok", label, confidence: 0.95,
        top_k: [{ label, confidence: 0.95 }], model_version: version,
      }) }));
    };
  }, { version: modelVersion });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/metadata", (route) => route.fulfill({
    json: {
      backend: "pytorch", model_version: modelVersion, protocol_version: "1.0",
      frame_count: 16, frame_width: 224, frame_height: 224,
      labels: ["Chào", "Mua", "Nồi cơm điện"], supported_image_formats: ["image/webp", "image/jpeg"],
      confidence_threshold: 0.70, margin_threshold: 0.15,
      candidate_labels_unverified: false, mock: false, collection_enabled: false,
    },
  }));
  await page.goto(process.env.VSIGN_SMOKE_URL || "http://localhost:5173");
  const manualAdd = page.getByRole("radio", { name: "Thêm từ thủ công", includeHidden: true });
  const autoAdd = page.getByRole("radio", { name: "Thêm từ tự động", includeHidden: true });
  const undo = page.getByRole("button", { name: "Hoàn tác từ cuối", includeHidden: true });
  const transcript = page.getByRole("region", { name: "Câu của bạn" });
  async function selectCaptureMode(name) {
    if (!await page.locator(".capture-settings").evaluate(element => element.open)) {
      await page.getByText("Cách thu", { exact: true }).click();
    }
    await page.getByRole("button", { name, exact: true }).click();
    assert.equal(await page.locator(".capture-settings").evaluate(element => element.open), false);
    assert.equal(await page.locator(".capture-settings > summary").evaluate(element => element === document.activeElement), true);
  }
  assert.equal(await manualAdd.isChecked(), true);
  await page.getByRole("button", { name: "Bật camera", exact: true }).click();
  await page.getByText("Cách thêm từ", { exact: true }).click();
  await selectCaptureMode("Tự động beta");
  await page.waitForFunction(() => window.__transcriptRequests.length >= 1, null, { timeout: 60000 });
  await page.evaluate(() => window.__replyTranscript(0));
  assert.equal(await undo.isDisabled(), true);
  await page.getByRole("button", { name: "Thêm vào câu", exact: true }).click();
  await transcript.getByText("1 từ", { exact: true }).waitFor();
  await undo.click();
  await selectCaptureMode("Giữ để ký");
  await autoAdd.click();
  assert.equal(await undo.isDisabled(), true);
  assert.equal(await page.locator(".capture-settings .mode.active").getAttribute("aria-pressed"), "true");

  async function captureManual() {
    const before = await page.evaluate(() => window.__transcriptRequests.length);
    const hold = page.getByRole("button", { name: "Giữ để ký, cũng có thể giữ phím Space" });
    await page.waitForFunction(() => {
      const button = document.querySelector(".hold-button");
      const video = document.querySelector("video");
      return button && !button.disabled && video && video.readyState >= 2;
    });
    await hold.scrollIntoViewIfNeeded();
    const bounds = await hold.boundingBox();
    assert.ok(bounds);
    await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
    await page.mouse.down();
    // This is the fixture's capture duration, not a network or inference wait.
    await new Promise((resolve) => setTimeout(resolve, 1000));
    await page.mouse.up();
    await page.waitForFunction((count) => window.__transcriptRequests.length > count, before);
    return page.evaluate((index) => window.__transcriptRequests[index].payload.sequence, before);
  }

  const firstAuto = await captureManual();
  await page.evaluate((sequence) => window.__replyTranscript(sequence), firstAuto);
  await transcript.getByText("1 từ", { exact: true }).waitFor();
  await page.evaluate((sequence) => window.__replyTranscript(sequence), firstAuto);
  assert.equal(await transcript.getByText("1 từ", { exact: true }).isVisible(), true);
  assert.equal(await page.getByRole("button", { name: "Thêm vào câu", exact: true }).count(), 0);

  const pending = await captureManual();
  await manualAdd.click();
  await autoAdd.click();
  await page.evaluate((sequence) => window.__replyTranscript(sequence, "Mua"), pending);
  assert.equal(await transcript.getByText("1 từ", { exact: true }).isVisible(), true);

  const longLabelSequence = await captureManual();
  await page.evaluate((sequence) => window.__replyTranscript(sequence, "Nồi cơm điện"), longLabelSequence);
  await transcript.getByText("Chào Nồi cơm điện", { exact: true }).waitFor();

  const layouts = [];
  for (const width of [320, 390, 768, 1365]) {
    await page.setViewportSize({ width, height: 900 });
    await autoAdd.scrollIntoViewIfNeeded();
    const layout = await page.evaluate(() => ({
      width: innerWidth, scrollWidth: document.body.scrollWidth,
      overflow: Array.from(document.querySelectorAll(".word-insertion-options label,.automatic-insertion-status,.result-label,.transcript-content p,.transcript-actions button")).filter((element) => {
        const bounds = element.getBoundingClientRect();
        return bounds.width && (bounds.left < -1 || bounds.right > innerWidth + 1 || element.scrollWidth > element.clientWidth + 2);
      }).map((element) => element.textContent),
    }));
    assert.equal(layout.width, layout.scrollWidth);
    assert.deepEqual(layout.overflow, []);
    layouts.push(layout);
    await page.screenshot({ path: path.join(output, `automatic-${width}.png`), fullPage: true });
  }

  await undo.click();
  await transcript.getByText("1 từ", { exact: true }).waitFor();

  const beforeAutomaticCapture = await page.evaluate(() => window.__transcriptRequests.length);
  await selectCaptureMode("Tự động beta");
  await page.waitForFunction((count) => window.__transcriptRequests.length > count, beforeAutomaticCapture, { timeout: 60000 });
  const nextSequence = await page.evaluate((index) => window.__transcriptRequests[index].payload.sequence, beforeAutomaticCapture);
  await page.evaluate((sequence) => window.__replyTranscript(sequence, "Mua"), nextSequence);
  await transcript.getByText("Chào Mua", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Tắt camera", exact: true }).click();
  await page.waitForFunction(() => document.activeElement?.textContent.trim() === "Bật camera");
  const active = await page.evaluate(() => window.__transcriptRequests.at(-1).payload.sequence);
  await page.evaluate((sequence) => window.__replyTranscript(sequence), active);
  assert.equal(await transcript.getByText("2 từ", { exact: true }).isVisible(), true);
  await undo.click();
  await page.evaluate((sequence) => window.__replyTranscript(sequence, "Mua"), nextSequence);
  assert.equal(await transcript.getByText("1 từ", { exact: true }).isVisible(), true);
  await page.getByRole("button", { name: "Xóa toàn bộ câu" }).click();
  await page.evaluate((sequence) => window.__replyTranscript(sequence), firstAuto);
  assert.equal(await undo.isDisabled(), true);
  await manualAdd.click();
  assert.equal(await page.locator(".add-button").isDisabled(), true);
  await page.screenshot({ path: path.join(output, "manual-after-clear.png"), fullPage: true });

  const requests = await page.evaluate(async () => Promise.all(window.__transcriptRequests.map(async ({ payload }) => {
    const image = new Image();
    image.src = payload.frames[0];
    await image.decode();
    return { sequence: payload.sequence, frameCount: payload.frames.length, width: image.naturalWidth, height: image.naturalHeight };
  })));
  assert.ok(requests.every(({ frameCount, width, height }) => frameCount === 16 && width === 224 && height === 224));
  assert.deepEqual(errors, []);
  const report = {
    passed: true, requests, layouts, defaultManual: true, manualClick: true,
    autoInsertionWithManualCapture: true, autoInsertionWithAutomaticCapture: true,
    oldReplyIgnoredAfterToggle: true, duplicateReplyIgnored: true, undoAndClear: true,
    mobileCaptureSelection: true, captureSelectionClosesDisclosure: true, cameraStopRestoresFocus: true,
    pageErrors: errors,
    note: "Replay camera and deterministic metadata/prediction fixtures; workflow evidence only, not model accuracy or latency evidence.",
  };
  await writeFile(path.join(output, "report.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
} finally {
  await browser.close();
}
