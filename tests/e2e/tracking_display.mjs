import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const require = createRequire(process.env.VSIGN_PLAYWRIGHT_FROM || import.meta.url);
const { chromium } = require("playwright");
const cameraFile = process.env.VSIGN_FAKE_CAMERA_FILE;
if (!cameraFile) throw new Error("Set VSIGN_FAKE_CAMERA_FILE to a replay .y4m; do not use a real webcam.");
const output = process.env.VSIGN_SMOKE_OUTPUT || "/tmp/vsign-tracking-display-smoke";
await mkdir(output, { recursive: true });

const fixtureModule = `
export const FilesetResolver = { forVisionTasks: async () => ({}) };
export class HandLandmarker {
  static HAND_CONNECTIONS = [{ start: 0, end: 1 }];
  static async createFromOptions() { return new HandLandmarker(); }
  detectForVideo() {
    const fixture = window.__trackingFixture;
    fixture.reads++;
    return {
      landmarks: fixture.hands, worldLandmarks: [],
      handedness: fixture.labels.map(categoryName => [{ categoryName, score: 0.99 }]),
      handednesses: []
    };
  }
  close() {}
}
export class PoseLandmarker {
  static async createFromOptions() { return new PoseLandmarker(); }
  detect() { return { landmarks: [window.__trackingFixture.pose], worldLandmarks: [] }; }
  close() {}
}
`;

const browser = await chromium.launch({
  channel: "chrome", headless: true,
  args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
    `--use-file-for-fake-video-capture=${cameraFile}`],
});
try {
  const context = await browser.newContext({ viewport: { width: 1365, height: 900 }, permissions: ["camera"] });
  const page = await context.newPage();
  const errors = [];
  const sampleWrites = [];
  const inferenceFrames = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    if (request.url().endsWith("/collection/samples")) sampleWrites.push(request.url());
  });
  page.on("websocket", (socket) => socket.on("framesent", ({ payload }) => {
    try {
      if (JSON.parse(payload).type === "frames") inferenceFrames.push(true);
    } catch { /* Ignore non-protocol messages. */ }
  }));
  await page.addInitScript(() => {
    const hand = (x) => Array.from({ length: 21 }, (_, index) => ({
      x: x + index * 0.001, y: 0.6 - index * 0.005, z: 0, visibility: 1,
    }));
    const pose = Array.from({ length: 33 }, () => ({ x: 0.5, y: 0.4, z: 0, visibility: 1 }));
    pose[0] = { x: 0.5, y: 0.1, z: 0, visibility: 1 };
    pose[11] = { x: 0.35, y: 0.4, z: 0, visibility: 1 };
    pose[12] = { x: 0.65, y: 0.4, z: 0, visibility: 1 };
    window.__trackingFixture = { hands: [hand(0.3), hand(0.7)], labels: ["Left", "Right"], pose, reads: 0 };
    window.__trackingDots = [];
    const prototype = CanvasRenderingContext2D.prototype;
    const clear = prototype.clearRect;
    const arc = prototype.arc;
    const fill = prototype.fill;
    prototype.clearRect = function (...args) {
      if (this.canvas.classList.contains("tracking-canvas")) window.__trackingDots = [];
      return clear.apply(this, args);
    };
    prototype.arc = function (x, y, radius, ...rest) {
      if (this.canvas.classList.contains("tracking-canvas")) this.__trackingArc = { x, y, radius };
      return arc.call(this, x, y, radius, ...rest);
    };
    prototype.fill = function (...args) {
      if (this.canvas.classList.contains("tracking-canvas") && this.__trackingArc) {
        window.__trackingDots.push({ ...this.__trackingArc, opacity: this.globalAlpha, color: this.fillStyle });
      }
      return fill.apply(this, args);
    };
  });
  await page.route("**/node_modules/.vite/deps/@mediapipe_tasks-vision.js*", (route) =>
    route.fulfill({ contentType: "application/javascript", body: fixtureModule }));
  await page.goto(process.env.VSIGN_SMOKE_URL || "http://localhost:5173");
  await page.getByRole("button", { name: "Bật camera", exact: true }).click();
  await page.waitForFunction(() => window.__trackingFixture.reads >= 2 && window.__trackingDots.some((dot) => dot.radius === 3.7));

  const colors = () => page.evaluate(() => {
    const width = document.querySelector(".tracking-canvas").getBoundingClientRect().width;
    return {
      greenX: window.__trackingDots.find((dot) => dot.radius === 2.6 && dot.color === "#dff36b")?.x / width,
      tealX: window.__trackingDots.find((dot) => dot.radius === 2.6 && dot.color === "#62ead1")?.x / width,
    };
  });
  const initial = await colors();
  assert.ok(initial.greenX > 0.5 && initial.tealX < 0.5);
  const setHands = async (xs, labels) => {
    const reads = await page.evaluate(({ xs, labels }) => {
      const fixture = window.__trackingFixture;
      fixture.hands = xs.map((x) => Array.from({ length: 21 }, (_, index) => ({
        x: x + index * 0.001, y: 0.6 - index * 0.005, z: 0, visibility: 1,
      })));
      fixture.labels = labels;
      return fixture.reads;
    }, { xs, labels });
    await page.waitForFunction((reads) => window.__trackingFixture.reads > reads, reads);
  };
  await setHands([0.7, 0.3], ["Right", "Left"]);
  const reordered = await colors();
  assert.ok(reordered.greenX > 0.5 && reordered.tealX < 0.5);
  await setHands([0.49, 0.51], ["Left", "Right"]);
  await setHands([0.42, 0.58], ["Right", "Left"]);
  await page.waitForFunction(() => {
    const width = document.querySelector(".tracking-canvas").getBoundingClientRect().width;
    const green = window.__trackingDots.find((dot) => dot.radius === 2.6 && dot.color === "#dff36b");
    const teal = window.__trackingDots.find((dot) => dot.radius === 2.6 && dot.color === "#62ead1");
    return green?.x < width / 2 && teal?.x > width / 2;
  });
  const crossed = await colors();

  const missingAt = await page.evaluate(() => {
    window.__trackingFixture.hands = [];
    window.__trackingFixture.labels = [];
    return performance.now();
  });
  await page.waitForFunction(() => window.__trackingDots.some((dot) => dot.radius === 3.7 && dot.opacity > 0 && dot.opacity < 0.65));
  const heldOpacity = await page.evaluate(() => window.__trackingDots.find((dot) => dot.radius === 3.7).opacity);
  await page.waitForFunction(() => window.__trackingDots.every((dot) => dot.radius !== 3.7));
  assert.ok(await page.evaluate(() => window.__trackingDots.some((dot) => dot.radius === 3.5)));
  const expiredAfterMs = await page.evaluate((at) => performance.now() - at, missingAt);

  await setHands([0.3], ["Left"]);
  await page.waitForFunction(() => window.__trackingDots.some((dot) => dot.radius === 3.7));
  await page.getByLabel("Hình ảnh camera trực tiếp").evaluate((video) => video.pause());
  await page.waitForFunction(() => window.__trackingDots.every((dot) => dot.radius !== 3.7));
  await page.getByLabel("Hình ảnh camera trực tiếp").evaluate((video) => video.play());
  await page.waitForFunction(() => window.__trackingDots.some((dot) => dot.radius === 3.7));

  const layouts = [];
  for (const width of [320, 390, 768, 1365]) {
    await page.setViewportSize({ width, height: 900 });
    await page.waitForFunction(() => {
      const canvas = document.querySelector(".tracking-canvas");
      const bounds = canvas.getBoundingClientRect();
      const ratio = Math.min(devicePixelRatio || 1, 1.5);
      return canvas.width === Math.round(bounds.width * ratio) &&
        canvas.height === Math.round(bounds.height * ratio) &&
        window.__trackingDots.some((dot) => dot.radius === 3.7);
    });
    const layout = await page.evaluate(() => {
      const canvas = document.querySelector(".tracking-canvas");
      const bounds = canvas.getBoundingClientRect();
      const pixels = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data;
      let visiblePixels = 0;
      for (let index = 3; index < pixels.length; index += 4) if (pixels[index] > 0) visiblePixels++;
      return {
        width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
        canvasWidth: bounds.width, canvasHeight: bounds.height, visiblePixels,
        withinViewport: bounds.left >= 0 && bounds.right <= innerWidth,
      };
    });
    assert.equal(layout.scrollWidth, layout.width);
    assert.equal(layout.withinViewport, true);
    assert.ok(layout.canvasWidth > 0 && layout.canvasHeight > 0 && layout.visiblePixels > 0);
    layouts.push(layout);
    await page.screenshot({ path: path.join(output, `tracking-${width}.png`), fullPage: true });
  }
  await page.getByRole("button", { name: "Tắt camera", exact: true }).click();
  assert.equal(await page.locator(".tracking-canvas").evaluate((canvas) =>
    canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data.some((value, index) => index % 4 === 3 && value > 0)), false);
  assert.deepEqual(sampleWrites, []);
  assert.deepEqual(inferenceFrames, []);
  assert.deepEqual(errors, []);
  await context.close();

  // A separate context uses the unmodified MediaPipe detectors on the replay video.
  const replayContext = await browser.newContext({ viewport: { width: 1365, height: 900 }, permissions: ["camera"] });
  const replayPage = await replayContext.newPage();
  const replayErrors = [];
  replayPage.on("pageerror", (error) => replayErrors.push(error.message));
  await replayPage.goto(process.env.VSIGN_SMOKE_URL || "http://localhost:5173");
  await replayPage.getByRole("button", { name: "Bật camera", exact: true }).click();
  await replayPage.waitForFunction(() => document.querySelector(".tracking-overlay")?.classList.contains("tracking-tracking"), null, { timeout: 60000 });
  const replay = await replayPage.locator(".tracking-canvas").evaluate((canvas) => {
    const pixels = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data;
    let visiblePixels = 0;
    for (let index = 3; index < pixels.length; index += 4) if (pixels[index] > 0) visiblePixels++;
    return { visiblePixels, readout: document.querySelector(".tracking-readout").textContent };
  });
  assert.ok(replay.visiblePixels > 0);
  await replayPage.screenshot({ path: path.join(output, "tracking-mediapipe-replay.png"), fullPage: true });
  await replayPage.getByRole("button", { name: "Tắt camera", exact: true }).click();
  assert.deepEqual(replayErrors, []);
  await replayContext.close();
  const report = {
    passed: true, initial, reordered, crossed, heldOpacity, expiredAfterMs, layouts,
    pausedVideoExpiry: true, cameraOffClearsCanvas: true,
    pageErrors: errors, sampleWrites, inferenceFrames, realMediaPipeReplay: replay,
    note: "Controlled landmark fixtures plus real MediaPipe on a replay camera; not real-camera quality or unseen-signer accuracy evidence.",
  };
  await writeFile(path.join(output, "report.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
} finally {
  await browser.close();
}
