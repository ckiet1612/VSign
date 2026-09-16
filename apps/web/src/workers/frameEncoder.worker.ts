import type { NormalizedCropRegion } from "../lib/adaptiveFraming";

interface EncoderRequest {
  frames: Array<{
    bitmap: ImageBitmap;
    crop: NormalizedCropRegion | null;
  }>;
}

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

encoderScope.onmessage = async (event) => {
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
      const { bitmap, crop } = frame;
      const side = Math.min(bitmap.width, bitmap.height);
      const sourceX = crop ? crop.x * bitmap.width : (bitmap.width - side) / 2;
      const sourceY = crop ? crop.y * bitmap.height : (bitmap.height - side) / 2;
      const sourceWidth = crop ? crop.width * bitmap.width : side;
      const sourceHeight = crop ? crop.height * bitmap.height : side;
      context.drawImage(
        bitmap,
        sourceX,
        sourceY,
        sourceWidth,
        sourceHeight,
        0,
        0,
        OUTPUT_SIZE,
        OUTPUT_SIZE,
      );
      let blob = await canvas.convertToBlob({ type: "image/webp", quality: OUTPUT_QUALITY });
      if (blob.type !== "image/webp") {
        blob = await canvas.convertToBlob({ type: "image/jpeg", quality: OUTPUT_QUALITY });
      }
      encoded.push(await blobToDataUrl(blob));
      bitmap.close();
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
