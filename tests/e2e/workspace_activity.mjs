import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdtemp, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import net from "node:net";
import os from "node:os";
import path from "node:path";

const require = createRequire(process.env.VSIGN_PLAYWRIGHT_FROM || import.meta.url);
const { chromium } = require("playwright");
const sharp = require("sharp");
const root = process.cwd();
const output = await mkdtemp(path.join(os.tmpdir(), "vsign-activity-"));
async function freePort() {
  const server = net.createServer();
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  return port;
}
const platformPort = await freePort(), webPort = await freePort();
const platform = `http://127.0.0.1:${platformPort}`, url = `http://127.0.0.1:${webPort}`;
const email = "smoke@example.com", password = `Activity-${randomUUID()}`;
const children = [], logs = [];
function start(command, args, options = {}) {
  const child = spawn(command, args, { cwd: root, ...options, stdio: ["ignore", "pipe", "pipe"] });
  child.stdout.on("data", chunk => logs.push(String(chunk)));
  child.stderr.on("data", chunk => logs.push(String(chunk)));
  children.push(child); return child;
}
async function ready(endpoint) {
  for (let i = 0; i < 150; i++) {
    try { if ((await fetch(endpoint)).ok) return; } catch { /* Server is starting. */ }
    await new Promise(resolve => setTimeout(resolve, 200));
  }
  throw new Error(`Server did not start: ${endpoint}`);
}
let browser;
try {
  start(path.join(root, ".venv/bin/python"), ["-c", `
import os, uvicorn
from app.config import Settings
from app.main import create_app
from pathlib import Path
app = create_app(Settings(database_url="sqlite:///" + os.environ["SMOKE_DB"],
  database_auto_create=True, auth_required=False, app_environment="development",
  collection_enabled=True, collection_dir=Path(os.environ["SMOKE_COLLECTION"]),
  allowed_origins=(os.environ["SMOKE_ORIGIN"],), bootstrap_admin_email=os.environ["SMOKE_EMAIL"],
  bootstrap_admin_password=os.environ["SMOKE_PASSWORD"]))
uvicorn.run(app, host="127.0.0.1", port=int(os.environ["SMOKE_PORT"]))
`], { env: { ...process.env, PYTHONPATH: `${root}/services/inference:${root}`,
    SMOKE_DB: path.join(output, "platform.db"), SMOKE_COLLECTION: path.join(output, "collection"),
    SMOKE_ORIGIN: url, SMOKE_EMAIL: email, SMOKE_PASSWORD: password, SMOKE_PORT: String(platformPort) } });
  await ready(`${platform}/health`);
  start(process.execPath, ["node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", String(webPort), "--strictPort"], {
    cwd: path.join(root, "apps/web"), env: { ...process.env, VITE_PLATFORM_HTTP_URL: platform,
      VITE_PLATFORM_AUTH_REQUIRED: "false", VITE_PUBLIC_DEMO: "false",
      VITE_INFERENCE_HTTP_URL: "http://127.0.0.1:8002", VITE_INFERENCE_WS_URL: "ws://127.0.0.1:8002/ws/inference" },
  });
  await ready(url);
  browser = await chromium.launch({ channel: "chrome", headless: true });
  const context = await browser.newContext({ viewport: { width: 1365, height: 900 } });
  const page = await context.newPage();
  const errors = []; page.on("pageerror", error => errors.push(error.message));
  // The isolated frontend uses an ephemeral origin; preserve live inference data with a CORS fixture.
  await page.route(requestUrl => ["8002", "8003"].includes(requestUrl.port) && ["/health", "/metadata"].includes(requestUrl.pathname), async route => {
    const response = await route.fetch();
    await route.fulfill({ response, headers: { ...response.headers(), "access-control-allow-origin": url, "access-control-allow-credentials": "true" } });
  });
  await page.goto(`${url}/?view=activity`);
  await page.getByRole("heading", { name: /Đăng nhập VSign/ }).waitFor();
  assert.equal(await page.getByRole("main").count(), 1);
  assert.equal((await context.request.get(`${platform}/api/v1/workspace/audit/events`)).status(), 401);
  await page.getByRole("button", { name: "Giám sát", exact: true }).click();
  await page.getByRole("main", { name: "Giám sát" }).getByText("Backend đang hoạt động", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Hoạt động", exact: true }).click();
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Mật khẩu", { exact: true }).fill("wrong-password");
  await page.getByRole("button", { name: "Đăng nhập", exact: true }).click();
  await page.getByRole("alert").waitFor();
  await page.getByLabel("Mật khẩu", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Đăng nhập", exact: true }).click();
  const main = page.getByRole("main", { name: "Hoạt động" });
  await main.locator(".activity-row").first().waitFor();
  assert.equal(await main.getByText("Chưa có nguồn nhật ký", { exact: true }).count(), 2);
  await main.getByLabel("Loại hoạt động").selectOption("auth");
  await main.getByLabel("Kết quả").selectOption("failure");
  await main.getByText("auth.login_failed", { exact: true }).waitFor();
  await main.getByLabel("Loại hoạt động").selectOption("model");
  await main.getByLabel("Kết quả").selectOption("");
  await main.getByText("Không có hoạt động phù hợp.", { exact: true }).waitFor();

  // Drop the ACK after the real store commits. Retry must reuse the UUID.
  const ids = []; let drop = true;
  await page.route("**/audit/client-events", async route => {
    ids.push(route.request().postDataJSON().event_id);
    const response = await route.fetch();
    if (drop) { drop = false; await route.abort("connectionreset"); }
    else await route.fulfill({ response });
  });
  await page.locator('summary[aria-label="Cấu hình AI"]').click();
  await page.getByRole("combobox", { name: "Model máy chủ" }).selectOption("seated");
  const retry = page.getByRole("button", { name: "Thử ghi lại nhật ký" });
  await retry.waitFor(); await retry.click();
  await retry.waitFor({ state: "hidden" });
  assert.equal(ids.length, 2); assert.equal(ids[0], ids[1]);
  await main.getByRole("button", { name: "Làm mới hoạt động" }).click();
  await main.getByText("model.switched", { exact: true }).waitFor();
  assert.equal(await main.locator(".activity-row").count(), 1);
  await main.getByText("Trình duyệt báo cáo", { exact: true }).waitFor();
  await main.getByText("Chi tiết", { exact: true }).click();
  const stored = await (await context.request.get(`${platform}/api/v1/workspace/audit/events?group=model`)).json();
  assert.equal(stored.events.length, 1); assert.equal(stored.events[0].event_id, ids[0]);

  for (let i = 0; i < 52; i++) {
    const response = await context.request.post(`${platform}/api/v1/workspace/audit/client-events`, { data: {
      event_id: randomUUID(), event_type: "model.switched", resource_id: randomUUID(),
      model_version: "fixture-new", previous_model_version: "fixture-old", model_option: "seated", previous_model_option: "current",
    } }); assert.equal(response.status(), 201);
  }
  await main.getByRole("button", { name: "Làm mới hoạt động" }).click();
  const more = main.getByRole("button", { name: "Tải thêm", exact: true }); await more.waitFor();
  assert.equal(await main.locator(".activity-row").count(), 50);
  await more.click(); await more.waitFor({ state: "hidden" });
  assert.equal(await main.locator(".activity-row").count(), 53);
  await main.locator(".activity-row summary").first().click();
  const layouts = [];
  for (const width of [320, 390, 768, 1365]) {
    await page.setViewportSize({ width, height: 900 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `Overflow at ${width}`);
    const clipped = await main.locator("input, select, dd, h3").evaluateAll(elements => elements
      .filter(el => el.getBoundingClientRect().width > 0 && el.scrollWidth > el.clientWidth + 2).map(el => el.textContent));
    assert.deepEqual(clipped, [], `Clipped at ${width}`);
    const screenshot = path.join(output, `activity-${width}.png`);
    await page.screenshot({ path: screenshot, fullPage: true });
    assert.ok((await sharp(screenshot).stats()).channels.slice(0, 3).some(channel => channel.stdev > 5));
    layouts.push({ width, screenshot });
  }
  await page.route("**/audit/events?*", route => route.fulfill({ status: 503, json: { detail: "offline fixture" } }));
  await main.getByRole("button", { name: "Làm mới hoạt động" }).click();
  await main.getByRole("alert").filter({ hasText: "dữ liệu cũ" }).waitFor();
  assert.equal(await main.locator(".activity-row").count(), 53);
  await page.unroute("**/audit/events?*");
  await main.getByRole("button", { name: "Làm mới hoạt động" }).click();
  await main.getByRole("alert").waitFor({ state: "hidden" });
  assert.deepEqual(errors, []);
  await writeFile(path.join(output, "report.json"), JSON.stringify({ layouts, errors, retry_ids: ids,
    checks: ["optional-login", "anonymous-monitoring", "real-login-failure-success", "filters", "verified-model-switch",
      "lost-ack-idempotent-retry", "real-keyset-pagination", "responsive-layout-pixels", "stale-recovery"],
    limits: "Isolated temporary database and ephemeral-origin CORS fixture for live inference identity; no training, deployment, webcam or dataset writes." }, null, 2));
  console.log(JSON.stringify({ output, layouts: layouts.length, checks: 9 }));
} catch (error) {
  await writeFile(path.join(output, "server.log"), logs.join(""));
  console.error(`Browser failure evidence: ${output}`);
  if (browser) for (const context of browser.contexts()) for (const page of context.pages()) {
    await page.screenshot({ path: path.join(output, "failure.png"), fullPage: true }).catch(() => {});
  }
  throw error;
} finally {
  await browser?.close();
  await Promise.all(children.map(child => new Promise(resolve => {
    if (child.exitCode !== null) return resolve();
    child.once("exit", resolve); child.kill("SIGTERM");
    const deadline = setTimeout(() => child.kill("SIGKILL"), 3000); deadline.unref();
  })));
}
