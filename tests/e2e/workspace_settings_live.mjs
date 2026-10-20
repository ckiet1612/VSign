// Read-only smoke verification for an already-running loopback local-admin workspace.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';

const require = createRequire(process.env.VSIGN_PLAYWRIGHT_FROM || import.meta.url);
const { chromium } = require('playwright'), sharp = require('sharp');
const api = process.env.VSIGN_API || 'http://127.0.0.1:8000', web = process.env.VSIGN_WEB || 'http://127.0.0.1:5174';
for (const url of [api, web]) assert.ok(['127.0.0.1', 'localhost'].includes(new URL(url).hostname), 'Loopback only');
const output = process.env.VSIGN_EVIDENCE_DIR || 'tmp/workspace-settings-live-20261016';
await mkdir(output, { recursive: true });
async function read(route) {
  const response = await fetch(api + route, { signal: AbortSignal.timeout(10000) });
  assert.equal(response.status, 200, route); return response.json();
}
assert.equal((await read('/api/v1/auth/me')).auth_mode, 'local_admin');
const before = await read('/api/v1/workspace/settings'), metadata = await read('/metadata');
const writes = [], errors = [], layouts = [];
const browser = await chromium.launch({ channel: 'chrome', headless: true });
let failure;
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/v1/**', route => {
    if (!['GET', 'OPTIONS'].includes(route.request().method())) {
      writes.push({ method: route.request().method(), path: new URL(route.request().url()).pathname }); return route.abort();
    }
    return route.continue();
  });
  await page.goto(web + '/?view=settings'); await page.getByLabel('Tên workspace', { exact: true }).waitFor();
  assert.equal(await page.getByRole('tab').count(), 5);
  for (const width of [1440, 1024, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.getByRole('button', { name: 'Làm mới cài đặt', exact: true }).click();
    await page.locator('#settings-panel[aria-busy=false]').waitFor();
    for (const [key, label] of [['workspace', 'Workspace'], ['retention', 'Retention'], ['collection', 'Thu mẫu'], ['runtime', 'Runtime'], ['notifications', 'Thông báo']]) {
      await page.getByRole('tab', { name: label, exact: true }).click();
      if (key === 'retention') {
        assert.equal(await page.getByLabel('Tự động xóa', { exact: true }).isEnabled(), false);
        await page.getByRole('button', { name: 'Xem trước retention', exact: true }).click();
        await page.getByLabel('Mẫu nháp hết hạn', { exact: true }).waitFor();
      }
      if (key === 'notifications') await page.getByText('Chưa kết nối kênh gửi', { exact: true }).waitFor();
      assert.equal(await page.getByRole('button', { name: 'Lưu cài đặt', exact: true }).isEnabled(), false);
      const layout = await page.evaluate(() => ({
        overflow: document.documentElement.scrollWidth > innerWidth,
        controlsFit: [...document.querySelectorAll('.settings-page input,.settings-page select,.settings-page button')].every(element => {
          const rect = element.getBoundingClientRect(); return rect.width > 0 && rect.x >= 0 && rect.right <= innerWidth + 1;
        }),
        accountFits: [...document.querySelectorAll('.sidebar-account-copy > *')].every(element => element.getBoundingClientRect().right <= element.parentElement.getBoundingClientRect().right + 1),
      }));
      assert.equal(layout.overflow, false, `${key} ${width}`); assert.equal(layout.controlsFit, true); assert.equal(layout.accountFits, true);
      const file = `${output}/${key}-${width}.png`; await page.screenshot({ path: file, fullPage: true });
      assert.ok((await sharp(file).stats()).channels.some(channel => channel.stdev > 15)); layouts.push({ key, width, screenshot: file });
    }
  }
  assert.deepEqual(await read('/api/v1/workspace/settings'), before); assert.deepEqual(await read('/metadata'), metadata);
  assert.deepEqual(writes, []); assert.deepEqual(errors, []);
} catch (error) { failure = error; }
finally {
  await browser.close(); await writeFile(`${output}/report.json`, JSON.stringify({ api, web, checks: failure ? [] : [
    'Five live settings tabs render at five viewport widths with no horizontal overflow, clipped controls or blank screenshots',
    'Retention remains preview-only, delivery remains unavailable, and untouched forms cannot save',
    'No mutating API requests, no page exceptions, settings and inference metadata unchanged',
  ], layouts, writes, errors, failure: failure?.stack ?? null }, null, 2));
}
console.log(JSON.stringify({ output, layouts: layouts.length, writes, errors, failure: failure?.message ?? null }, null, 2));
if (failure) throw failure;
