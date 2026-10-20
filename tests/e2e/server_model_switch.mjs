import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const require = createRequire(process.env.VSIGN_PLAYWRIGHT_FROM || import.meta.url);
const { chromium } = require("playwright");
const sharp = require("sharp");
const output = process.env.VSIGN_SMOKE_OUTPUT || "/tmp/vsign-server-model-switch";
const normalUrl = process.env.VSIGN_SMOKE_URL || "http://127.0.0.1:5173";
const testUrl = process.env.VSIGN_DEV_TEST_URL || "http://127.0.0.1:5174/dev-test";
const candidateUrl = process.env.VSIGN_CANDIDATE_URL || "http://127.0.0.1:8003";
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ channel: "chrome", headless: true });
const errors = [], sockets = [], layouts = [], measurements = [];
try {
  const context = await browser.newContext({ viewport: { width: 1365, height: 900 } });
  const page = await context.newPage();
  page.on("pageerror", error => errors.push(error.message));
  page.on("websocket", socket => sockets.push(socket.url()));
  const primary = await (await context.request.get("http://127.0.0.1:8000/metadata")).json();
  const candidate = await (await context.request.get(`${candidateUrl}/metadata`)).json();
  const recordedBefore = (await (await context.request.get(`${candidateUrl}/dev-tests/summary`)).json()).recorded;
  assert.notEqual(primary.model_version, candidate.model_version);
  for (const [name, url] of [["recognize", normalUrl], ["manual-test", testUrl]]) {
    await page.goto(url);
    if (name === "recognize") await page.locator('summary[aria-label="Cấu hình AI"]').click();
    const select = page.getByRole("combobox", { name: "Model máy chủ" });
    await page.waitForFunction(() => { const select = document.querySelector('select[aria-label="Model máy chủ"]'); return select && !select.disabled; });
    assert.equal(await select.inputValue(), "current");
    assert.ok((await page.textContent("body")).includes(primary.model_version));
    for (const width of [320, 390, 768, 1365]) {
      await page.setViewportSize({ width, height: 900 });
      await select.selectOption("seated");
      await page.waitForFunction(version => document.body.textContent.includes(version), candidate.model_version);
      await page.waitForFunction(() => { const select = document.querySelector('select[aria-label="Model máy chủ"]'); return select && !select.disabled; });
      assert.equal(await select.inputValue(), "seated");
      const bounds = await select.boundingBox();
      assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= width + 1, "Model selector must fit viewport");
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      const shot = path.join(output, `${name}-${width}.png`);
      await page.screenshot({ path: shot, fullPage: true });
      const pixels = await sharp(shot).stats();
      assert.ok(pixels.channels.slice(0, 3).some(channel => channel.stdev > 5), "Rendered page must not be blank");
      const labelBounds = await page.locator(".server-model-select span").boundingBox();
      const separated = bounds.x >= labelBounds.x + labelBounds.width - 1 || bounds.y >= labelBounds.y + labelBounds.height - 1;
      assert.equal(separated, true, "Selector must not overlap its label");
      layouts.push({ page: name, width, selector: bounds, label: labelBounds, screenshot: shot,
        pixel_stddev: pixels.channels.slice(0, 3).map(channel => channel.stdev) });
      await select.selectOption("current");
      await page.waitForFunction(version => document.body.textContent.includes(version), primary.model_version);
      await page.waitForFunction(() => { const select = document.querySelector('select[aria-label="Model máy chủ"]'); return select && !select.disabled; });
      assert.equal(await select.inputValue(), "current");
    }
    await page.route("**/metadata", async route => {
      if (new URL(route.request().url()).port === "8003") await route.abort("connectionrefused");
      else await route.continue();
    });
    await select.selectOption("seated");
    await page.getByRole("alert").filter({ hasText: "giữ lựa chọn cũ" }).waitFor();
    assert.equal(await select.inputValue(), "current");
    assert.ok((await page.textContent("body")).includes(primary.model_version));
    await page.unroute("**/metadata");
  }
  assert.ok(sockets.some(url => new URL(url).port === "8003"));
  assert.ok(sockets.some(url => new URL(url).port === "8000"));
  assert.deepEqual(errors, []);
  const recordedAfter = (await (await context.request.get(`${candidateUrl}/dev-tests/summary`)).json()).recorded;
  assert.equal(recordedAfter, recordedBefore, "Switch smoke must not create manual camera trials");
  if (process.env.VSIGN_BENCHMARK_FIXTURE) {
    const fixture = JSON.parse(await readFile(process.env.VSIGN_BENCHMARK_FIXTURE, "utf8"));
    const expected = JSON.parse(await readFile(process.env.VSIGN_BENCHMARK_BASELINE, "utf8"));
    assert.equal(fixture.samples.length, expected.samples.length);
    async function measure(url, metadata, name) {
      const ws = new WebSocket(`${url.replace("http", "ws")}/ws/inference`);
      await new Promise((resolve, reject) => { ws.addEventListener("open", resolve, { once: true }); ws.addEventListener("error", reject, { once: true }); });
      const session = crypto.randomUUID(), replies = [];
      try {
        for (let index = 0; index < fixture.samples.length * 2 + 2; index++) {
          const sampleIndex = index < 2 ? index : (index - 2) % fixture.samples.length;
          assert.equal(fixture.samples[sampleIndex].path, expected.samples[sampleIndex].path);
          const data = JSON.stringify({ type: "frames", session_id: session, sequence: index,
            captured_at: Date.now(), frames: fixture.samples[sampleIndex].frames });
          const started = performance.now();
          const reply = await new Promise((resolve, reject) => {
            const timer = setTimeout(() => reject(new Error("Inference timed out")), 60000);
            ws.addEventListener("message", event => { clearTimeout(timer); resolve(JSON.parse(event.data)); }, { once: true });
            ws.send(data);
          });
          assert.equal(reply.sequence, index);
          assert.equal(reply.model_version, metadata.model_version);
          assert.ok(["ok", "uncertain"].includes(reply.status));
          assert.notEqual(reply.label, "Không ký hiệu");
          if (index >= 2) replies.push({ path: fixture.samples[sampleIndex].path,
            expected: expected.samples[sampleIndex].expected_label, elapsed_ms: performance.now() - started, reply });
        }
      } finally { ws.close(); }
      const times = replies.map(item => item.elapsed_ms).sort((a, b) => a - b);
      const percentile = p => { const i = (times.length - 1) * p, low = Math.floor(i), high = Math.ceil(i);
        return times[low] + (times[high] - times[low]) * (i - low); };
      const positives = replies.filter(item => item.expected !== "Không ký hiệu");
      const negatives = replies.filter(item => item.expected === "Không ký hiệu");
      const result = { name, model_version: metadata.model_version, backend: metadata.backend,
        median_ms: percentile(.5), p95_ms: percentile(.95), requests: replies.length,
        positive_samples: positives.length, positive_correct_accepts: positives.filter(item => item.reply.status === "ok" && item.reply.label === item.expected).length,
        negative_samples: negatives.length, negative_false_accepts: negatives.filter(item => item.reply.status === "ok").length, replies };
      measurements.push(result);
      console.log(JSON.stringify({ name, median_ms: result.median_ms, p95_ms: result.p95_ms, requests: replies.length }));
    }
    await measure("http://127.0.0.1:8000", primary, "current_before");
    await measure(candidateUrl, candidate, "seated_personal");
    await measure("http://127.0.0.1:8000", primary, "current_after");
  }
  const report = { passed: true, primary_version: primary.model_version, candidate_version: candidate.model_version,
    errors, sockets, layouts, recordedBefore, recordedAfter, measurements, real_camera_used: false,
    predictions_tested: measurements.length > 0,
    limits: "Two warmups, serial 40-request endpoint brackets on identical encoded training clips. Not independent accuracy, load or camera-to-result latency." };
  await writeFile(path.join(output, "report.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ passed: true, screenshots: layouts.length, recordedBefore, recordedAfter }));
} finally { await browser.close(); }
