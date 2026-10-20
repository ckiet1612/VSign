import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";

const require = createRequire(process.env.VSIGN_PLAYWRIGHT_FROM || import.meta.url);
const { chromium } = require("playwright");
const input = JSON.parse(await readFile(process.argv[2], "utf8"));
const browser = await chromium.launch({ channel: "chrome", headless: true });
const samples = [];
try {
  const page = await browser.newPage();
  await page.goto(input.frontend);
  for (const sample of input.samples) {
    const pngFrames = await Promise.all(sample.png_frames.map(async file =>
      `data:image/png;base64,${(await readFile(file)).toString("base64")}`));
    const variants = [];
    for (const mode of ["worker_center", "main_center", "worker_full"]) {
      const sequence = samples.length * 3 + variants.length;
      const result = await page.evaluate(async ({ pngFrames, mode, sequence, backend }) => {
        const { encodeFrames } = await import("/src/lib/frameEncoder.ts");
        if (typeof OffscreenCanvas === "undefined" || typeof Worker === "undefined") {
          throw new Error("Worker encoder unavailable in diagnostic browser");
        }
        const captured = await Promise.all(pngFrames.map(async source => ({
          bitmap: await createImageBitmap(await (await fetch(source)).blob()),
          crop: mode === "worker_full" ? { x: 0, y: 0, width: 1, height: 1 } : null,
        })));
        const width = captured[0].bitmap.width, height = captured[0].bitmap.height;
        const NativeWorker = window.Worker;
        let frames;
        try {
          if (mode === "main_center") window.Worker = undefined;
          frames = await encodeFrames(captured);
        } finally {
          window.Worker = NativeWorker;
        }
        const reply = await new Promise((resolve, reject) => {
          const socket = new WebSocket(backend.replace(/^http/, "ws") + "/ws/inference");
          const timeout = setTimeout(() => { socket.close(); reject(new Error("Inference timeout")); }, 60000);
          const finish = (error, value) => {
            clearTimeout(timeout);
            socket.onclose = null;
            socket.close();
            error ? reject(error) : resolve(value);
          };
          socket.onopen = () => socket.send(JSON.stringify({ type: "frames", session_id: crypto.randomUUID(),
            sequence, captured_at: Date.now(), frames }));
          socket.onmessage = event => finish(null, JSON.parse(event.data));
          socket.onerror = () => finish(new Error("WebSocket failure"));
          socket.onclose = () => finish(new Error("Socket closed before reply"));
        });
        return { frames, width, height, reply };
      }, { pngFrames, mode, sequence, backend: input.backend });
      assert.equal(result.frames.length, 16);
      assert.equal(result.reply.sequence, sequence);
      assert.ok(["ok", "uncertain"].includes(result.reply.status));
      assert.notEqual(result.reply.label, "Không ký hiệu");
      variants.push({ mode, sequence, width: result.width, height: result.height,
        image_format: result.frames[0].split(";")[0].slice(5),
        encoded_frames_sha256: createHash("sha256").update(JSON.stringify(result.frames)).digest("hex"),
        reply: result.reply });
    }
    const { png_frames, ...identity } = sample;
    samples.push({ ...identity, variants });
    console.log(JSON.stringify({ word: sample.expected_label,
      variants: variants.map(item => ({ mode: item.mode, status: item.reply.status, label: item.reply.label })) }));
  }
  await writeFile(process.argv[3], JSON.stringify({ samples }, null, 2), { flag: "wx" });
} finally {
  await browser.close();
}
