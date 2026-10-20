import assert from "node:assert/strict";
import { spawn, execFileSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { mkdtemp, readFile, realpath, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(process.env.VSIGN_PLAYWRIGHT_FROM || import.meta.url);
const { chromium } = require("playwright");
const sharp = require("sharp");
const root = fileURLToPath(new URL("../../", import.meta.url));
const output = await realpath(await mkdtemp(path.join(os.tmpdir(), "vsign-enterprise-models-")));
const children = [], logs = [], checks = [], layouts = [], errors = [], jobs = [], predictions = [], snapshots = {};
let browser, page, fixture, failure;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function freePort() {
  const server = net.createServer();
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  return [8000, 8002, 8003, 5174].includes(port) ? freePort() : port;
}
const platformPort = await freePort();
let webPort = await freePort();
while (webPort === platformPort) webPort = await freePort();
const platform = `http://127.0.0.1:${platformPort}`, web = `http://127.0.0.1:${webPort}`;

function start(name, command, args, options = {}) {
  const child = spawn(command, args, { cwd: root, ...options, stdio: ["ignore", "pipe", "pipe"], detached: true });
  child.once("error", error => errors.push(`${name}: ${error.message}`));
  child.stdout.on("data", chunk => logs.push(`[${name}] ${chunk}`));
  child.stderr.on("data", chunk => logs.push(`[${name}] ${chunk}`));
  children.push({ name, child });
}
async function until(label, operation) {
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    assert.deepEqual(errors, []);
    for (const { child } of children) assert.equal(child.exitCode, null, "Fixture server exited");
    if (await operation()) return;
    await sleep(150);
  }
  throw new Error(`Timed out: ${label}`);
}
async function ready(url) {
  await until(url, async () => { try { return (await fetch(url, { signal: AbortSignal.timeout(1500) })).ok; } catch { return false; } });
}
async function json(request, endpoint, payload, expected = 200) {
  const response = payload === undefined ? await request.get(`${platform}${endpoint}`)
    : await request.post(`${platform}${endpoint}`, { data: payload });
  assert.equal(response.status(), expected, `${endpoint}: ${await response.text()}`);
  return response.json();
}
async function finish(request, requestId, expectedModel, revision) {
  let snapshot;
  await until(`deployment ${requestId}`, async () => {
    snapshot = await json(request, "/api/v1/workspace/models");
    const job = snapshot.deployments.find(row => row.id === requestId);
    assert.notEqual(job?.status, "failed", job?.error);
    return job?.status === "succeeded";
  });
  assert.equal(snapshot.target.active_model_id, expectedModel);
  assert.equal(snapshot.target.observed_model_id, expectedModel);
  assert.equal(snapshot.target.revision, revision);
  assert.equal(snapshot.target.pending_job_id, null);
  jobs.push(snapshot.deployments.find(row => row.id === requestId));
  return snapshot;
}
async function prediction(version, label) {
  const bytes = await sharp({ create: { width: 224, height: 224, channels: 3, background: "white" } }).jpeg().toBuffer();
  const result = await page.evaluate(async ({ endpoint, frame }) => new Promise((resolve, reject) => {
    const socket = new WebSocket(endpoint);
    const timer = setTimeout(() => { socket.close(); reject(new Error("Prediction timed out")); }, 10000);
    socket.onopen = () => socket.send(JSON.stringify({ type: "frames", session_id: crypto.randomUUID(), sequence: 0,
      captured_at: Date.now(), frames: Array(16).fill(frame) }));
    socket.onmessage = event => { clearTimeout(timer); socket.close(); resolve(JSON.parse(event.data)); };
    socket.onerror = () => { clearTimeout(timer); socket.close(); reject(new Error("Prediction socket failed")); };
  }), { endpoint: `${platform.replace("http:", "ws:")}/ws/inference`, frame: `data:image/jpeg;base64,${bytes.toString("base64")}` });
  assert.equal(result.model_version, version);
  assert.equal(result.status, "ok");
  assert.equal(result.label, label);
  predictions.push(result);
}

try {
  start("fixture", path.join(root, ".venv/bin/python"), ["-u", "tests/e2e/model_registry_fixture.py", "--output", output,
    "--port", String(platformPort), "--origin", web], { env: { ...process.env, PYTHONPATH: `${root}/services/inference:${root}` } });
  await ready(`${platform}/health`);
  fixture = JSON.parse(await readFile(path.join(output, "config.json"), "utf8"));
  assert.deepEqual(fixture.backend_checks.map(check => check.backend_class), ["ONNXInferenceBackend", "ONNXInferenceBackend"]);
  checks.push("Disposable native ONNX models; no shared services or artifacts");
  start("web", process.execPath, ["node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", String(webPort), "--strictPort"], {
    cwd: path.join(root, "apps/web"), env: { ...process.env, VITE_PLATFORM_HTTP_URL: platform, VITE_INFERENCE_HTTP_URL: platform,
      VITE_INFERENCE_WS_URL: `${platform.replace("http:", "ws:")}/ws/inference`, VITE_PUBLIC_DEMO: "false", VITE_PLATFORM_AUTH_REQUIRED: "false" },
  });
  await ready(web);
  browser = await chromium.launch({ channel: "chrome", headless: true });
  const context = await browser.newContext({ viewport: { width: 1365, height: 900 } });
  page = await context.newPage();
  page.on("pageerror", error => errors.push(error.message));
  const writes = [];
  page.on("request", request => { if (!["GET", "HEAD", "OPTIONS"].includes(request.method())) writes.push(request.url()); });
  await page.goto(`${web}/?view=models`);
  await page.getByLabel("Email", { exact: true }).fill(fixture.email);
  await page.getByLabel("Mật khẩu", { exact: true }).fill(fixture.password);
  await page.getByRole("button", { name: "Đăng nhập", exact: true }).click();
  await page.getByRole("heading", { name: "Phiên bản đang dùng", exact: true }).waitFor();
  const me = await json(context.request, "/api/v1/auth/me");
  assert.equal(me.user.role, "model_admin");
  checks.push("Internal test membership is explicit; session login remains functional");
  snapshots.initial = await json(context.request, "/api/v1/workspace/models");
  const baselineId = snapshots.initial.target.active_model_id;
  assert.equal(snapshots.initial.models.length, 1);
  await prediction(fixture.baseline.version, "Hello");

  let state = await json(context.request, "/api/v1/workspace/models", {
    manifest_path: fixture.candidate.manifest_path, artifact_path: fixture.candidate.artifact_path, labels_path: fixture.labels_path,
  }, 201);
  const candidateId = state.models.find(model => model.origin === "candidate").id;
  assert.equal(state.target.active_model_id, baselineId);
  assert.equal(state.target.revision, 0);
  assert.deepEqual(state.deployments, []);
  checks.push("Registering a candidate never deploys it");
  await json(context.request, `/api/v1/workspace/models/${candidateId}/validate`, { report_path: fixture.reports.invalid }, 422);
  state = await json(context.request, `/api/v1/workspace/models/${candidateId}/validate`, { report_path: fixture.reports.failing });
  let candidate = state.models.find(model => model.id === candidateId);
  assert.equal(candidate.validation.passed, false);
  await json(context.request, `/api/v1/workspace/models/${candidateId}/approve`, { validation_id: candidate.validation.id }, 409);
  checks.push("Invalid and failed evaluations cannot pass approval");
  state = await json(context.request, `/api/v1/workspace/models/${candidateId}/validate`, { report_path: fixture.reports.passing });
  assert.equal(state.models.find(model => model.id === candidateId).validation.passed, false);
  checks.push("Imported numeric report is diagnostic and cannot authorize deployment");
  execFileSync(path.join(root, ".venv/bin/python"), ["tests/e2e/seed_model_gate_fixture.py", path.join(output, "config.json")], {
    cwd: root, env: { ...process.env, PYTHONPATH: `${root}/services/inference:${root}` },
  });
  state = await json(context.request, "/api/v1/workspace/models");
  candidate = state.models.find(model => model.id === candidateId);
  assert.equal(candidate.validation.passed, true);
  const deploy = { request_id: randomUUID(), model_id: candidateId, expected_revision: 0 };
  await json(context.request, "/api/v1/workspace/models/deployments", deploy, 409);
  await json(context.request, `/api/v1/workspace/models/${candidateId}/approve`, { validation_id: candidate.validation.id });
  checks.push("Passing evaluation still requires separate internal approval");
  await json(context.request, "/api/v1/workspace/models/deployments", deploy, 202);
  snapshots.deployed = await finish(context.request, deploy.request_id, candidateId, 1);
  assert.equal((await json(context.request, "/metadata")).model_version, fixture.candidate.version);
  await prediction(fixture.candidate.version, "Bye");
  await json(context.request, "/api/v1/workspace/models/deployments", deploy, 202);
  assert.equal((await json(context.request, "/api/v1/workspace/models")).target.revision, 1);
  checks.push("Internal deployment reloads native ONNX; repeated request is idempotent");
  const rollback = { request_id: randomUUID(), expected_revision: 1 };
  await json(context.request, "/api/v1/workspace/models/rollback", rollback, 202);
  snapshots.rolledBack = await finish(context.request, rollback.request_id, baselineId, 2);
  await prediction(fixture.baseline.version, "Hello");
  checks.push("Internal rollback restores pointer and served identity");

  await page.getByRole("button", { name: "Làm mới mô hình", exact: true }).click();
  await page.getByRole("heading", { name: "Khôi phục phiên bản", exact: true }).waitFor();
  assert.equal(await page.getByLabel("Manifest", { exact: true }).count(), 0);
  assert.equal(await page.getByRole("button", { name: /Triển khai|Hoàn tác|Phê duyệt|Đăng ký ứng viên/ }).count(), 0);
  for (const width of [320, 390, 768, 1365]) {
    await page.setViewportSize({ width, height: 900 });
    const documentWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    assert.ok(documentWidth <= width);
    const screenshot = path.join(output, `models-history-${width}.png`);
    await page.screenshot({ path: screenshot, fullPage: true });
    const stats = await sharp(screenshot).stats();
    assert.ok(stats.channels.some(channel => channel.stdev > 10));
    layouts.push({ width, documentWidth, screenshot });
  }
  checks.push("Workspace model view remains read-only with populated history at four widths");
  snapshots.audit = await json(context.request, "/api/v1/workspace/audit/events?group=deployment");
  assert.equal(snapshots.audit.events.length, 4);
  assert.ok(snapshots.audit.events.every(event => event.workspace_id === fixture.workspace_id && event.actor_id === me.user.id));
  await page.getByRole("button", { name: "Hoạt động", exact: true }).click();
  await page.getByLabel("Loại hoạt động").selectOption("deployment");
  await page.getByRole("heading", { name: "Yêu cầu hoàn tác", exact: true }).waitFor();
  checks.push("Deployment audit remains scoped and has readable business labels");
  for (const artifact of [fixture.baseline, fixture.candidate]) {
    assert.equal(createHash("sha256").update(await readFile(artifact.artifact_path)).digest("hex"), artifact.sha256);
  }
  assert.deepEqual(writes.map(url => new URL(url).pathname), ["/api/v1/auth/login"]);
  assert.deepEqual(errors, []);
  checks.push("No browser model writes, page errors or fixture artifact changes");
} catch (error) {
  failure = { message: error.message, stack: error.stack };
} finally {
  await browser?.close();
  for (const { child } of children.reverse()) {
    if (child.exitCode !== null) continue;
    await new Promise(resolve => {
      const timer = setTimeout(() => { try { process.kill(-child.pid, "SIGKILL"); } catch {} }, 10000);
      child.once("exit", () => { clearTimeout(timer); resolve(); });
      try { process.kill(-child.pid, "SIGTERM"); } catch { clearTimeout(timer); resolve(); }
    });
  }
  await writeFile(path.join(output, "server.log"), logs.join(""));
  await writeFile(path.join(output, "report.json"), JSON.stringify({ status: failure ? "failed" : "passed", checks, layouts,
    errors, jobs, predictions, snapshots, failure, platform, web, output,
    limits: "Disposable native ONNX constants and synthetic reports, not real camera, training, model quality or production acceptance." }, null, 2));
  console.log(JSON.stringify({ status: failure ? "failed" : "passed", checks, failure, report: path.join(output, "report.json") }, null, 2));
}
if (failure) process.exitCode = 1;
