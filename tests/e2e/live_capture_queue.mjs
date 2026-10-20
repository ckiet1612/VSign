import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const require = createRequire(process.env.VSIGN_PLAYWRIGHT_FROM || import.meta.url);
const { chromium } = require("playwright");
const cameraFile = process.env.VSIGN_FAKE_CAMERA_FILE;
if (!cameraFile) throw new Error("Set VSIGN_FAKE_CAMERA_FILE to a replay webcam .y4m file.");
const output = process.env.VSIGN_SMOKE_OUTPUT || "/tmp/vsign-live-queue-smoke";
await mkdir(output, { recursive: true });
const browser = await chromium.launch({
  channel: "chrome", headless: true,
  args: [
    "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
    `--use-file-for-fake-video-capture=${cameraFile}`,
  ],
});

try {
  const context = await browser.newContext({
    viewport: { width: 1365, height: 900 }, permissions: ["camera"],
  });
  await context.addInitScript(() => {
    const Original = window.WebSocket;
    window.__heldReplies = [];
    class DelayedSocket extends Original {
      constructor(...args) {
        super(...args);
        if (!String(args[0]).includes("/ws/inference")) return;
        this.addEventListener("message", (event) => {
          if (event.__released) return;
          try {
            if (JSON.parse(event.data).type !== "prediction") return;
            event.stopImmediatePropagation();
            window.__heldReplies.push({ socket: this, data: event.data });
          } catch { /* Non-prediction messages pass through unchanged. */ }
        });
      }
    }
    window.WebSocket = DelayedSocket;
    window.__releaseReply = () => {
      const held = window.__heldReplies.shift();
      if (!held) return false;
      const event = new MessageEvent("message", { data: held.data });
      event.__released = true;
      held.socket.dispatchEvent(event);
      return true;
    };
  });
  const page = await context.newPage();
  const errors = [];
  const sent = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("websocket", (socket) => {
    if (!socket.url().includes("/ws/inference")) return;
    socket.on("framesent", ({ payload }) => {
      const message = JSON.parse(payload);
      if (message.type === "frames") sent.push(message);
    });
  });
  await page.goto(process.env.VSIGN_SMOKE_URL || "http://localhost:5173");
  await page.getByRole("button", { name: "Bật camera", exact: true }).click();
  await page.getByText("Cách thu", { exact: true }).click();
  await page.getByRole("button", { name: "Tự động beta" }).click();
  const full = page.getByText("Hàng đợi đầy · chờ AI xử lý", { exact: true });
  await full.waitFor({ timeout: 55000 });
  assert.equal(sent.length, 1);
  assert.equal(sent[0].frames.length, 16);
  assert.equal(await page.getByText("Chờ: 2/2", { exact: true }).isVisible(), true);
  assert.equal(await page.getByRole("button", { name: "Hoàn tác từ cuối", includeHidden: true }).isDisabled(), true);
  await page.screenshot({ path: path.join(output, "queue-full.png"), fullPage: true });
  await page.waitForFunction(() => window.__heldReplies.length === 1);
  await page.evaluate(() => window.__releaseReply());
  await page.waitForFunction(() => window.__heldReplies.length === 1);
  assert.equal(sent.length, 2);
  assert.equal(sent[1].sequence, 1);
  assert.equal(sent[1].frames.length, 16);
  assert.equal(await full.isVisible(), false);
  assert.equal(await page.getByText("Chờ: 1/2", { exact: true }).isVisible(), true);
  assert.equal(await page.locator(".capture-diagnostics").getAttribute("open"), null);
  await page.getByText("Thời gian xử lý", { exact: true }).click();
  const timing = await page.locator(".capture-timings").innerText();
  assert.match(timing, /Phản hồi AI/);

  const imageSizes = await page.evaluate(async (frames) => Promise.all(frames.map((src) =>
    new Promise((resolve) => {
      const image = new Image();
      image.onload = () => resolve([image.naturalWidth, image.naturalHeight]);
      image.onerror = () => resolve([0, 0]);
      image.src = src;
    }),
  )), sent[0].frames);
  assert.ok(imageSizes.every(([width, height]) => width === 224 && height === 224));

  const layouts = [];
  for (const width of [320, 390, 768, 1365]) {
    await page.setViewportSize({ width, height: 900 });
    const layout = await page.evaluate(() => ({
      width: innerWidth, scrollWidth: document.body.scrollWidth,
      overflow: Array.from(document.querySelectorAll(
        ".capture-timings dt,.capture-timings dd,.automatic-queue-counts,.automatic-action,button",
      )).filter((element) => {
        const bounds = element.getBoundingClientRect();
        return bounds.width && (bounds.left < -1 || bounds.right > innerWidth + 1 ||
          element.scrollWidth > element.clientWidth + 2);
      }).map((element) => element.textContent),
    }));
    assert.equal(layout.width, layout.scrollWidth);
    assert.equal(layout.overflow.length, 0);
    layouts.push(layout);
    await page.screenshot({ path: path.join(output, `timing-${width}.png`), fullPage: true });
  }

  await page.getByRole("button", { name: "Tắt camera", exact: true }).click();
  await page.evaluate(() => window.__releaseReply());
  assert.equal(sent.length, 2);
  assert.equal(await page.locator(".add-button").isDisabled(), true);
  assert.equal(await page.locator(".add-button").isVisible(), false);

  await page.getByText("Cách thu", { exact: true }).click();
  await page.getByRole("button", { name: "Giữ để ký", exact: true }).click();
  await page.getByRole("button", { name: "Bật camera", exact: true }).click();
  await page.waitForFunction(() => {
    const video = document.querySelector("video");
    return video && video.readyState >= 2 && video.videoWidth > 0;
  });
  await page.getByRole("button", {
    name: "Giữ để ký, cũng có thể giữ phím Space",
  }).waitFor();
  await page.keyboard.down("Space");
  // This is the intentional duration of the manual fixture, not a network wait.
  await new Promise((resolve) => setTimeout(resolve, 1000));
  await page.keyboard.up("Space");
  await page.waitForFunction(() => window.__heldReplies.length === 1, null, { timeout: 20000 });
  assert.equal(sent.length, 3);
  assert.equal(sent[2].frames.length, 16);
  await page.evaluate(() => window.__releaseReply());
  await page.getByRole("button", {
    name: "Giữ để ký, cũng có thể giữ phím Space",
  }).waitFor();
  assert.equal(await page.getByRole("button", { name: "Hoàn tác từ cuối", includeHidden: true }).isDisabled(), true);
  await page.getByRole("button", { name: "Tắt camera", exact: true }).click();
  assert.equal(errors.length, 0);
  const report = {
    passed: true, requests: sent.map(({ sequence, frames }) => ({ sequence, frameCount: frames.length })),
    imageSizes, layouts, timing, cameraCancellation: true, manualCapture: true,
    autoTranscriptInsertion: false, consoleErrors: errors,
    note: "Replay camera and artificially held replies; not a real-camera quality or latency benchmark.",
  };
  await writeFile(path.join(output, "report.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
} finally {
  await browser.close();
}
