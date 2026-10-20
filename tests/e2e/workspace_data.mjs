import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtemp, readFile, realpath, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(process.env.VSIGN_PLAYWRIGHT_FROM || import.meta.url);
const { chromium } = require("playwright"), sharp = require("sharp");
const root = fileURLToPath(new URL("../../", import.meta.url));
const output = await realpath(await mkdtemp(path.join(os.tmpdir(), "vsign-workspace-data-")));
const children = [], logs = [], checks = [], layouts = [], errors = [], writes = [];
const requests = [], requestFailures = [];
let browser, page, failure, finalData;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function port() {
  const server = net.createServer();
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const value = server.address().port;
  await new Promise(resolve => server.close(resolve));
  return [8000, 8002, 8003, 5174].includes(value) ? port() : value;
}
const platformPort = await port();
let webPort = await port();
while (webPort === platformPort) webPort = await port();
const platform = `http://127.0.0.1:${platformPort}`, web = `http://127.0.0.1:${webPort}`;
function start(name, command, args, cwd, env) {
  const child = spawn(command, args, { cwd, env, detached: true, stdio: ["ignore", "pipe", "pipe"] });
  child.once("error", error => errors.push(`${name}: ${error.message}`));
  child.stdout.on("data", chunk => logs.push(`[${name}] ${chunk}`));
  child.stderr.on("data", chunk => logs.push(`[${name}] ${chunk}`));
  children.push(child);
}
async function until(label, operation, duration = 60000) {
  const deadline = Date.now() + duration;
  while (Date.now() < deadline) {
    assert.deepEqual(errors, []);
    for (const child of children) assert.equal(child.exitCode, null, "Isolated server exited");
    if (await operation()) return;
    await sleep(200);
  }
  throw new Error(`Timed out: ${label}`);
}
async function ready(url) {
  await until(url, async () => { try { return (await fetch(url, { signal: AbortSignal.timeout(1000) })).ok; } catch { return false; } });
}
async function json(endpoint) {
  const response = await fetch(`${platform}${endpoint}`);
  assert.equal(response.status, 200, `${endpoint}: ${await response.clone().text()}`);
  return response.json();
}

try {
  start("platform", path.join(root, ".venv/bin/python"), ["-m", "uvicorn", "app.main:app", "--app-dir", "services/inference",
    "--host", "127.0.0.1", "--port", String(platformPort)], root, { ...process.env,
    PYTHONPATH: `${root}/services/inference:${root}`, APP_ENV: "development", AUTH_REQUIRED: "false", LOCAL_ADMIN_ENABLED: "true",
    DATABASE_AUTO_CREATE: "true", DATABASE_URL: `sqlite:///${output}/platform.db`, WORKSPACE_ID: "data-e2e", WORKSPACE_NAME: "Dữ liệu doanh nghiệp",
    INFERENCE_BACKEND: "mock", MODEL_VERSION: "data-e2e-mock", MODEL_MANIFEST_PATH: "", MODEL_DEPLOYMENT_WORKER: "false",
    COLLECTION_ENABLED: "true", COLLECTION_DIR: path.join(output, "media"), ALLOWED_ORIGINS: web, DEV_TEST_ENABLED: "false",
    BOOTSTRAP_ADMIN_EMAIL: "", BOOTSTRAP_ADMIN_PASSWORD: "", OPENAI_API_KEY: "", LABEL_MAP_PATH: "",
  });
  await ready(`${platform}/health`);
  start("web", process.execPath, ["node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", String(webPort), "--strictPort"],
    path.join(root, "apps/web"), { ...process.env, VITE_PLATFORM_HTTP_URL: platform, VITE_INFERENCE_HTTP_URL: platform,
      VITE_INFERENCE_WS_URL: `${platform.replace("http:", "ws:")}/ws/inference`, VITE_PUBLIC_DEMO: "false", VITE_PLATFORM_AUTH_REQUIRED: "false" });
  await ready(web);
  browser = await chromium.launch({ channel: "chrome", headless: true, args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"] });
  const context = await browser.newContext({ viewport: { width: 1365, height: 1000 }, permissions: ["camera"] });
  page = await context.newPage();
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => { requests.push(request.url()); if (!["GET", "HEAD", "OPTIONS"].includes(request.method())) writes.push(request.url()); });
  page.on("requestfailed", request => requestFailures.push({ url: request.url(), error: request.failure()?.errorText }));
  await page.goto(`${web}/?view=data`);
  await page.getByRole("heading", { name: "Dữ liệu", exact: true }).waitFor();
  await page.getByText("Chưa có bộ dữ liệu.", { exact: true }).waitFor();
  assert.equal((await json("/api/v1/auth/me")).auth_mode, "local_admin");
  assert.equal(await page.locator("input[type=password]").count(), 0);
  assert.deepEqual((await json("/api/v1/workspace/data")).datasets, []);
  checks.push("Isolated workspace starts empty with enterprise local admin; no automatic import or login form");

  await page.getByRole("tab", { name: "Danh mục ký hiệu", exact: true }).click();
  await page.getByLabel("Tên phiên bản danh mục", { exact: true }).fill("Sales v1");
  await page.getByRole("button", { name: "Lưu phiên bản danh mục", exact: true }).click();
  await page.getByRole("heading", { name: "Sales v1", exact: true }).waitFor();
  await page.getByRole("tab", { name: "Bộ dữ liệu", exact: true }).click();
  await page.getByLabel("Tên bộ dữ liệu", { exact: true }).fill("Thu dữ liệu thử nghiệm");
  await page.getByRole("button", { name: "Tạo bộ dữ liệu", exact: true }).click();
  await page.getByRole("heading", { name: "Thu dữ liệu thử nghiệm", exact: true }).waitFor();
  await page.getByLabel("Hạn mức Thu dữ liệu thử nghiệm", { exact: true }).fill("1");
  await page.getByRole("button", { name: "Lưu hạn mức Thu dữ liệu thử nghiệm", exact: true }).click();
  await until("quota saved", async () => (await json("/api/v1/workspace/data")).datasets[0]?.quota_per_label === 1);
  const created = await json("/api/v1/workspace/data");
  const datasetId = created.datasets[0].id;
  checks.push("UI creates versioned labels and a draft dataset; real backend stores the per-label quota");

  await page.getByRole("tab", { name: "Thu mẫu", exact: true }).click();
  await page.getByLabel("Bộ dữ liệu đang thu", { exact: true }).selectOption(datasetId);
  await page.getByLabel("Từ cần thực hiện", { exact: true }).selectOption("Không ký hiệu");
  await page.getByRole("button", { name: "Bật camera", exact: true }).click();
  await page.getByRole("button", { name: "Bắt đầu thu", exact: true }).click();
  await until("one actual encoded fake-camera sample", async () => (await json("/api/v1/workspace/data")).datasets[0].sample_count === 1);
  await until("closed collection session", async () => (await json("/api/v1/workspace/data")).sessions[0].state === "completed");
  const captured = await json("/api/v1/workspace/data");
  assert.equal(captured.sessions[0].sample_count, 1);
  assert.equal(captured.datasets[0].counts["Không ký hiệu"].right + captured.datasets[0].counts["Không ký hiệu"].left, 1);
  checks.push("Synthetic camera uses unchanged full-frame capture, persists a real MP4/JSON pair and completes at quota");

  await page.getByRole("tab", { name: "Phiên thu", exact: true }).click();
  await page.getByText("Hoàn tất", { exact: true }).waitFor();
  await page.getByRole("tab", { name: "Bộ dữ liệu", exact: true }).click();
  await page.getByRole("button", { name: "Chốt phiên bản", exact: true }).click();
  await page.getByRole("button", { name: "Xác nhận chốt", exact: true }).click();
  await page.getByText("Bản dữ liệu bất biến", { exact: false }).waitFor();
  finalData = await json("/api/v1/workspace/data");
  const snapshot = finalData.snapshots[0];
  assert.equal(finalData.datasets[0].status, "sealed");
  const manifest = await json(`/api/v1/workspace/data/snapshots/${snapshot.id}/manifest`);
  const snapshotRoot = path.join(output, "media/workspaces/data-e2e/snapshots", snapshot.id);
  const encoded = await readFile(path.join(snapshotRoot, "manifest.json"));
  assert.equal(createHash("sha256").update(encoded).digest("hex"), snapshot.sha256);
  const sample = manifest.samples[0];
  assert.equal(createHash("sha256").update(await readFile(path.join(snapshotRoot, sample.video))).digest("hex"), sample.video_sha256);
  const metadata = JSON.parse(await readFile(path.join(snapshotRoot, sample.video.replace(/\.mp4$/, ".json")), "utf8"));
  assert.ok(metadata.frame_count >= 8 && metadata.frame_count <= 42);
  assert.equal(metadata.expected_label, "Không ký hiệu");
  assert.equal(await page.getByRole("button", { name: "Chốt phiên bản", exact: true }).count(), 0);
  checks.push("UI seals a closed nonempty dataset; copied bytes and manifest SHA256 match; sealed mutations disappear");

  await page.reload();
  await page.getByRole("tab", { name: "Bộ dữ liệu", exact: true }).click();
  await page.getByText("Bản dữ liệu bất biến", { exact: false }).waitFor();
  checks.push("Reload restores authoritative persisted dataset, session and snapshot state");

  for (const [tab, key] of [["Thu mẫu", "collect"], ["Phiên thu", "sessions"], ["Bộ dữ liệu", "datasets"], ["Danh mục ký hiệu", "labels"]]) {
    await page.getByRole("tab", { name: tab, exact: true }).click();
    for (const width of [320, 390, 768, 1365]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.evaluate(() => document.fonts.ready);
      const geometry = await page.evaluate(() => {
        const clipped = [...document.querySelectorAll(".workspace-data h1,.workspace-data h2,.workspace-data button,.workspace-data dd,.workspace-data p")]
          .filter(node => node.getBoundingClientRect().width > 0 && node.scrollWidth > node.clientWidth + 2).map(node => node.textContent);
        return { width: innerWidth, documentWidth: document.documentElement.scrollWidth, clipped };
      });
      assert.ok(geometry.documentWidth <= width, `${tab}: overflow at ${width}`);
      assert.deepEqual(geometry.clipped, [], `${tab}: text clipping at ${width}`);
      const screenshot = path.join(output, `${key}-${width}.png`);
      await page.screenshot({ path: screenshot, fullPage: true });
      const stats = await sharp(screenshot).stats();
      assert.ok(stats.channels.slice(0, 3).some(channel => channel.stdev > 10));
      layouts.push({ tab, width, geometry, screenshot });
    }
  }
  checks.push("Four data views at four widths: nonblank screenshots, no document overflow or measured text clipping");
  const audit = await json("/api/v1/workspace/audit/events");
  assert.ok(audit.events.some(event => event.event_type === "data.snapshot_created"));
  assert.ok(audit.events.some(event => event.event_type === "collection.sample_saved"));
  assert.ok(audit.events.every(event => event.workspace_id === "data-e2e"));
  assert.ok(writes.filter(url => new URL(url).origin === platform).every(url => new URL(url).pathname.startsWith("/api/v1/workspace/data/")));
  assert.ok(!(await json("/api/v1/workspace/models")).permissions.deploy);
  assert.deepEqual(errors, []);
  checks.push("Server records workspace audit; browser never calls legacy collection, client audit or model mutations");
} catch (error) {
  failure = { message: error.message, stack: error.stack };
  if (page && !page.isClosed()) {
    await page.screenshot({ path: path.join(output, "failure.png"), fullPage: true }).catch(() => {});
    await writeFile(path.join(output, "failure.txt"), await page.locator("body").innerText());
    await writeFile(path.join(output, "failure.html"), await page.content());
  }
} finally {
  try { await browser?.close(); } catch (error) { errors.push(`Browser cleanup: ${error.message}`); }
  for (const child of children.reverse()) {
    if (child.exitCode !== null || !child.pid) continue;
    await new Promise(resolve => {
      const timer = setTimeout(() => { try { process.kill(-child.pid, "SIGKILL"); } catch {} }, 10000);
      child.once("exit", () => { clearTimeout(timer); resolve(); });
      try { process.kill(-child.pid, "SIGTERM"); } catch { clearTimeout(timer); resolve(); }
    });
  }
  await writeFile(path.join(output, "server.log"), logs.join(""));
  const report = { status: failure || errors.length ? "failed" : "passed", checks, layouts, errors, writes, requests, requestFailures, finalData,
    failure, platform, web, limits: "Disposable mock inference and synthetic camera; no real samples, training, model mutation or camera-quality acceptance." };
  await writeFile(path.join(output, "report.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ ...report, layouts: layouts.map(({ tab, width, geometry }) => ({ tab, width, geometry })), finalData: undefined, report: path.join(output, "report.json") }, null, 2));
}
if (failure || errors.length) process.exitCode = 1;
