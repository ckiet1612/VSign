import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";

const require = createRequire(process.env.VSIGN_PLAYWRIGHT_FROM || import.meta.url);
const { chromium } = require("playwright");
const web = process.env.VSIGN_WEB_URL || "http://127.0.0.1:5174";
const platform = process.env.VSIGN_PLATFORM_URL || "http://127.0.0.1:8000";
const output = path.resolve(process.env.VSIGN_E2E_OUTPUT || "tmp/system-admin-browser-20261018");
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ channel: "chrome", headless: true });
const layouts = [], errors = [], blockedWrites = [], checks = [];
const views = {
  overview: "Tổng quan hệ thống", recognize: "Nhận dạng", data: "Dữ liệu & thu mẫu",
  evaluation: "Đánh giá mô hình", monitoring: "Giám sát dịch vụ", models: "Mô hình & triển khai",
  activity: "Nhật ký hệ thống", integrations: "Tích hợp & API", team: "Tài khoản & quyền", settings: "Cấu hình hệ thống",
};

try {
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
  await context.route("**/*", route => {
    const request = route.request();
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method())) {
      blockedWrites.push({ method: request.method(), url: request.url() });
      return route.abort();
    }
    return route.continue();
  });
  const page = await context.newPage();
  page.on("pageerror", error => errors.push(error.message));
  const read = async endpoint => {
    const response = await context.request.get(platform + endpoint);
    assert.equal(response.status(), 200, endpoint);
    return response.json();
  };
  const identity = await read("/api/v1/auth/me");
  assert.equal(identity.user.role, "system_admin");
  const before = await read("/api/v1/workspace/models");
  const metadata = await read("/metadata");
  assert.ok(Object.values(before.permissions).every(Boolean));
  checks.push("Real system identity and lifecycle permissions");
  await page.goto(web);
  await page.getByRole("heading", { name: "Tổng quan hệ thống", exact: true }).waitFor();
  await page.getByText("Hệ thống · Local", { exact: true }).waitFor();
  checks.push("System overview is the default entry");
  checks.push("Passwordless local administration is labeled Local");

  for (let attempt = 0; attempt < 3; attempt++) {
    let releaseIdentity;
    const pendingIdentity = new Promise(resolve => { releaseIdentity = resolve; });
    const delayIdentity = async route => {
      await pendingIdentity;
      await route.continue();
    };
    await page.route("**/api/v1/auth/me", delayIdentity);
    await page.reload({ waitUntil: "domcontentloaded" });
    try {
      await page.getByLabel("Đang tải workspace", { exact: true }).waitFor();
      assert.equal(await page.locator(".app-sidebar").count(), 0);
      assert.equal(await page.getByText("Không gian doanh nghiệp", { exact: true }).count(), 0);
    } finally {
      releaseIdentity();
    }
    await page.getByText("Hệ thống · Local", { exact: true }).waitFor();
    await page.unroute("**/api/v1/auth/me", delayIdentity);
  }
  checks.push("Three reloads with delayed identity never mount enterprise navigation while loading");

  const open = async view => {
    await page.locator(".sidebar-navigation").getByRole("button", { name: views[view], exact: true }).click();
    await page.waitForFunction(view => {
      const url = new URL(location.href);
      return (url.searchParams.get("view") || "recognize") === view;
    }, view);
    await page.waitForLoadState("networkidle");
    await page.waitForFunction(() => !document.querySelector("#workspace [aria-busy=true]"));
    const text = await page.locator("#workspace").innerText();
    assert.ok(!/Không thể tải|Phản hồi .+ không hợp lệ|Bạn không có quyền|Chưa xác nhận quyền workspace/.test(text), `${view}: ${text}`);
  };

  await open("data");
  const data = await read("/api/v1/workspace/data");
  const words = page.getByLabel("Từ cần thực hiện", { exact: true });
  assert.deepEqual(await words.locator("option").evaluateAll(options => options.map(option => option.value)), data.default_labels);
  const previewWord = data.default_labels.find(label => label !== "Không ký hiệu" && label !== data.default_labels[0]);
  assert.ok(previewWord);
  await words.selectOption(previewWord);
  assert.equal(await words.inputValue(), previewWord);
  await page.getByLabel(`Video mẫu cho từ ${previewWord}`, { exact: true }).waitFor();
  assert.equal(await page.getByRole("button", { name: "Bắt đầu thu", exact: true }).isEnabled(), false);
  checks.push("Default collection words can be selected for preview without a dataset or any writes");

  for (const width of [1920, 1440, 1024, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 1080 });
    for (const view of Object.keys(views)) {
      await open(view);
      const geometry = await page.evaluate(() => {
        const main = document.querySelector("#workspace");
        const panel = main.querySelector(".workspace-page,.settings-page,.team-page,.integrations-page,.evaluations-page,.camera-panel");
        const expected = panel.matches(".camera-panel") ? parseFloat(getComputedStyle(main).gridTemplateColumns) : main.getBoundingClientRect().width;
        return { viewport: innerWidth, document: document.documentElement.scrollWidth,
          panel: panel.getBoundingClientRect().width, expected };
      });
      assert.ok(geometry.document <= width + 1, `${width}/${view} overflow: ${JSON.stringify(geometry)}`);
      assert.ok(Math.abs(geometry.panel - geometry.expected) < 2, `${width}/${view} capped width`);
      layouts.push({ view, ...geometry });
      if (width === 1920 || width === 390 && ["models", "team", "settings", "recognize"].includes(view))
        await page.screenshot({ path: path.join(output, `${view}-${width}.png`), fullPage: true });
    }
  }
  checks.push("All ten views at six viewport widths, including mobile admin navigation");

  await page.setViewportSize({ width: 1920, height: 1080 });
  await open("models");
  await page.getByLabel("Manifest", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Đăng ký ứng viên", exact: true }).waitFor();
  checks.push("Internal registry controls are mounted without submitting writes");
  await open("team");
  for (const name of ["Thành viên", "Vai trò", "Lời mời", "Nhật ký quyền"]) {
    await page.getByRole("tab", { name, exact: true }).click();
    await page.waitForLoadState("networkidle");
    assert.ok(!/Không thể tải|Phản hồi .+ không hợp lệ/.test(await page.locator("#workspace").innerText()));
  }
  checks.push("Accounts, role matrix, invitations and permission audit load from real APIs");
  await open("settings");
  for (const name of ["Workspace", "Retention", "Thu mẫu", "Runtime", "Thông báo"]) {
    await page.getByRole("tab", { name, exact: true }).click();
    await page.waitForLoadState("networkidle");
  }
  checks.push("All five configuration sections are reachable");
  await page.getByRole("button", { name: "Thu gọn sidebar", exact: true }).click();
  for (const view of Object.keys(views)) {
    await open(view);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  }
  checks.push("All ten views work with collapsed sidebar");
  const after = await read("/api/v1/workspace/models");
  assert.deepEqual(after.target, before.target);
  assert.deepEqual(after.models, before.models);
  assert.deepEqual(after.deployments, before.deployments);
  assert.deepEqual(await read("/metadata"), metadata);
  assert.deepEqual(blockedWrites, []);
  assert.deepEqual(errors, []);
  const report = { checks, layouts, errors, blockedWrites, modelUnchanged: true, registryUnchanged: true };
  await writeFile(path.join(output, "report.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ output, checks, layouts: layouts.length, errors, blockedWrites }, null, 2));
} finally {
  await browser.close();
}
