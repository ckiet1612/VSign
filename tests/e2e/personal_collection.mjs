import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import path from "node:path";

const require = createRequire(process.env.VSIGN_PLAYWRIGHT_FROM || import.meta.url);
const { chromium } = require("playwright");
const cameraFile = process.env.VSIGN_FAKE_CAMERA_FILE;
const dataRoot = process.env.VSIGN_COLLECTION_SMOKE_DATA;
const backend = process.env.VSIGN_COLLECTION_SMOKE_BACKEND;
if (!cameraFile || !backend || !dataRoot?.startsWith("/tmp/vsign-")) {
  throw new Error("Set camera replay, isolated smoke backend and /tmp/vsign-* data root; never use real collection data.");
}
const output = process.env.VSIGN_SMOKE_OUTPUT || "/tmp/vsign-personal100-smoke";
await mkdir(output, { recursive: true });
const legacy = path.join(dataRoot, "cho/right/sentinel.mp4");
await mkdir(path.dirname(legacy), { recursive: true });
await writeFile(legacy, "legacy-preserved");
const quotaDir = path.join(dataRoot, "batches/personal-100/chao/right");
await mkdir(quotaDir, { recursive: true });
for (let i = 0; i < 99; i++) {
  await writeFile(path.join(quotaDir, `quota-fixture-${i}.mp4`), "quota-fixture");
  await writeFile(path.join(quotaDir, `quota-fixture-${i}.json`), "{}");
}

const browser = await chromium.launch({
  channel: "chrome", headless: true,
  args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
    `--use-file-for-fake-video-capture=${cameraFile}`],
});
try {
  const context = await browser.newContext({ viewport: { width: 1365, height: 900 }, permissions: ["camera"] });
  await context.addInitScript(() => {
    const NativeSocket = window.WebSocket;
    window.__collectionInferenceCalls = 0;
    class NoInferenceSocket {
      static OPEN = 1;
      readyState = 0;
      onopen = null; onmessage = null; onclose = null; onerror = null;
      constructor(url, protocols) {
        if (!String(url).includes("/ws/inference")) return new NativeSocket(url, protocols);
      }
      send() { window.__collectionInferenceCalls++; throw new Error("Collection must not send inference"); }
      close() { this.readyState = 3; }
    }
    window.WebSocket = NoInferenceSocket;
  });
  const page = await context.newPage();
  const errors = [];
  const submissions = [];
  let failNext = false;
  page.on("pageerror", (e) => errors.push(e.message));
  await page.route("**/collection/summary?batch=personal-100", async (route) => {
    const response = await context.request.get(`${backend}/collection/summary?batch=personal-100`);
    await route.fulfill({ response });
  });
  await page.route("**/collection/samples", async (route) => {
    const payload = route.request().postDataJSON();
    submissions.push(payload);
    assert.equal(payload.batch, "personal-100");
    assert.equal(payload.predicted_label, null);
    if (failNext) {
      failNext = false;
      await route.fulfill({ status: 503, json: { detail: "Lỗi lưu smoke" } });
      return;
    }
    const response = await context.request.post(`${backend}/collection/samples`, { data: payload });
    await route.fulfill({ response });
  });
  await page.goto(process.env.VSIGN_SMOKE_URL || "http://127.0.0.1:5174");
  await page.locator('summary[aria-label="Công cụ"]').click();
  await page.getByRole("button", { name: "Thu dữ liệu AI", exact: true }).click();
  await page.getByRole("button", { name: "Bật camera", exact: true }).click();
  const progress = page.getByRole("progressbar");
  const labelSelect = page.locator("#collection-label");
  await page.getByRole("button", { name: "Bắt đầu thu", exact: true }).waitFor();
  assert.equal(await page.getByRole("button", { name: /Giữ để quay mẫu/ }).count(), 0);

  // Capture real RGB replay frames; the negative label does not require hand tracking.
  await labelSelect.selectOption("Không ký hiệu");
  await page.getByRole("button", { name: "Bắt đầu thu", exact: true }).click();
  await page.waitForFunction(() => Number(document.querySelector('[role="progressbar"]').getAttribute("aria-valuenow")) >= 2,
    null, { timeout: 60000 });
  await page.getByRole("button", { name: "Tạm dừng", exact: true }).click();
  const pausedCount = Number(await progress.getAttribute("aria-valuenow"));
  const pausedSubmissions = submissions.length;
  await page.waitForTimeout(5500);
  assert.equal(submissions.length, pausedSubmissions);
  assert.equal(Number(await progress.getAttribute("aria-valuenow")), pausedCount);
  await page.getByRole("button", { name: "Tiếp tục", exact: true }).click();
  await page.getByRole("button", { name: "Dừng phiên", exact: true }).click();
  await page.reload();
  await page.locator('summary[aria-label="Công cụ"]').click();
  await page.getByRole("button", { name: "Thu dữ liệu AI", exact: true }).click();
  await labelSelect.selectOption("Không ký hiệu");
  await page.waitForFunction((count) => Number(document.querySelector('[role="progressbar"]').getAttribute("aria-valuenow")) === count, pausedCount);
  await page.getByRole("button", { name: "Bật camera", exact: true }).click();

  failNext = true;
  await page.getByRole("button", { name: "Bắt đầu thu", exact: true }).click();
  await page.getByText(/Lỗi lưu smoke/).waitFor({ timeout: 30000 });
  const failedKey = submissions.at(-1).sample_key;
  const afterError = submissions.length;
  await page.waitForTimeout(5500);
  assert.equal(submissions.length, afterError);
  assert.equal(Number(await progress.getAttribute("aria-valuenow")), pausedCount);
  await page.getByRole("button", { name: "Thử lưu lại", exact: true }).click();
  await page.waitForFunction((count) => Number(document.querySelector('[role="progressbar"]').getAttribute("aria-valuenow")) === count + 1, pausedCount);
  assert.equal(submissions.at(-1).sample_key, failedKey);
  await page.getByRole("button", { name: "Dừng phiên", exact: true }).click();

  // The 99 seed files are quota fixtures, not evidence of 99 valid recordings.
  await labelSelect.selectOption("Chào");
  assert.equal(await progress.getAttribute("aria-valuenow"), "99");
  await page.getByRole("button", { name: "Bắt đầu thu", exact: true }).click();
  await page.getByRole("button", { name: "Đã đủ mẫu", exact: true }).waitFor({ timeout: 60000 });
  assert.equal(await progress.getAttribute("aria-valuenow"), "100");
  assert.equal(await page.getByLabel("Từ cần thực hiện").inputValue(), "Chào");
  const finalSubmissions = submissions.length;
  await page.waitForTimeout(5500);
  assert.equal(submissions.length, finalSubmissions);

  const layouts = [];
  for (const width of [320, 390, 768, 1365]) {
    await page.setViewportSize({ width, height: 900 });
    const layout = await page.evaluate(() => ({
      width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
      overflow: [...document.querySelectorAll('.collection-session-actions button,.collection-panel select,.collection-progress-label')]
        .filter((el) => el.scrollWidth > el.clientWidth + 2).map((el) => el.textContent),
    }));
    assert.equal(layout.width, layout.scrollWidth);
    assert.deepEqual(layout.overflow, []);
    layouts.push(layout);
    await page.screenshot({ path: path.join(output, `collection-${width}.png`), fullPage: true });
  }
  const dimensions = await page.evaluate(async (dataUrl) => {
    const image = new Image(); image.src = dataUrl; await image.decode();
    return { width: image.naturalWidth, height: image.naturalHeight };
  }, submissions.at(-1).frames[0]);
  assert.deepEqual(dimensions, { width: 224, height: 224 });
  assert.equal(await readFile(legacy, "utf8"), "legacy-preserved");
  assert.equal((await readdir(quotaDir)).filter((f) => f.endsWith(".mp4")).length, 100);
  assert.equal(await page.evaluate(() => window.__collectionInferenceCalls), 0);
  assert.deepEqual(errors, []);
  const report = {
    passed: true, savedNegativeClips: pausedCount + 1,
    captureFrameCounts: submissions.map((p) => p.frames.length),
    dimensions, layouts, pauseResumeStop: true, reloadProgress: true,
    explicitRetrySameCaptureKey: true, quotaStoppedAt100: true,
    legacyPreserved: true, inferenceRequests: 0, pageErrors: errors,
    note: "Replay camera, real MP4 saves in isolated temporary data. 99 quota files were seeded fixtures. No real-camera quality or model-training claim.",
  };
  await writeFile(path.join(output, "report.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
} finally {
  await browser.close();
}
