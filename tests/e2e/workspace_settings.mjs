// Isolated fixture host for the collaborative browser verification workflow.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtemp, realpath, writeFile } from 'node:fs/promises';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../../', import.meta.url));
const output = await realpath(await mkdtemp(path.join(os.tmpdir(), 'vsign-settings-')));
const children = [], logs = [];
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function port() {
  const server = net.createServer(); await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const value = server.address().port; await new Promise(resolve => server.close(resolve)); return value;
}
const apiPort = await port(), webPort = await port();
const api = `http://127.0.0.1:${apiPort}`, web = `http://127.0.0.1:${webPort}`;
const environment = { ...process.env, PYTHONPATH: `${root}/services/inference:${root}`, APP_ENV: 'development',
  AUTH_REQUIRED: 'true', LOCAL_ADMIN_ENABLED: 'false', AUTH_COOKIE_SECURE: 'false',
  DATABASE_URL: `sqlite:///${output}/platform.db`, DATABASE_AUTO_CREATE: 'true', WORKSPACE_ID: 'settings-e2e',
  WORKSPACE_NAME: 'Workspace kiểm thử', INFERENCE_BACKEND: 'mock', MODEL_MANIFEST_PATH: '',
  MODEL_DEPLOYMENT_WORKER: 'false', COLLECTION_ENABLED: 'true', COLLECTION_DIR: `${output}/media`,
  ALLOWED_ORIGINS: web, BOOTSTRAP_ADMIN_EMAIL: 'owner@example.com', BOOTSTRAP_ADMIN_PASSWORD: 'fixture-password-12345',
  OPENAI_API_KEY: '', DEV_TEST_ENABLED: 'false', INTEGRATION_ENCRYPTION_KEY: '', INTEGRATION_ENCRYPTION_KEY_FILE: '' };
function start(label, command, args, cwd, env) {
  const child = spawn(command, args, { cwd, env, detached: true, stdio: ['ignore', 'pipe', 'pipe'] });
  child.on('error', error => logs.push(error.message));
  child.stdout.on('data', value => logs.push(`[${label}] ${value}`)); child.stderr.on('data', value => logs.push(`[${label}] ${value}`));
  children.push(child);
}
async function until(url) {
  const deadline = Date.now() + 60000;
  while (Date.now() < deadline) {
    for (const child of children) assert.equal(child.exitCode, null, logs.join(''));
    try { if ((await fetch(url)).ok) return; } catch { /* Wait for server readiness. */ }
    await sleep(150);
  }
  throw new Error('Fixture startup timeout: ' + url);
}
let stopping = false;
async function stop(code = 0) {
  if (stopping) return; stopping = true;
  for (const child of [...children].reverse()) if (child.exitCode === null) { try { process.kill(-child.pid, 'SIGTERM'); } catch { /* Already stopped. */ } }
  for (const child of children) {
    if (child.exitCode === null) await Promise.race([new Promise(resolve => child.once('exit', resolve)), sleep(5000)]);
    if (child.exitCode === null) { try { process.kill(-child.pid, 'SIGKILL'); } catch { /* Already stopped. */ } }
  }
  await writeFile(`${output}/runtime.log`, logs.join('')); process.exit(code);
}
process.on('SIGTERM', () => stop()); process.on('SIGINT', () => stop());
try {
  start('api', `${root}/.venv/bin/python`, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(apiPort)], root, environment);
  await until(api + '/health');
  start('web', process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', String(webPort), '--strictPort'], `${root}/apps/web`,
    { ...process.env, VITE_PLATFORM_HTTP_URL: api, VITE_INFERENCE_HTTP_URL: api, VITE_INFERENCE_WS_URL: api.replace('http:', 'ws:') + '/ws/inference', VITE_PUBLIC_DEMO: 'false' });
  await until(web);
  const manifest = { output, api, web, fixtureOnly: true, metadata: await (await fetch(api + '/metadata')).json() };
  await writeFile(`${output}/manifest.json`, JSON.stringify(manifest, null, 2));
  console.log(JSON.stringify(manifest, null, 2));
  if (process.argv.includes('--serve')) console.log('Fixture ready. Verify with the collaborative browser; stop this process to clean up both servers.');
  else {
    const { verifySettingsBrowser } = await import('./workspace_settings_browser.mjs');
    await verifySettingsBrowser(manifest); await stop();
  }
} catch (error) { console.error(error); await stop(1); }
