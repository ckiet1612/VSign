import { afterEach, describe, expect, it, vi } from "vitest";
import { createStreamingEncoder } from "./frameEncoder";

class FakeWorker {
  static instances: FakeWorker[] = [];
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  posted: Array<{ id: number; frame: { bitmap: ImageBitmap } }> = [];
  terminate = vi.fn();
  constructor() { FakeWorker.instances.push(this); }
  postMessage(message: { id: number; frame: { bitmap: ImageBitmap } }) { this.posted.push(message); }
  reply(id: number, frame: string | null) {
    this.onmessage?.({ data: frame ? { id, ok: true, frame } : { id, ok: false, message: "hỏng" } } as MessageEvent);
  }
}

const bitmap = () => ({ close: vi.fn() }) as unknown as ImageBitmap;

describe("createStreamingEncoder", () => {
  afterEach(() => {
    FakeWorker.instances = [];
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("dùng một worker cố định và trả đúng frame theo id dù reply lệch thứ tự", async () => {
    vi.stubGlobal("Worker", FakeWorker);
    vi.stubGlobal("OffscreenCanvas", class {});
    const encoder = createStreamingEncoder();
    const first = encoder.encode({ bitmap: bitmap(), crop: null });
    const second = encoder.encode({ bitmap: bitmap(), crop: null });
    expect(FakeWorker.instances).toHaveLength(1);
    const [worker] = FakeWorker.instances;
    worker.reply(worker.posted[1].id, "second");
    worker.reply(worker.posted[0].id, "first");
    await expect(first).resolves.toBe("first");
    await expect(second).resolves.toBe("second");

    const failed = encoder.encode({ bitmap: bitmap(), crop: null });
    worker.reply(worker.posted[2].id, null);
    await expect(failed).rejects.toThrow("hỏng");

    const pending = encoder.encode({ bitmap: bitmap(), crop: null });
    encoder.dispose();
    await expect(pending).rejects.toThrow("Đã hủy xử lý frame.");
    expect(worker.terminate).toHaveBeenCalledOnce();
  });

  it("lỗi worker hủy các frame đang chờ và tạo worker mới cho frame sau", async () => {
    vi.stubGlobal("Worker", FakeWorker);
    vi.stubGlobal("OffscreenCanvas", class {});
    const encoder = createStreamingEncoder();
    const pending = encoder.encode({ bitmap: bitmap(), crop: null });
    FakeWorker.instances[0].onerror?.();
    await expect(pending).rejects.toThrow("Web Worker xử lý frame gặp lỗi.");
    void encoder.encode({ bitmap: bitmap(), crop: null }).catch(() => undefined);
    expect(FakeWorker.instances).toHaveLength(2);
    encoder.dispose();
  });

  it("không có OffscreenCanvas thì encode trên main thread và đóng bitmap", async () => {
    vi.stubGlobal("OffscreenCanvas", undefined);
    const context = { fillRect: vi.fn(), drawImage: vi.fn(), fillStyle: "" };
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(context as unknown as CanvasRenderingContext2D);
    vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockReturnValue("data:image/webp;base64,AAAA");
    const encoder = createStreamingEncoder();
    const frame = { bitmap: { width: 224, height: 224, close: vi.fn() } as unknown as ImageBitmap, crop: null };
    await expect(encoder.encode(frame)).resolves.toBe("data:image/webp;base64,AAAA");
    expect(context.fillRect).toHaveBeenCalledWith(0, 0, 224, 224);
    expect(frame.bitmap.close).toHaveBeenCalledOnce();
    encoder.dispose();
  });
});
