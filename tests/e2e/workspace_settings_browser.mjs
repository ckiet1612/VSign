import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { writeFile } from 'node:fs/promises';

export async function verifySettingsBrowser({ api, web, output, metadata }) {
  const require = createRequire(process.env.VSIGN_PLAYWRIGHT_FROM || import.meta.url);
  const { chromium } = require('playwright'), sharp = require('sharp');
  const checks = [], layouts = [], errors = [], writes = [], base = '/api/v1/workspace/settings';
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const owner = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await owner.newPage(); page.on('pageerror', error => errors.push(error.message));
  let failure;
  async function read(context, route = base) {
    const response = await context.request.get(api + route); assert.equal(response.status(), 200, await response.text()); return response.json();
  }
  async function login(target, email) {
    await target.goto(web + '/?view=settings'); await target.getByLabel('Email', { exact: true }).fill(email);
    await target.getByLabel('Mật khẩu', { exact: true }).fill('fixture-password-12345');
    await target.getByRole('button', { name: 'Đăng nhập', exact: true }).click();
    await target.locator('#settings-panel[aria-busy=false]').waitFor();
  }
  async function tab(label) {
    await page.getByRole('tab', { name: label, exact: true }).click(); await page.locator('#settings-panel[aria-busy=false]').waitFor();
  }
  async function save() {
    const response = page.waitForResponse(response => response.url().startsWith(api + base) && response.request().method() === 'POST');
    await page.getByRole('button', { name: 'Lưu cài đặt', exact: true }).click();
    const result = await response; assert.equal(result.status(), 200, await result.text());
    writes.push({ path: new URL(result.url()).pathname, body: result.request().postDataJSON() });
    await page.getByText('Đã lưu cài đặt.', { exact: true }).waitFor();
  }
  async function fresh() {
    const response = page.waitForResponse(response => response.url() === api + base && response.request().method() === 'GET');
    await page.getByRole('button', { name: 'Làm mới cài đặt', exact: true }).click(); await response;
    await page.locator('#settings-panel[aria-busy=false]').waitFor();
  }
  try {
    await login(page, 'owner@example.com'); assert.equal(await page.getByRole('tab').count(), 5);
    const longName = 'Workspace kiểm chứng giai đoạn 8 với tên tiếng Việt dài dành cho kiểm tra bố cục';
    await page.getByLabel('Tên workspace', { exact: true }).fill(longName);
    await page.getByLabel('Múi giờ', { exact: true }).fill('Asia/Ho_Chi_Minh'); await save();
    assert.equal((await read(owner, '/api/v1/workspace')).name, longName);
    await tab('Retention'); await page.getByLabel('Mẫu nháp (ngày)', { exact: true }).fill('30');
    await page.getByLabel('Nhật ký hoạt động (ngày)', { exact: true }).fill('90'); await save();
    assert.equal(await page.getByLabel('Tự động xóa', { exact: true }).isEnabled(), false);
    await page.getByRole('button', { name: 'Xem trước retention', exact: true }).click();
    await page.getByLabel('Mẫu nháp hết hạn', { exact: true }).waitFor();
    assert.equal(await page.getByLabel('Mẫu nháp hết hạn', { exact: true }).innerText(), '0');
    assert.equal(await page.getByRole('button', { name: /^Xóa/ }).count(), 0);
    await tab('Thu mẫu'); await page.getByLabel('Yêu cầu đồng ý lưu mẫu', { exact: true }).check();
    await page.getByLabel('Hạn mức mặc định mỗi ký hiệu', { exact: true }).fill('17'); await save();
    await tab('Runtime'); await page.getByRole('combobox', { name: 'Chế độ thu nhận dạng mặc định', exact: true }).selectOption('automatic'); await save();
    await tab('Thông báo'); await page.getByLabel('Hoàn tất thu mẫu', { exact: true }).uncheck(); await save();
    const saved = await read(owner);
    assert.equal(saved.revision, 4); assert.equal(saved.notifications.revision, 1);
    assert.equal(saved.collection_policy.default_quota_per_label, 17); assert.equal(saved.retention.automatic_deletion, false);
    assert.equal(saved.notifications.delivery, 'not_configured');
    await page.reload(); await page.getByLabel('Tên workspace', { exact: true }).waitFor();
    assert.equal(await page.getByLabel('Tên workspace', { exact: true }).inputValue(), longName);
    checks.push('All five groups save through real APIs, reload persists name, retention never deletes, and preference revision is independent');

    await page.getByLabel('Tên workspace', { exact: true }).fill('Bản nháp đang chỉnh sửa');
    const conflict = await owner.request.post(api + base + '/update', { data: { request_id: crypto.randomUUID(), expected_revision: 4,
      workspace: { name: longName, timezone: 'UTC' } } }); assert.equal(conflict.status(), 200);
    await fresh(); assert.equal(await page.getByLabel('Tên workspace', { exact: true }).inputValue(), 'Bản nháp đang chỉnh sửa');
    await page.getByText('Có phiên bản mới hơn.', { exact: true }).waitFor();
    const rejected = page.waitForResponse(response => response.url() === api + base + '/update' && response.request().method() === 'POST');
    await page.getByRole('button', { name: 'Lưu cài đặt', exact: true }).click(); assert.equal((await rejected).status(), 409);
    await page.getByRole('alert').waitFor(); await fresh();
    await page.getByRole('button', { name: 'Nạp phiên bản mới', exact: true }).click();
    assert.equal(await page.getByLabel('Tên workspace', { exact: true }).inputValue(), longName);
    checks.push('Dirty draft survives refresh; stale revision is rejected; explicit reload recovers without overwriting another client');

    await tab('Thông báo'); const retriedBodies = []; let dropped = false;
    await page.route(api + base + '/notifications', async route => {
      retriedBodies.push(route.request().postDataJSON());
      if (!dropped) { dropped = true; const response = await route.fetch(); assert.equal(response.status(), 200); await route.abort('failed'); }
      else await route.continue();
    });
    await page.getByLabel('Hoàn tất thu mẫu', { exact: true }).check();
    await page.getByRole('button', { name: 'Lưu cài đặt', exact: true }).click();
    await page.getByRole('button', { name: 'Thử lại thao tác lưu', exact: true }).waitFor();
    await fresh();
    await page.getByRole('button', { name: 'Thử lại thao tác lưu', exact: true }).click();
    await page.getByRole('button', { name: 'Thử lại thao tác lưu', exact: true }).waitFor({ state: 'detached' });
    assert.equal(retriedBodies.length, 2); assert.deepEqual(retriedBodies[0], retriedBodies[1]);
    assert.equal((await read(owner)).notifications.revision, 2); await page.unroute(api + base + '/notifications');
    checks.push('Lost successful ACK retains exact request ID/body across refresh; explicit retry does not increment preference revision twice');

    const recognize = await owner.newPage(); recognize.on('pageerror', error => errors.push(error.message));
    await recognize.goto(web + '/?view=recognize');
    await recognize.getByRole('button', { name: 'Tự động beta', exact: true }).waitFor();
    await recognize.waitForFunction(() => [...document.querySelectorAll('button')].some(button => button.textContent.includes('Tự động') && button.getAttribute('aria-pressed') === 'true'));
    await recognize.getByRole('button', { name: 'Thủ công', exact: true }).click();
    await page.goto(web + '/?view=settings'); await page.getByLabel('Tên workspace', { exact: true }).waitFor();
    await tab('Runtime'); await page.getByRole('combobox', { name: 'Chế độ thu nhận dạng mặc định', exact: true }).selectOption('manual'); await save();
    assert.equal(await recognize.getByRole('button', { name: 'Thủ công', exact: true }).getAttribute('aria-pressed'), 'true');
    await recognize.close();
    checks.push('A fresh recognition page consumes runtime default; manual session choice survives a subsequent settings save; camera is not started');

    const labelsId = crypto.randomUUID(), datasetId = crypto.randomUUID();
    let response = await owner.request.post(api + '/api/v1/workspace/data/labels', { data: { request_id: labelsId, name: 'Danh mục fixture',
      entries: [{ id: crypto.randomUUID(), name: 'Cho', kind: 'sign' }] } }); assert.equal(response.status(), 201);
    response = await owner.request.post(api + '/api/v1/workspace/data/datasets', { data: { request_id: datasetId, name: 'Dữ liệu fixture', label_version_id: labelsId } });
    assert.equal(response.status(), 201); assert.equal((await response.json()).datasets[0].quota_per_label, 17);
    await page.goto(web + '/?view=data'); await page.getByRole('combobox', { name: 'Bộ dữ liệu đang thu', exact: true }).selectOption(datasetId);
    const consent = page.getByRole('checkbox', { name: 'Tôi đồng ý lưu video và dữ liệu mẫu cho workspace này.', exact: true });
    assert.equal(await consent.isChecked(), false); await consent.check();
    // No camera/media operation is performed by this workflow.
    assert.equal(await page.getByRole('button', { name: 'Bắt đầu thu', exact: true }).isEnabled(), false);
    checks.push('New dataset inherits quota 17 and required consent is opt-in; no camera capture or real media is used');

    await page.goto(web + '/?view=settings'); await page.getByLabel('Tên workspace', { exact: true }).waitFor();
    for (const width of [1440, 1024, 768, 390, 320]) {
      await page.setViewportSize({ width, height: 1000 }); await fresh();
      for (const [key, label] of [['workspace', 'Workspace'], ['retention', 'Retention'], ['collection', 'Thu mẫu'], ['runtime', 'Runtime'], ['notifications', 'Thông báo']]) {
        await tab(label);
        if (key === 'retention') { await page.getByRole('button', { name: 'Xem trước retention', exact: true }).click(); await page.getByLabel('Mẫu nháp hết hạn', { exact: true }).waitFor(); }
        const file = `${output}/${key}-${width}.png`; await page.screenshot({ path: file, fullPage: true });
        const layout = await page.evaluate(() => ({ overflow: document.documentElement.scrollWidth > innerWidth,
          width: document.querySelector('.settings-page').getBoundingClientRect().width,
          accountFits: [...document.querySelectorAll('.sidebar-account-copy > *')].every(e => {
            const r = e.getBoundingClientRect(), parent = e.parentElement.getBoundingClientRect();
            return r.right <= parent.right + 1;
          }),
          controls: [...document.querySelectorAll('.settings-page input,.settings-page select,.settings-page button')].every(e => {
            const r = e.getBoundingClientRect(); return r.width > 0 && r.x >= 0 && r.right <= innerWidth + 1;
          }) }));
        assert.equal(layout.overflow, false, `${key} ${width}`); assert.equal(layout.controls, true, `${key} controls ${width}`);
        assert.equal(layout.accountFits, true, `${key} account ${width}`);
        assert.ok((await sharp(file).stats()).channels.some(channel => channel.stdev > 15)); layouts.push({ tab: key, width, screenshot: file });
      }
    }
    checks.push('Five settings views at five widths render nonblank, with no document overflow or offscreen controls');

    const invited = await owner.request.post(api + '/api/v1/workspace/team/invitations', { data: { request_id: crypto.randomUUID(), email: 'viewer@example.com', role: 'viewer' } });
    assert.equal(invited.status(), 201); const invitation = await invited.json();
    const viewer = await browser.newContext({ viewport: { width: 390, height: 900 } });
    const accepted = await viewer.request.post(api + '/api/v1/invitations/accept', { data: { token: invitation.secret, request_id: crypto.randomUUID(),
      password: 'fixture-password-12345', display_name: 'Người xem fixture' } }); assert.equal(accepted.status(), 200);
    const viewerPage = await viewer.newPage(); viewerPage.on('pageerror', error => errors.push(error.message));
    await login(viewerPage, 'viewer@example.com'); await viewerPage.getByLabel('Hoàn tất thu mẫu', { exact: true }).waitFor();
    assert.equal(await viewerPage.getByRole('tab').count(), 1); assert.equal(await viewerPage.getByLabel('Tên workspace', { exact: true }).count(), 0);
    assert.equal((await viewer.request.post(api + base + '/update', { data: {} })).status(), 403);
    await viewerPage.getByLabel('Lỗi tích hợp', { exact: true }).uncheck();
    await viewerPage.getByRole('button', { name: 'Lưu cài đặt', exact: true }).click();
    await viewerPage.getByText('Đã lưu cài đặt.', { exact: true }).waitFor();
    assert.equal((await read(viewer)).notifications.preferences.integration_failed, false);
    assert.equal((await read(owner)).notifications.preferences.integration_failed, true);
    await viewerPage.screenshot({ path: `${output}/viewer-390.png`, fullPage: true });
    checks.push('Viewer sees personal notifications only; manager POST is denied, personal save is workspace/user-local');
    await viewer.request.post(api + '/api/v1/auth/logout');
    await viewerPage.getByRole('button', { name: 'Làm mới cài đặt', exact: true }).click();
    await viewerPage.getByRole('alert').waitFor(); assert.equal(await viewerPage.getByLabel('Hoàn tất thu mẫu', { exact: true }).count(), 0);
    checks.push('Revoked session refresh clears private settings instead of retaining editable controls');
    assert.deepEqual(await (await fetch(api + '/metadata')).json(), metadata); assert.deepEqual(errors, []);
  } catch (error) { failure = error; await page.screenshot({ path: `${output}/failure.png`, fullPage: true }).catch(() => {}); }
  finally {
    await browser.close(); await writeFile(`${output}/report.json`, JSON.stringify({ checks, layouts, errors, writes,
      failure: failure?.stack ?? null, limits: 'Isolated SQLite/mock fixture. No real camera, shared database writes, mail/push delivery, PostgreSQL/load or production acceptance.' }, null, 2));
  }
  console.log(JSON.stringify({ output, checks, layouts: layouts.length, failure: failure?.message ?? null }, null, 2));
  if (failure) throw failure;
}
