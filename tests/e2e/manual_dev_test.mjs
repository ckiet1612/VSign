import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const require = createRequire(process.env.VSIGN_PLAYWRIGHT_FROM || import.meta.url);
const { chromium } = require("playwright");
const camera = process.env.VSIGN_FAKE_CAMERA_FILE;
const backend = process.env.VSIGN_TEST_BACKEND || "http://127.0.0.1:8002";
const output = process.env.VSIGN_SMOKE_OUTPUT || "/tmp/vsign-manual-devtest-smoke";
if (!camera || !process.env.VSIGN_TEST_DATA_ROOT?.startsWith("/tmp/vsign-")) {
  throw new Error("Use replay camera and an isolated /tmp/vsign-* DEV_TEST_DIR backend; never the real test database.");
}
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ channel: "chrome", headless: true, args: [
  "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", `--use-file-for-fake-video-capture=${camera}`,
] });

try {
  const context = await browser.newContext({ viewport: { width: 1365, height: 900 }, permissions: ["camera"] });
  const page = await context.newPage();
  const errors = [], submissions = [], predictions = [];
  page.on("pageerror", error => errors.push(error.message));
  let loseReply = false;
  await page.route("**/dev-tests/trials", async route => {
    if (route.request().method() !== "POST") { await route.continue(); return; }
    const data = route.request().postDataJSON();
    submissions.push(data);
    const response = await context.request.post(`${backend}/dev-tests/trials`, { data });
    assert.equal(response.status(), 200, await response.text());
    const saved = await response.json();
    predictions.push(saved);
    if (loseReply) {
      loseReply = false;
      await route.fulfill({ status: 503, json: { detail: "Smoke: phản hồi bị mất sau khi đã lưu" } });
    } else { await route.fulfill({ response }); }
  });
  const initial = await context.request.get(`${backend}/dev-tests/summary`);
  assert.equal((await initial.json()).recorded, 0, "Smoke database must be empty");
  await page.goto(process.env.VSIGN_SMOKE_URL || "http://127.0.0.1:5174/dev-test");
  await page.getByRole("combobox", { name: "Từ kỳ vọng" }).selectOption("Mua");
  await page.getByRole("textbox", { name: "Người ký", exact: true }).fill("replay-smoke-not-a-real-signer");
  await page.getByRole("button", { name: "Bật camera", exact: true }).click();
  const start = page.getByRole("button", { name: "Bắt đầu test", exact: true });
  await start.waitFor();
  await page.waitForFunction(() => ![...document.querySelectorAll("button")].find(e => e.textContent === "Bắt đầu test")?.disabled);
  const pixels = await page.locator(".dt-camera video").evaluate(video => {
    const canvas = document.createElement("canvas"); canvas.width = canvas.height = 64;
    const ctx = canvas.getContext("2d"); ctx.drawImage(video, 0, 0, 64, 64);
    const values = ctx.getImageData(0, 0, 64, 64).data.filter((_, index) => index % 4 !== 3);
    const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
    return { mean, variance: values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / values.length };
  });
  assert.ok(pixels.variance > 10, "Replay camera must not be blank");

  async function capture(duration = 1200) {
    const before = submissions.length;
    const reply = page.waitForResponse(response => response.url().endsWith("/dev-tests/trials") && response.request().method() === "POST", { timeout: 60000 });
    await start.click();
    assert.equal(await page.getByRole("combobox", { name: "Từ kỳ vọng" }).isDisabled(), true);
    assert.equal(await page.getByRole("button", { name: "Phiên mới", exact: true }).isDisabled(), true);
    await page.waitForTimeout(duration);
    await page.getByRole("button", { name: "Kết thúc test", exact: true }).click();
    await reply;
    await page.waitForFunction(() => {
      const text = document.querySelector('[role="status"]')?.textContent ?? "";
      return text.includes("đã lưu") || text.includes("chưa được xác nhận");
    }, null, { timeout: 60000 });
    assert.equal(submissions.length, before + 1);
  }
  await capture();
  const first = predictions[0];
  assert.equal(submissions[0].expected_label, "Mua");
  assert.equal(submissions[0].frames.length, 16);
  assert.ok(submissions[0].source_frames.length >= 8);
  assert.equal(submissions[0].frames[0], submissions[0].source_frames[0]);
  assert.equal(submissions[0].frames.at(-1), submissions[0].source_frames.at(-1));
  assert.equal(first.mock, false);
  assert.equal(first.never_train, true);
  const frameSize = await page.evaluate(async data => {
    const image = new Image(); image.src = data; await image.decode();
    return { width: image.naturalWidth, height: image.naturalHeight };
  }, submissions[0].frames[0]);
  assert.deepEqual(frameSize, { width: 224, height: 224 });

  await page.getByRole("button", { name: "Xem clip", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Kiểm định clip" });
  await dialog.locator("video").evaluate(async video => {
    await video.play();
    if (video.readyState < 2) await new Promise((resolve, reject) => {
      video.addEventListener("loadeddata", resolve, { once: true }); video.addEventListener("error", reject, { once: true });
    });
  });
  await dialog.getByRole("checkbox", { name: "Clip hợp lệ" }).uncheck();
  await dialog.getByRole("textbox", { name: "Ghi chú" }).fill("Replay mechanics only; exclude from real camera accuracy");
  await dialog.getByRole("button", { name: "Lưu kiểm định" }).click();
  await dialog.waitFor({ state: "hidden" });
  await page.getByText("Loại khỏi thống kê", { exact: true }).waitFor();

  await page.getByRole("combobox", { name: "Từ kỳ vọng" }).selectOption("Không ký hiệu");
  await page.getByRole("combobox", { name: "Chuyển động nền" }).selectOption("random_motion");
  await capture();
  const negative = predictions[1];
  assert.equal(negative.outcome, negative.prediction.status === "ok" ? "false_accept" : "correct_rejection");
  await page.getByRole("combobox", { name: "Từ kỳ vọng" }).selectOption("Mua");
  await capture(10);
  assert.equal(predictions[2].outcome, "technical_error");
  assert.equal(predictions[2].error_stage, "capture");
  assert.equal(predictions[2].prediction, null);

  loseReply = true;
  await capture();
  const pending = submissions.at(-1);
  assert.equal(await start.isDisabled(), true);
  const count = submissions.length;
  await page.waitForTimeout(1200);
  assert.equal(submissions.length, count, "No automatic retry");
  await page.getByRole("button", { name: "Thử lưu lại" }).click();
  await page.getByText("Lượt test đã lưu.", { exact: true }).waitFor();
  assert.deepEqual(submissions.at(-1), pending);
  assert.deepEqual(predictions.at(-1), predictions.at(-2));

  const interruptionReply = page.waitForResponse(response => response.url().endsWith("/dev-tests/trials") && response.request().method() === "POST");
  await start.click();
  await page.waitForTimeout(900);
  await page.locator(".dt-camera video").evaluate(video => {
    const track = video.srcObject.getVideoTracks()[0];
    track.stop(); track.dispatchEvent(new Event("ended"));
  });
  await interruptionReply;
  await page.getByText("Lượt test đã lưu.", { exact: true }).waitFor();
  assert.equal(predictions.at(-1).outcome, "technical_error");
  assert.equal(predictions.at(-1).error_stage, "capture");
  assert.equal(submissions.at(-1).frames.length, 0);

  await page.reload();
  await page.getByText("5 lượt", { exact: true }).waitFor();
  const exported = await context.request.get(`${backend}/dev-tests/export?format=json`);
  const data = await exported.json();
  assert.equal(data.trials.length, 5);
  assert.equal(data.trials.find(trial => trial.trial_id === first.trial_id).outcome, first.outcome);
  assert.equal(data.summary.groups.length, 1);
  const group = data.summary.groups[0];
  assert.equal(group.positive.recorded, 4);
  assert.equal(group.positive.excluded, 1);
  assert.equal(group.positive.technical_error, 2);
  assert.equal(group.positive.evaluated, 1);
  assert.equal(group.negative.evaluated, 1);
  const exactFrames = await context.request.get(`${backend}/dev-tests/trials/${first.trial_id}/frames`);
  assert.deepEqual((await exactFrames.json()).frames, submissions[0].frames);
  const csv = await context.request.get(`${backend}/dev-tests/export?format=csv`);
  assert.equal(csv.status(), 200);
  assert.ok((await csv.text()).includes("replay-smoke-not-a-real-signer"));

  const layouts = [];
  for (const width of [320, 390, 768, 1365]) {
    await page.setViewportSize({ width, height: 900 });
    const layout = await page.evaluate(() => ({ width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
      overflow: [...document.querySelectorAll('.dt-header h1,.dt-camera-actions button,.dt-runtime button,fieldset select')]
        .filter(element => element.scrollWidth > element.clientWidth + 2).map(element => element.textContent) }));
    assert.equal(layout.scrollWidth, width, `Horizontal overflow at ${width}`);
    assert.deepEqual(layout.overflow, []);
    layouts.push(layout);
    await page.screenshot({ path: path.join(output, `manual-test-${width}.png`), fullPage: true });
  }
  await page.getByRole("button", { name: "Xem clip", exact: true }).last().click();
  for (const width of [320, 390, 768, 1365]) {
    await page.setViewportSize({ width, height: 900 });
    const bounds = await page.getByRole("dialog", { name: "Kiểm định clip" }).boundingBox();
    assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= width && bounds.y >= 0 && bounds.y + bounds.height <= 900);
    await page.screenshot({ path: path.join(output, `manual-review-${width}.png`), fullPage: true });
  }
  await page.screenshot({ path: path.join(output, "manual-test-review.png"), fullPage: true });
  assert.deepEqual(errors, []);
  const report = { passed: true, model: first.model_version, backend: first.backend, artifact_sha256: first.artifact_sha256,
    saved: 5, requests: submissions.length, exactFrameEvidence: true, frameSize, pixels, layouts,
    multipleCaptures: true, reviewPreservesPrediction: true, reloadPersistence: true, separateDenominators: true,
    lostReplyRetrySameIdentity: true, noAutomaticRetry: true, simulatedCameraInterruptionTechnical: true, csvJsonExports: true, pageErrors: errors,
    observations: predictions.map(trial => ({ trial_id: trial.trial_id, outcome: trial.outcome, inference_ms: trial.inference_ms })),
    note: "Replay camera mechanics and existing real model only. Not webcam accuracy, unseen-signer quality or a latency benchmark." };
  await writeFile(path.join(output, "report.json"), JSON.stringify(report, null, 2));
  await writeFile(path.join(output, "first-capture.json"), JSON.stringify({ request: submissions[0], trial: first }));
  console.log(JSON.stringify(report, null, 2));
} finally { await browser.close(); }
