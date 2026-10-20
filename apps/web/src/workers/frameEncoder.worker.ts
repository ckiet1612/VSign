import type { NormalizedCropRegion } from "../lib/adaptiveFraming";
import { drawCapturedFrame } from "../lib/bodyFraming";

interface EncoderFrame {
  bitmap: ImageBitmap;
  crop: NormalizedCropRegion | null;
}

/** A batch (`frames`) or one streamed frame (`id` + `frame`) encoded while the user signs. */
type EncoderRequest =
  | { frames: EncoderFrame[] }
  | { id: number; frame: EncoderFrame };

interface EncoderScope {
  onmessage: ((event: MessageEvent<EncoderRequest>) => void) | null;
  postMessage: (message: unknown) => void;
}

const encoderScope = self as unknown as EncoderScope;
const OUTPUT_SIZE = 224;
const OUTPUT_QUALITY = 0.78;

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error("Không đọc được frame đã encode."));
    reader.readAsDataURL(blob);
  });
}

async function encodeOne(
  canvas: OffscreenCanvas,
  context: OffscreenCanvasRenderingContext2D,
  frame: EncoderFrame,
): Promise<string> {
  drawCapturedFrame(context, frame, OUTPUT_SIZE);
  let blob = await canvas.convertToBlob({ type: "image/webp", quality: OUTPUT_QUALITY });
  if (blob.type !== "image/webp") {
    blob = await canvas.convertToBlob({ type: "image/jpeg", quality: OUTPUT_QUALITY });
  }
  return blobToDataUrl(blob);
}

let streamCanvas: OffscreenCanvas | null = null;
let streamContext: OffscreenCanvasRenderingContext2D | null = null;
// Streamed frames share one canvas, so encode them strictly in arrival order.
let streamQueue: Promise<void> = Promise.resolve();

function encodeStreamed(id: number, frame: EncoderFrame): void {
  streamQueue = streamQueue.then(async () => {
    try {
      streamCanvas ??= new OffscreenCanvas(OUTPUT_SIZE, OUTPUT_SIZE);
      streamContext ??= streamCanvas.getContext("2d", { alpha: false });
      if (!streamContext) throw new Error("Không tạo được OffscreenCanvas.");
      encoderScope.postMessage({ id, ok: true, frame: await encodeOne(streamCanvas, streamContext, frame) });
    } catch (error) {
      encoderScope.postMessage({
        id,
        ok: false,
        message: error instanceof Error ? error.message : "Không thể encode frame.",
      });
    } finally {
      frame.bitmap.close();
    }
  });
}

encoderScope.onmessage = async (event) => {
  if ("id" in event.data) {
    encodeStreamed(event.data.id, event.data.frame);
    return;
  }
  const frames = event.data.frames;
  const canvas = new OffscreenCanvas(OUTPUT_SIZE, OUTPUT_SIZE);
  const context = canvas.getContext("2d", { alpha: false });
  if (!context) {
    for (const frame of frames) frame.bitmap.close();
    encoderScope.postMessage({ ok: false, message: "Không tạo được OffscreenCanvas." });
    return;
  }
  try {
    const encoded: string[] = [];
    for (const frame of frames) {
      encoded.push(await encodeOne(canvas, context, frame));
      frame.bitmap.close();
    }
    encoderScope.postMessage({ ok: true, frames: encoded });
  } catch (error) {
    for (const frame of frames) frame.bitmap.close();
    encoderScope.postMessage({
      ok: false,
      message: error instanceof Error ? error.message : "Không thể encode frame.",
    });
  }
};

export {};
