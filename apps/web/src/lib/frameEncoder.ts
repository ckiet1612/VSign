import type { NormalizedCropRegion } from "./adaptiveFraming";

const OUTPUT_SIZE = 224;
const OUTPUT_QUALITY = 0.78;

export interface CapturedBitmap {
  bitmap: ImageBitmap;
  crop: NormalizedCropRegion | null;
  landmarks?: readonly number[] | null;
  baselineLandmarks?: readonly number[] | null;
}

export interface WorkerReply {
  ok: boolean;
  frames?: string[];
  message?: string;
}

function sourceRectangle(frame: CapturedBitmap) {
  const { bitmap, crop } = frame;
  if (!crop) {
    const side = Math.min(bitmap.width, bitmap.height);
    return {
      x: (bitmap.width - side) / 2,
      y: (bitmap.height - side) / 2,
      width: side,
      height: side,
    };
  }
  return {
    x: crop.x * bitmap.width,
    y: crop.y * bitmap.height,
    width: crop.width * bitmap.width,
    height: crop.height * bitmap.height,
  };
}

async function encodeOnMainThread(frames: readonly CapturedBitmap[]): Promise<string[]> {
  const canvas = document.createElement("canvas");
  canvas.width = OUTPUT_SIZE;
  canvas.height = OUTPUT_SIZE;
  const context = canvas.getContext("2d", { alpha: false });
  if (!context) throw new Error("Trình duyệt không tạo được canvas để xử lý frame.");

  const encoded: string[] = [];
  try {
    for (const frame of frames) {
      const { bitmap } = frame;
      const source = sourceRectangle(frame);
      context.drawImage(
        bitmap,
        source.x,
        source.y,
        source.width,
        source.height,
        0,
        0,
        OUTPUT_SIZE,
        OUTPUT_SIZE,
      );
      let dataUrl = canvas.toDataURL("image/webp", OUTPUT_QUALITY);
      if (!dataUrl.startsWith("data:image/webp;base64,")) {
        dataUrl = canvas.toDataURL("image/jpeg", OUTPUT_QUALITY);
      }
      encoded.push(dataUrl);
    }
  } finally {
    canvas.width = 0;
    canvas.height = 0;
    for (const frame of frames) frame.bitmap.close();
  }
  return encoded;
}

function canUseWorkerEncoder(): boolean {
  return typeof Worker !== "undefined" && typeof OffscreenCanvas !== "undefined";
}

async function encodeInWorker(frames: CapturedBitmap[]): Promise<string[]> {
  return new Promise((resolve, reject) => {
    const worker = new Worker(
      new URL("../workers/frameEncoder.worker.ts", import.meta.url),
      { type: "module" },
    );
    const timeout = window.setTimeout(() => {
      worker.terminate();
      reject(new Error("Xử lý frame quá thời gian cho phép."));
    }, 12_000);
    worker.onmessage = (event: MessageEvent<WorkerReply>) => {
      window.clearTimeout(timeout);
      worker.terminate();
      if (event.data.ok && event.data.frames) resolve(event.data.frames);
      else reject(new Error(event.data.message ?? "Không thể xử lý frame."));
    };
    worker.onerror = () => {
      window.clearTimeout(timeout);
      worker.terminate();
      reject(new Error("Web Worker xử lý frame gặp lỗi."));
    };
    worker.postMessage(
      { frames },
      frames.map((frame) => frame.bitmap),
    );
  });
}

export async function encodeFrames(frames: CapturedBitmap[]): Promise<string[]> {
  if (!frames.length) throw new Error("Không thu được frame camera.");
  if (canUseWorkerEncoder()) return encodeInWorker(frames);
  return encodeOnMainThread(frames);
}
