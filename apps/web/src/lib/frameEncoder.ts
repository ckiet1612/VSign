import type { NormalizedCropRegion } from "./adaptiveFraming";
import { drawCapturedFrame } from "./bodyFraming";

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

interface StreamReply {
  id: number;
  ok: boolean;
  frame?: string;
  message?: string;
}

const STREAM_FRAME_TIMEOUT_MS = 5_000;

/**
 * Encodes frames one at a time as they are captured, so a finished sign only
 * waits for its last few frames instead of the whole clip.
 */
export interface StreamingFrameEncoder {
  /** Takes ownership of `frame.bitmap` and closes it. */
  encode: (frame: Pick<CapturedBitmap, "bitmap" | "crop">) => Promise<string>;
  dispose: () => void;
}

export function createStreamingEncoder(): StreamingFrameEncoder {
  if (!canUseWorkerEncoder()) {
    let canvas: HTMLCanvasElement | null = null;
    return {
      encode: async (frame) => {
        try {
          canvas ??= document.createElement("canvas");
          canvas.width = OUTPUT_SIZE;
          canvas.height = OUTPUT_SIZE;
          const context = canvas.getContext("2d", { alpha: false });
          if (!context) throw new Error("Trình duyệt không tạo được canvas để xử lý frame.");
          drawCapturedFrame(context, frame, OUTPUT_SIZE);
          const dataUrl = canvas.toDataURL("image/webp", OUTPUT_QUALITY);
          return dataUrl.startsWith("data:image/webp;base64,")
            ? dataUrl
            : canvas.toDataURL("image/jpeg", OUTPUT_QUALITY);
        } finally {
          frame.bitmap.close();
        }
      },
      dispose: () => {
        if (canvas) canvas.width = 0;
        canvas = null;
      },
    };
  }

  let worker: Worker | null = null;
  let nextId = 0;
  const pending = new Map<number, { resolve: (frame: string) => void; reject: (error: Error) => void; timeout: number }>();
  const failAll = (message: string) => {
    for (const { reject, timeout } of pending.values()) {
      window.clearTimeout(timeout);
      reject(new Error(message));
    }
    pending.clear();
  };
  const start = () => {
    const created = new Worker(
      new URL("../workers/frameEncoder.worker.ts", import.meta.url),
      { type: "module" },
    );
    created.onmessage = (event: MessageEvent<StreamReply>) => {
      const request = pending.get(event.data.id);
      if (!request) return;
      pending.delete(event.data.id);
      window.clearTimeout(request.timeout);
      if (event.data.ok && event.data.frame) request.resolve(event.data.frame);
      else request.reject(new Error(event.data.message ?? "Không thể xử lý frame."));
    };
    created.onerror = () => {
      created.terminate();
      if (worker === created) worker = null;
      failAll("Web Worker xử lý frame gặp lỗi.");
    };
    return created;
  };
  return {
    encode: (frame) => new Promise<string>((resolve, reject) => {
      worker ??= start();
      const id = nextId++;
      const timeout = window.setTimeout(() => {
        pending.delete(id);
        reject(new Error("Xử lý frame quá thời gian cho phép."));
      }, STREAM_FRAME_TIMEOUT_MS);
      pending.set(id, { resolve, reject, timeout });
      worker.postMessage({ id, frame: { bitmap: frame.bitmap, crop: frame.crop } }, [frame.bitmap]);
    }),
    dispose: () => {
      worker?.terminate();
      worker = null;
      failAll("Đã hủy xử lý frame.");
    },
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
      drawCapturedFrame(context, frame, OUTPUT_SIZE);
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
