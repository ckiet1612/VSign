import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const require = createRequire(process.env.VSIGN_PLAYWRIGHT_FROM || import.meta.url);
const { chromium } = require("playwright");
const sharp = require("sharp");
const url = process.env.VSIGN_SMOKE_URL || "http://127.0.0.1:5174";
const endpoint = process.env.VSIGN_INFERENCE_URL || "http://127.0.0.1:8002";
const candidateEndpoint = process.env.VSIGN_CANDIDATE_URL || "http://localhost:8003";
const output = process.env.VSIGN_SMOKE_OUTPUT || "/tmp/vsign-workspace-runtime-20261015";
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ channel: "chrome", headless: true });
const errors = [], healthRequests = [], writes = [], layouts = [];
try {
  const context = await browser.newContext({ viewport: { width: 1365, height: 900 } });
  const page = await context.newPage();
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => {
    if (new URL(request.url()).pathname === "/health") healthRequests.push(request.url());
    if (["POST", "PUT", "PATCH", "DELETE"].includes(request.method())) writes.push(request.url());
  });
  const primary = await (await context.request.get(`${endpoint}/metadata`)).json();
  const candidate = await (await context.request.get(`${candidateEndpoint}/metadata`)).json();
  await page.goto(`${url}/?view=overview`);
  await page.getByRole("main", { name: "Tổng quan" }).getByText("Backend đang hoạt động", { exact: true }).waitFor();
  for (const [view, title] of [["overview", "Tổng quan"], ["monitoring", "Giám sát"]]) {
    await page.getByRole("button", { name: title, exact: true }).click();
    const main = page.getByRole("main", { name: title });
    await main.getByText(primary.model_version, { exact: true }).waitFor();
    assert.equal(await main.getByText(`${primary.labels.length} nhãn đã nạp`, { exact: true }).count(), 1);
    assert.equal(await main.getByText(`Protocol ${primary.protocol_version}`, { exact: true }).count(), 1);
    for (const width of [320, 390, 768, 1365]) {
      await page.setViewportSize({ width, height: 900 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `${view} overflows at ${width}`);
      const clipped = await main.locator(".workspace-metric, .workspace-metric strong, .runtime-toolbar, dd").evaluateAll(elements =>
        elements.filter(el => el.scrollWidth > el.clientWidth + 1).map(el => el.textContent));
      assert.deepEqual(clipped, [], `${view} has clipped content at ${width}`);
      const screenshot = path.join(output, `${view}-${width}.png`);
      await page.screenshot({ path: screenshot, fullPage: true });
      const pixels = await sharp(screenshot).stats();
      assert.ok(pixels.channels.slice(0, 3).some(channel => channel.stdev > 5));
      layouts.push({ view, width, screenshot });
    }
  }
  const main = page.getByRole("main", { name: "Giám sát" });
  const refresh = main.getByRole("button", { name: "Làm mới trạng thái runtime" });
  assert.equal(await main.getByText("Chưa có dữ liệu", { exact: true }).count(), 2);
  await main.getByText(`${endpoint}/health`, { exact: true }).waitFor();
  await main.getByText(`Bộ nhãn (${primary.labels.length})`, { exact: true }).click();
  assert.equal(await main.locator(".runtime-labels li").count(), primary.labels.length);
  const pollsBefore = healthRequests.length;
  await page.waitForRequest(request => request.url() === `${endpoint}/health`, { timeout: 12000 });
  assert.ok(healthRequests.length > pollsBefore, "Runtime should poll while visible");
  await page.route("**/health", route => route.abort("connectionrefused"));
  await page.route("**/metadata", route => route.fulfill({ status: 503, body: "unavailable" }));
  await refresh.click();
  await main.getByText("Backend ngoại tuyến", { exact: true }).waitFor();
  assert.match(await main.getByRole("status").innerText(), /Dữ liệu lần đọc trước/);
  await page.screenshot({ path: path.join(output, "monitoring-offline.png"), fullPage: true });
  await page.unroute("**/health");
  await page.unroute("**/metadata");
  await refresh.click();
  await main.getByText("Backend đang hoạt động", { exact: true }).waitFor();
  assert.equal(await main.getByRole("status").count(), 0);

  await page.route("**/metadata", route => route.fulfill({ json: { ...primary, labels: [123] } }));
  await refresh.click();
  await main.getByRole("status").filter({ hasText: "Phản hồi backend không hợp lệ" }).waitFor();
  await page.unroute("**/metadata");
  await refresh.click();
  await main.getByText("Backend đang hoạt động", { exact: true }).waitFor();

  // A stalled network fixture proves the UI deadline, not backend inference latency.
  await page.route("**/health", () => {});
  await refresh.click();
  await main.getByRole("status").filter({ hasText: "Hết thời gian chờ backend" }).waitFor({ timeout: 8000 });
  await page.unroute("**/health");
  await refresh.click();
  await main.getByText("Backend đang hoạt động", { exact: true }).waitFor();

  if (primary.model_version !== candidate.model_version) {
    await page.locator('summary[aria-label="Cấu hình AI"]').click();
    const select = page.getByRole("combobox", { name: "Model máy chủ" });
    await select.selectOption("seated");
    await main.getByText(candidate.model_version, { exact: true }).waitFor();
    await main.getByText(`${candidateEndpoint}/health`, { exact: true }).waitFor();
    await refresh.click();
    await main.getByText("Backend đang hoạt động", { exact: true }).waitFor();
    if (!await select.isVisible()) await page.locator('summary[aria-label="Cấu hình AI"]').click();
    await select.selectOption("current");
    await main.getByText(primary.model_version, { exact: true }).waitFor();
  }
  await page.getByRole("button", { name: "Nhận dạng", exact: true }).click();
  const stoppedAt = healthRequests.length;
  await page.waitForTimeout(10500);
  assert.equal(healthRequests.length, stoppedAt, "No monitoring polling outside runtime pages");
  assert.deepEqual(writes, [], "Monitoring must not submit inference, collections, or mutations");
  assert.deepEqual(errors, []);
  await writeFile(path.join(output, "report.json"), JSON.stringify({
    url, endpoint, primary_model: primary.model_version, candidate_model: candidate.model_version,
    layouts, health_requests: healthRequests, writes, errors,
    checks: ["live-health-metadata", "polling", "refresh", "offline-stale-recovery", "invalid-metadata", "timeout", "selected-endpoint", "polling-cleanup"],
    limits: "Browser/network fixtures verify UI behavior, not camera accuracy or inference latency.",
  }, null, 2));
  console.log(JSON.stringify({ output, layouts: layouts.length, errors, writes }));
} finally {
  await browser.close();
}
