import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";

const require = createRequire(process.env.VSIGN_PLAYWRIGHT_FROM || import.meta.url);
const { chromium } = require("playwright");
const sharp = require("sharp");
const web = process.env.VSIGN_WEB_URL || "http://127.0.0.1:5174";
const platform = process.env.VSIGN_PLATFORM_URL || "http://127.0.0.1:8000";
const output = path.resolve(process.env.VSIGN_E2E_OUTPUT || "tmp/enterprise-admin-browser-20261015");
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ channel: "chrome", headless: true });
const checks = [], layouts = [], errors = [], blockedWrites = [];

try {
  const context = await browser.newContext({ viewport: { width: 1365, height: 900 } });
  // This smoke reads the shared runtime; all browser mutations are blocked.
  await context.route("**/*", async route => {
    const request = route.request();
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method())) {
      blockedWrites.push({ method: request.method(), url: request.url() });
      return route.abort();
    }
    return route.continue();
  });
  await context.addInitScript(() => {
    window.__passwordMounted = false;
    new MutationObserver(() => {
      if (document.querySelector("input[type=password]")) window.__passwordMounted = true;
    }).observe(document, { childList: true, subtree: true });
  });
  const page = await context.newPage();
  page.on("pageerror", error => errors.push(error.message));
  const meResponse = await context.request.get(`${platform}/api/v1/auth/me`);
  assert.equal(meResponse.status(), 200);
  const me = await meResponse.json();
  assert.equal(me.auth_mode, "local_admin");
  assert.equal(me.user.role, "admin");
  assert.equal(me.user.display_name, "Admin local");
  assert.equal(meResponse.headers()["set-cookie"], undefined);
  checks.push("Persisted local admin without login or session cookie");

  const registryResponse = await context.request.get(`${platform}/api/v1/workspace/models`);
  assert.equal(registryResponse.status(), 200);
  const registry = await registryResponse.json();
  assert.ok(Object.values(registry.permissions).every(value => value === false));
  const baselineTarget = registry.target;
  checks.push("Enterprise admin has read access but no technical model permissions");

  for (const [view, heading] of [
    ["models", "Mô hình nhận dạng"], ["activity", "Hoạt động"],
    ["monitoring", "Giám sát"], ["team", "Thành viên & quyền"], ["overview", "Tổng quan"],
  ]) {
    await page.goto(`${web}/?view=${view}`);
    await page.getByRole("heading", { name: heading, exact: true }).waitFor();
    await page.getByText("Admin local", { exact: true }).first().waitFor();
    if (view === "models") await page.getByRole("heading", { name: "Phiên bản đang dùng", exact: true }).waitFor();
    if (view === "activity") await page.getByRole("region", { name: "Nhật ký hoạt động", exact: true }).waitFor();
    assert.equal(await page.locator("input[type=password]").count(), 0);
    assert.equal(await page.getByRole("button", { name: "Đăng xuất", exact: true }).count(), 0);
    assert.equal(await page.evaluate(() => window.__passwordMounted), false);
    assert.ok(await page.getByText("Quản trị doanh nghiệp", { exact: true }).count() >= 1);
    assert.equal(await page.getByLabel("Manifest", { exact: true }).count(), 0);
    assert.equal(await page.getByLabel("Artifact", { exact: true }).count(), 0);
    assert.equal(await page.getByRole("button", { name: /Triển khai|Hoàn tác|Phê duyệt|Đăng ký ứng viên/ }).count(), 0);
    assert.equal(await page.getByRole("combobox", { name: "Model máy chủ" }).count(), 0);
    assert.equal(await page.getByRole("link", { name: "Dev / Test", hidden: true }).count(), 0);
    assert.equal(await page.getByText("Cấu hình AI", { exact: true }).count(), 0);
    const visibleText = await page.getByRole("main").innerText();
    assert.ok(!/https?:\/\/|Protocol |\bBackend\b|\bManifest\b|\bArtifact\b|Dev\/Test|\bRevision\b/.test(visibleText));
    checks.push(`${view}: business identity; no transient login form, logout or technical controls`);
    for (const width of [320, 390, 768, 1365]) {
    await page.setViewportSize({ width, height: 900 });
    await page.evaluate(() => document.fonts.ready);
    const geometry = await page.evaluate(() => ({ width: innerWidth, documentWidth: document.documentElement.scrollWidth }));
    assert.ok(geometry.documentWidth <= width, `Document overflow at ${width}`);
    assert.equal(await page.evaluate(() => window.__passwordMounted), false);
    const screenshot = path.join(output, `${view}-${width}.png`);
    await page.screenshot({ path: screenshot, fullPage: true });
    const stats = await sharp(screenshot).stats();
    const rgbStdev = stats.channels.slice(0, 3).map(channel => channel.stdev);
    assert.ok(rgbStdev.some(value => value > 10), "Blank screenshot");
    layouts.push({ view, width, geometry, rgbStdev, screenshot });
    }
  }
  checks.push("Five views at four widths: nonblank screenshots and no document overflow");
  const finalResponse = await context.request.get(`${platform}/api/v1/workspace/models`);
  assert.equal(finalResponse.status(), 200);
  const finalRegistry = await finalResponse.json();
  assert.deepEqual(finalRegistry.target, baselineTarget);
  assert.deepEqual(finalRegistry.deployments, registry.deployments);
  assert.deepEqual(errors, []);
  assert.deepEqual(blockedWrites, []);
  checks.push("No page errors, browser writes or deployment pointer changes");
  const report = { date: new Date().toISOString(), web, platform, checks, layouts, errors, blockedWrites, auth: me, registry };
  await writeFile(path.join(output, "report.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ checks, layouts: layouts.map(({ width, geometry }) => ({ width, geometry })), report: path.join(output, "report.json") }, null, 2));
} finally {
  await browser.close();
}
