import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const require = createRequire(process.env.VSIGN_PLAYWRIGHT_FROM || import.meta.url);
const { chromium } = require("playwright");
const cameraFile = process.env.VSIGN_FAKE_CAMERA_FILE;
if (!cameraFile) throw new Error("Set VSIGN_FAKE_CAMERA_FILE to a replay .y4m camera.");
const output = process.env.VSIGN_SMOKE_OUTPUT || "/tmp/vsign-automatic-sentence-smoke";
await mkdir(output, { recursive: true });
const labels = ["Tôi", "Muốn", "Mua", "Tủ lạnh", "Rẻ"];
const fixtureLabels = [...labels, "Laptop", "Mới", "Cũ", "Sữa"];
const version = "automatic-sentence-fixture";
const browser = await chromium.launch({ channel: "chrome", headless: true, args: [
  "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
  `--use-file-for-fake-video-capture=${cameraFile}`,
] });
try {
  const context = await browser.newContext({ viewport: { width: 1365, height: 900 }, permissions: ["camera"] });
  await context.addInitScript(({ version }) => {
    const NativeSocket = window.WebSocket;
    window.__sentenceRequests = [];
    class FixtureSocket {
      readyState = 1;
      onopen = null;
      onmessage = null;
      onclose = null;
      constructor(url, protocols) {
        if (!String(url).includes("/ws/inference")) return new NativeSocket(url, protocols);
        queueMicrotask(() => this.onopen?.(new Event("open")));
      }
      send(data) { window.__sentenceRequests.push({ payload: JSON.parse(data), socket: this }); }
      close() { this.readyState = 3; }
    }
    window.WebSocket = FixtureSocket;
    window.__replySentence = (sequence, label, status = "ok") => {
      const request = window.__sentenceRequests.find(item => item.payload.sequence === sequence);
      if (!request) throw new Error(`Missing request ${sequence}`);
      request.socket.onmessage?.(new MessageEvent("message", { data: JSON.stringify({
        type: "prediction", sequence, status, label: status === "ok" ? label : null,
        confidence: status === "ok" ? .95 : null, top_k: [{ label, confidence: .95 }], model_version: version,
      }) }));
    };
  }, { version });
  const page = await context.newPage();
  const errors = [], compositions = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => {
    if (request.url().endsWith("/sentence/compose")) compositions.push(request.postDataJSON());
  });
  await page.route("**/metadata", route => route.fulfill({ json: {
    backend: "coreml", model_version: version, protocol_version: "1.0", labels: fixtureLabels,
    frame_count: 16, frame_width: 224, frame_height: 224, supported_image_formats: ["image/jpeg", "image/webp"],
    confidence_threshold: .7, margin_threshold: .15, candidate_labels_unverified: false,
    mock: false, collection_enabled: false, sentence_ai_enabled: false,
  } }));
  // Test-only raw trajectories exercise the real segmenter, encoder and FIFO.
  await page.route("**/src/components/HandTrackingOverlay.tsx*", async route => {
    const original = await (await route.fetch()).text();
    const reactURL = original.match(/from "(\/node_modules\/\.vite\/deps\/react\.js[^"\n]*)"/)[1];
    await route.fulfill({ contentType: "application/javascript", body: `
      import React from ${JSON.stringify(reactURL)};
      import { emptyLandmarkFrame, HAND_GLOBAL_OFFSET, HAND_PRESENCE_OFFSET } from "/src/lib/landmarkFeatures.ts";
      export function HandTrackingOverlay(props) {
        const latest = React.useRef(props); latest.current = props;
        React.useEffect(() => {
          let x = .2, gesture = null;
          window.__sentenceGesture = () => {
            if (gesture) throw new Error("Gesture already running");
            gesture = { start: performance.now(), from: x, to: x < .4 ? .675 : .2 };
          };
          const timer = setInterval(() => {
            if (!latest.current.active) return;
            const now = performance.now();
            if (gesture) {
              const elapsed = now - gesture.start;
              const ratio = Math.min(1, Math.max(0, (elapsed - 800) / 1000));
              x = gesture.from + (gesture.to - gesture.from) * ratio;
              if (elapsed >= 2800) gesture = null;
            }
            window.__sentenceGestureBusy = !!gesture;
            const features = emptyLandmarkFrame();
            for (let point = 0; point < 21; point++) {
              features[point * 3] = x + point * .001;
              features[point * 3 + 1] = .5;
            }
            features[HAND_GLOBAL_OFFSET] = x;
            features[HAND_GLOBAL_OFFSET + 1] = .5;
            features[HAND_PRESENCE_OFFSET] = 1;
            latest.current.onTrackingFrame({ features, baselineFeatures: new Array(128).fill(0),
              crop: null, handCount: 1, updatedAt: now });
          }, 50);
          return () => clearInterval(timer);
        }, []);
        return null;
      }
    ` });
  });
  await page.goto(process.env.VSIGN_SMOKE_URL || "http://localhost:5173");
  await page.getByRole("button", { name: "Bật camera", exact: true }).click();
  await page.getByText("Cách thu", { exact: true }).click();
  await page.getByText("Cách thêm từ", { exact: true }).click();
  await page.getByRole("button", { name: "Tự động beta", exact: true }).click();
  await page.getByRole("radio", { name: "Thêm từ tự động" }).click();
  await page.waitForFunction(() => document.querySelector("video")?.readyState >= 2);
  const transcript = page.getByRole("region", { name: "Câu của bạn" });

  async function sign(label, reply = true, status = "ok") {
    await page.waitForFunction(() => !window.__sentenceGestureBusy);
    const count = await page.evaluate(() => window.__sentenceRequests.length);
    await page.evaluate(() => window.__sentenceGesture());
    await page.waitForFunction(count => window.__sentenceRequests.length > count, count, { timeout: 15000 });
    const sequence = await page.evaluate(count => window.__sentenceRequests[count].payload.sequence, count);
    if (reply) await page.evaluate(({ sequence, label, status }) => window.__replySentence(sequence, label, status), { sequence, label, status });
    return sequence;
  }

  for (const label of labels.slice(0, 4)) await sign(label);
  const suffix = await sign("Rẻ", false);
  // Intentional held model response, longer than the sentence-pause threshold.
  await new Promise(resolve => setTimeout(resolve, 2300));
  assert.equal(compositions.length, 0);
  await page.evaluate(sequence => window.__replySentence(sequence, "Rẻ"), suffix);
  await transcript.getByText("Tôi muốn mua tủ lạnh rẻ.", { exact: true }).waitFor();
  assert.deepEqual(compositions[0].words, labels);
  assert.equal(await transcript.getByText("Dự thảo · chưa xác nhận", { exact: true }).isVisible(), true);
  await page.screenshot({ path: path.join(output, "complete-draft-desktop.png"), fullPage: true });

  const layouts = [];
  for (const width of [320, 390, 768, 1365]) {
    await page.setViewportSize({ width, height: 900 });
    const layout = await page.evaluate(() => ({
      width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
      overflow: [...document.querySelectorAll(".sentence-draft,.sentence-draft p,.sentence-draft span")]
        .filter(element => element.scrollWidth > element.clientWidth + 2).map(element => element.textContent),
    }));
    assert.equal(layout.width, layout.scrollWidth);
    assert.deepEqual(layout.overflow, []);
    layouts.push(layout);
    await page.screenshot({ path: path.join(output, `draft-${width}.png`), fullPage: true });
  }

  // No transcript clear between sentences: a warning must affect only its owner.
  await new Promise(resolve => setTimeout(resolve, 5200));
  await sign("Mua");
  await transcript.getByText("Mua.", { exact: true }).waitFor();
  assert.equal(await transcript.getByText("Tôi muốn mua tủ lạnh rẻ.", { exact: true }).isVisible(), true);
  await new Promise(resolve => setTimeout(resolve, 5200));
  await sign("Rẻ", true, "uncertain");
  await transcript.getByText("Có đoạn chưa nhận dạng · cần kiểm tra", { exact: true }).waitFor();
  await new Promise(resolve => setTimeout(resolve, 5200));
  await sign("Tủ lạnh");
  await transcript.getByText("Tủ lạnh.", { exact: true }).waitFor();
  assert.equal(await transcript.locator(".sentence-draft").count(), 4);
  assert.equal(await transcript.getByText("Có đoạn chưa nhận dạng · cần kiểm tra", { exact: true }).isVisible(), true);
  await page.screenshot({ path: path.join(output, "continuous-sentences.png"), fullPage: true });
  const continuousSentences = await transcript.locator(".sentence-draft").allTextContents();

  // Start a separate operator test session; two captured sentences wait in FIFO.
  await transcript.getByRole("button", { name: "Xóa toàn bộ câu" }).click();
  const beforeDelayed = compositions.length;
  const heldFirst = await sign("Mua", false);
  await new Promise(resolve => setTimeout(resolve, 5200));
  const queuedSecond = sign("Tủ lạnh", false);
  await page.waitForFunction(() => window.__sentenceGestureBusy);
  await page.waitForFunction(() => !window.__sentenceGestureBusy);
  assert.equal(compositions.length, beforeDelayed);
  await page.evaluate(sequence => window.__replySentence(sequence, "Mua"), heldFirst);
  const secondSequence = await queuedSecond;
  await page.evaluate(sequence => window.__replySentence(sequence, "Tủ lạnh"), secondSequence);
  await transcript.getByText("Mua.", { exact: true }).waitFor();
  await transcript.getByText("Tủ lạnh.", { exact: true }).waitFor();
  assert.deepEqual(compositions.slice(beforeDelayed).map(item => item.words), [["Mua"], ["Tủ lạnh"]]);
  await page.screenshot({ path: path.join(output, "delayed-sentence-ownership.png"), fullPage: true });

  await transcript.getByRole("button", { name: "Xóa toàn bộ câu" }).click();
  const beforeRepeated = compositions.length;
  const repeatedFirst = await sign("Mua", false);
  await new Promise(resolve => setTimeout(resolve, 5200));
  const repeatedSecond = sign("Mua", false);
  await page.waitForFunction(() => window.__sentenceGestureBusy);
  await page.waitForFunction(() => !window.__sentenceGestureBusy);
  await page.evaluate(sequence => window.__replySentence(sequence, "Mua"), repeatedFirst);
  const repeatedSequence = await repeatedSecond;
  await page.evaluate(sequence => window.__replySentence(sequence, "Mua"), repeatedSequence);
  await page.waitForFunction(() => [...document.querySelectorAll(".sentence-draft p")]
    .filter(element => element.textContent === "Mua.").length === 2);
  assert.deepEqual(compositions.slice(beforeRepeated).map(item => item.words), [["Mua"], ["Mua"]]);

  await transcript.getByRole("button", { name: "Xóa toàn bộ câu" }).click();
  const beforeUncertain = compositions.length;
  await sign("Mua");
  await sign("Rẻ", true, "uncertain");
  await transcript.getByText("Có đoạn chưa nhận dạng · cần kiểm tra", { exact: true }).waitFor();
  await new Promise(resolve => setTimeout(resolve, 2300));
  assert.equal(compositions.length, beforeUncertain + 1);
  assert.deepEqual(compositions.at(-1).words, ["Mua"]);
  await transcript.getByText("Mua.", { exact: true }).waitFor();
  await page.screenshot({ path: path.join(output, "missing-qualifier.png"), fullPage: true });

  await transcript.getByRole("button", { name: "Xóa toàn bộ câu" }).click();
  for (const label of ["Laptop", "Mới", "Cũ"]) await sign(label);
  await transcript.getByText("Laptop mới cũ.", { exact: true }).waitFor();
  await transcript.getByText("Cấu trúc chưa rõ · giữ nguyên thứ tự, cần kiểm tra", { exact: true }).waitFor();
  for (const width of [320, 390, 768, 1365]) {
    await page.setViewportSize({ width, height: 900 });
    const overflow = await page.evaluate(() => [...document.querySelectorAll(".sentence-draft,.sentence-draft p,.sentence-draft span")]
      .filter(element => element.scrollWidth > element.clientWidth + 2).map(element => element.textContent));
    assert.deepEqual(overflow, []);
    await page.screenshot({ path: path.join(output, `grammar-review-${width}.png`), fullPage: true });
  }
  await new Promise(resolve => setTimeout(resolve, 5200));
  await sign("Sữa");
  await transcript.getByText("Sữa.", { exact: true }).waitFor();
  assert.equal(await transcript.getByText("Laptop mới cũ.", { exact: true }).isVisible(), true);
  assert.equal(await transcript.locator(".sentence-draft").count(), 2);
  const requests = await page.evaluate(() => window.__sentenceRequests.map(({ payload }) => ({
    sequence: payload.sequence, frameCount: payload.frames.length,
  })));
  assert.ok(requests.every(item => item.frameCount === 16));
  assert.deepEqual(errors, []);
  const report = { passed: true, requests, compositions, layouts, pageErrors: errors,
    heldSuffixIncluded: true, uncertainSuffixCreatesBestEffortReview: true, customerWebActions: 0,
    continuousSentences, continuousSentenceCount: 4, recoveryWithoutClear: true, delayedSentenceOwnership: true,
    repeatedDelayedWordPreserved: true,
    grammarReviewDoesNotBlockNextSentence: true,
    limits: "Operator configures once; raw tracking and prediction fixtures with a replay camera and real sentence API. Not real webcam/model accuracy, language boundary accuracy or production acceptance." };
  await writeFile(path.join(output, "report.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
} finally { await browser.close(); }
