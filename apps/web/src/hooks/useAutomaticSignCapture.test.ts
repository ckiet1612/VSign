import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { HandTrackingFrame } from "../components/HandTrackingOverlay";
import { emptyLandmarkFrame, HAND_GLOBAL_OFFSET, HAND_PRESENCE_OFFSET } from "../lib/landmarkFeatures";
import { uniformSampleIndices } from "../lib/sampling";
import { framingFrame } from "../lib/bodyFraming";
import { useAutomaticSignCapture } from "./useAutomaticSignCapture";

const encoder = vi.hoisted(() => ({ encode: vi.fn(), dispose: vi.fn() }));
vi.mock("../lib/frameEncoder", () => ({ createStreamingEncoder: () => encoder }));

type TestBitmap = ImageBitmap & { id: number };
const encodeById = async (frame: { bitmap: ImageBitmap }) => {
  frame.bitmap.close();
  return `frame-${(frame.bitmap as TestBitmap).id}`;
};
const sentIds = (frames: string[]) => [...new Set(frames.map((frame) => Number(frame.split("-")[1])))];

function tracking(timestamp: number, x: number | null): HandTrackingFrame {
  const features = emptyLandmarkFrame();
  if (x !== null) {
    for (let point = 0; point < 21; point += 1) {
      features[point * 3] = x + point * 0.001;
      features[point * 3 + 1] = 0.5;
    }
    features[HAND_GLOBAL_OFFSET] = x;
    features[HAND_GLOBAL_OFFSET + 1] = 0.5;
    features[HAND_PRESENCE_OFFSET] = 1;
  }
  return { features, baselineFeatures: new Array(128).fill(x ?? 0), crop: null, handCount: x === null ? 0 : 1, updatedAt: timestamp };
}

function gesture(start = 0): HandTrackingFrame[] {
  return [
    ...Array.from({ length: 16 }, (_, i) => tracking(start + i * 50, 0.2)),
    ...Array.from({ length: 20 }, (_, i) => tracking(start + 800 + i * 50, 0.2 + i * 0.025)),
    ...Array.from({ length: 20 }, (_, i) => tracking(start + 1800 + i * 50, 0.675)),
  ];
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => { resolve = next; });
  return { promise, resolve };
}

describe("automatic Sales30 RGB capture", () => {
  let bitmaps: Array<ImageBitmap & { id: number }>;
  const video = { readyState: HTMLMediaElement.HAVE_CURRENT_DATA, videoWidth: 1280, videoHeight: 720 } as HTMLVideoElement;

  beforeEach(() => {
    bitmaps = [];
    encoder.encode.mockReset().mockImplementation(encodeById);
    encoder.dispose.mockReset();
    vi.stubGlobal("createImageBitmap", vi.fn(async () => {
      const bitmap = { width: 224, height: 224, id: bitmaps.length, close: vi.fn() } as unknown as ImageBitmap & { id: number };
      bitmaps.push(bitmap);
      return bitmap;
    }));
  });
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  function mount() {
    const onSequence = vi.fn();
    const onError = vi.fn();
    const onCaptureStart = vi.fn();
    const onCaptureCancel = vi.fn();
    const hook = renderHook(
      ({ enabled, paused, captureContextKey }) => useAutomaticSignCapture({
        enabled, paused, captureContextKey,
        videoRef: { current: video }, captureVideoFrames: true,
        onSequence, onError, onCaptureStart, onCaptureCancel,
      }),
      { initialProps: { enabled: true, paused: false, captureContextKey: "server" } },
    );
    const feed = async (frames: HandTrackingFrame[]) => {
      for (const frame of frames) {
        await act(async () => { hook.result.current.ingest(frame); });
      }
    };
    return { ...hook, onSequence, onError, onCaptureStart, onCaptureCancel, feed };
  }

  it("gửi đúng 16 ảnh lấy đều, giữ pre-roll và crop RGB cố định", async () => {
    const { feed, onSequence, onCaptureStart, onError } = mount();
    await feed(gesture());
    expect(onCaptureStart).toHaveBeenCalledOnce();
    expect(onSequence).toHaveBeenCalledOnce();
    const frames = onSequence.mock.calls[0][2] as string[];
    expect(frames).toHaveLength(16);
    expect(encoder.encode.mock.calls.every(([frame]) => frame.crop === null)).toBe(true);
    const ids = sentIds(frames);
    const all = Array.from({ length: ids.at(-1)! - ids[0] + 1 }, (_, i) => ids[0] + i);
    expect(ids).toEqual(uniformSampleIndices(all.length, 16).map((i) => all[i]));
    // Motion starts at 800 ms; RGB snapshots run every >=75 ms.
    expect(ids[0]).toBeLessThan(8);
    expect(createImageBitmap).toHaveBeenCalledWith(video, 280, 0, 720, 720, {
      resizeWidth: 224, resizeHeight: 224, resizeQuality: "low",
    });
    expect(onError).not.toHaveBeenCalled();
  });

  it("trim-bodycrop-v1: chỉ gửi đoạn tay giơ lên và crop quanh người", async () => {
    const context = { fillRect: vi.fn(), drawImage: vi.fn(), fillStyle: "", imageSmoothingEnabled: false, imageSmoothingQuality: "low" };
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(context as unknown as CanvasRenderingContext2D);
    const pose = Array.from({ length: 33 }, (_, index) => ({
      x: index === 11 ? 0.6 : index === 12 ? 0.4 : 0.5,
      y: index === 15 || index === 16 ? 1.2 : 0.45,
      visibility: index === 15 || index === 16 ? 0.1 : 0.99,
    }));
    const framed = gesture().map((frame) => {
      const raised = frame.updatedAt >= 800 && frame.updatedAt < 1800;
      const wrist = { x: 0.5, y: raised ? 0.5 : 0.95 };
      return { ...frame, framing: framingFrame(frame.updatedAt, [[wrist, { x: 0.52, y: wrist.y - 0.05 }]], pose) };
    });
    const onSequence = vi.fn();
    const hook = renderHook(() => useAutomaticSignCapture({
      enabled: true, paused: false, captureContextKey: "server", videoRef: { current: video },
      captureVideoFrames: true, bodyFraming: true, onSequence,
    }));
    for (const frame of framed) await act(async () => { hook.result.current.ingest(frame); });
    expect(onSequence).toHaveBeenCalledOnce();
    expect(onSequence.mock.calls[0][2]).toHaveLength(16);
    // One snapshot per 100 ms: bitmap k was taken at k * 100 ms.
    const ids = sentIds(onSequence.mock.calls[0][2] as string[]);
    expect(Math.min(...ids)).toBeGreaterThanOrEqual(7);
    expect(Math.max(...ids)).toBeLessThanOrEqual(18);
    expect(context.fillRect).toHaveBeenCalledWith(0, 0, 224, 224);
    const [source, sx, sy, sw, sh] = context.drawImage.mock.calls.at(-1)!;
    expect(source).toBe(video);
    // Shoulder width 256 px -> 665.6 px square centred 38.4 px above the shoulders, clipped to the frame.
    expect(sx).toBeCloseTo(307.2, 6);
    expect(sy).toBe(0);
    expect(sw).toBeCloseTo(665.6, 6);
    expect(sh).toBeCloseTo(618.4, 6);
  });

  it("không gửi khi tay đứng yên, không có tay hoặc đang chờ inference", async () => {
    const { feed, onSequence, rerender } = mount();
    await feed(Array.from({ length: 90 }, (_, i) => tracking(i * 50, null)));
    await feed(Array.from({ length: 90 }, (_, i) => tracking(4500 + i * 50, 0.2)));
    expect(onSequence).not.toHaveBeenCalled();
    rerender({ enabled: true, paused: true, captureContextKey: "server" });
    const before = bitmaps.length;
    await feed(gesture(9000));
    expect(bitmaps).toHaveLength(before);
    expect(onSequence).not.toHaveBeenCalled();
  });

  it("giải phóng pre-roll ngay khi tắt camera", async () => {
    const { feed, rerender, result, onSequence } = mount();
    await feed(gesture().slice(0, 24));
    expect(result.current.phase).toBe("capturing");
    rerender({ enabled: false, paused: false, captureContextKey: "server" });
    expect(result.current.phase).toBe("off");
    expect(bitmaps.every((b) => vi.mocked(b.close).mock.calls.length === 1)).toBe(true);
    await feed(gesture(5000));
    expect(onSequence).not.toHaveBeenCalled();
  });

  it("bỏ encode cũ sau đổi route và không cho lượt thứ hai chen vào", async () => {
    const pending = deferred<string>();
    encoder.encode.mockImplementation((frame) => {
      frame.bitmap.close();
      return pending.promise;
    });
    const { feed, onSequence, result, rerender, onCaptureCancel } = mount();
    await feed(gesture());
    expect(result.current.phase).toBe("encoding");
    const encodedBefore = encoder.encode.mock.calls.length;
    await feed(gesture(5000));
    expect(encoder.encode).toHaveBeenCalledTimes(encodedBefore);
    rerender({ enabled: true, paused: false, captureContextKey: "local" });
    expect(encoder.dispose).toHaveBeenCalled();
    encoder.encode.mockImplementation(encodeById);
    await act(async () => pending.resolve("stale"));
    expect(onSequence).not.toHaveBeenCalled();
    expect(onCaptureCancel).toHaveBeenCalledOnce();
    expect(result.current.phase).toBe("waiting");
    await feed(gesture(9000));
    expect(onSequence).toHaveBeenCalledOnce();
  });

  it("đóng bitmap hoàn tất muộn sau khi đã unmount", async () => {
    const pending = deferred<ImageBitmap>();
    const bitmap = { close: vi.fn() } as unknown as ImageBitmap;
    vi.mocked(createImageBitmap).mockReturnValueOnce(pending.promise);
    const { result, unmount, onSequence } = mount();
    act(() => result.current.ingest(tracking(0, 0.2)));
    unmount();
    await act(async () => pending.resolve(bitmap));
    expect(bitmap.close).toHaveBeenCalledOnce();
    expect(onSequence).not.toHaveBeenCalled();
  });

  it("hủy encode đang chạy khi tạm dừng và thu được lượt mới sau khi tiếp tục", async () => {
    const pending = deferred<string>();
    encoder.encode.mockImplementation((frame) => {
      frame.bitmap.close();
      return pending.promise;
    });
    const { feed, result, rerender, onSequence, onCaptureCancel } = mount();
    await feed(gesture());
    expect(result.current.phase).toBe("encoding");

    rerender({ enabled: true, paused: true, captureContextKey: "server" });
    expect(result.current.phase).toBe("rearming");
    expect(onCaptureCancel).toHaveBeenCalledOnce();
    encoder.encode.mockImplementation(encodeById);
    await act(async () => pending.resolve("stale"));
    expect(onSequence).not.toHaveBeenCalled();

    rerender({ enabled: true, paused: false, captureContextKey: "server" });
    await feed(gesture(5000));
    expect(onSequence).toHaveBeenCalledOnce();
  });

  it("báo lỗi khi ảnh camera không đủ và cho phép thử lại", async () => {
    vi.mocked(createImageBitmap).mockRejectedValue(new Error("Camera frame unavailable"));
    const { feed, result, onSequence, onError } = mount();
    await feed(gesture());
    expect(onSequence).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalledWith("Không thu được đủ ảnh camera cho ký hiệu. Hãy thử lại.");
    expect(result.current.phase).toBe("waiting");

    vi.mocked(createImageBitmap).mockImplementation(async () => {
      const bitmap = {
        width: 224, height: 224, id: bitmaps.length, close: vi.fn(),
      } as unknown as ImageBitmap & { id: number };
      bitmaps.push(bitmap);
      return bitmap;
    });
    await feed(gesture(5000));
    expect(onSequence).toHaveBeenCalledOnce();
  });

  it("kết thúc lượt bị mất tracking mà không đủ frame tay", async () => {
    const { feed, result, onSequence, onCaptureStart, onCaptureCancel } = mount();
    await feed([
      tracking(0, null),
      tracking(50, 0.2),
      tracking(100, 0.225),
      tracking(150, 0.25),
      ...Array.from({ length: 25 }, (_, i) => tracking(200 + i * 50, null)),
    ]);
    expect(onCaptureStart).toHaveBeenCalledOnce();
    expect(onSequence).not.toHaveBeenCalled();
    expect(onCaptureCancel).toHaveBeenCalledOnce();
    expect(result.current.phase).toBe("cooldown");
  });

  it("giữ nguyên nhánh landmark và không tạo ảnh khi không dùng server", async () => {
    const onSequence = vi.fn();
    const { result } = renderHook(() => useAutomaticSignCapture({ enabled: true, paused: false, onSequence }));
    for (const frame of gesture()) act(() => result.current.ingest(frame));
    expect(onSequence).toHaveBeenCalledOnce();
    expect(onSequence.mock.calls[0][0]).toHaveLength(16);
    expect(createImageBitmap).not.toHaveBeenCalled();
    expect(encoder.encode).not.toHaveBeenCalled();
  });

  it("encode ảnh ngay trong lúc ký, chỉ giữ ảnh thô khi đang nghỉ", async () => {
    const { feed, result, onSequence } = mount();
    const frames = gesture();
    await feed(frames.slice(0, 16));
    expect(result.current.phase).toBe("waiting");
    expect(encoder.encode).not.toHaveBeenCalled();
    await feed(frames.slice(16, 30));
    expect(result.current.phase).toBe("capturing");
    const whileSigning = encoder.encode.mock.calls.length;
    // Pre-roll snapshots plus every new one are already with the encoder.
    expect(whileSigning).toBeGreaterThan(8);
    expect(onSequence).not.toHaveBeenCalled();
    await feed(frames.slice(30));
    expect(onSequence).toHaveBeenCalledOnce();
    expect(encoder.encode.mock.calls.length - whileSigning).toBeLessThan(15);
  });

  it("encodeMs chỉ đo phần chờ các ảnh cuối sau khi ký xong", async () => {
    const clock = vi.spyOn(performance, "now").mockReturnValue(100);
    const waiting: Array<() => void> = [];
    encoder.encode.mockImplementation((frame) => {
      frame.bitmap.close();
      return new Promise<string>((resolve) => waiting.push(() => resolve("data:image/webp;base64,AAAA")));
    });
    const { feed, onSequence, result } = mount();
    await feed(gesture());
    expect(result.current.phase).toBe("encoding");
    clock.mockReturnValue(160);
    await act(async () => waiting.forEach((resolve) => resolve()));
    const timing = onSequence.mock.calls[0][3];
    expect(timing.captureMs).toBeGreaterThan(1000);
    expect(timing.encodeMs).toBe(60);
    expect(onSequence.mock.calls[0][2]).toHaveLength(16);
  });

  it("thu đủ 6 ký hiệu RGB có khoảng nghỉ 1 giây, không bỏ lượt xen kẽ", async () => {
    const { feed, onSequence, result, onError, onCaptureStart } = mount();
    await feed(Array.from({ length: 16 }, (_, index) => tracking(index * 50, 0.2)));
    let timestamp = 800;
    for (let sign = 0; sign < 6; sign += 1) {
      const from = sign % 2 ? 0.675 : 0.2;
      const direction = sign % 2 ? -1 : 1;
      await feed(Array.from({ length: 20 }, (_, index) =>
        tracking(timestamp + index * 50, from + direction * index * 0.025),
      ));
      timestamp += 1000;
      await feed(Array.from({ length: 20 }, (_, index) =>
        tracking(timestamp + index * 50, from + direction * 19 * 0.025),
      ));
      timestamp += 1000;
      expect(onSequence).toHaveBeenCalledTimes(sign + 1);
      expect(result.current.phase).toBe("waiting");
    }
    expect(onCaptureStart).toHaveBeenCalledTimes(6);
    expect(onError).not.toHaveBeenCalled();
    expect(onSequence.mock.calls.every((call) => call[2].length === 16)).toBe(true);
    expect(bitmaps.every((bitmap) => vi.mocked(bitmap.close).mock.calls.length <= 1)).toBe(true);
  });

  it("tiếp tục sau hàng đợi đầy phải quan sát tay nghỉ trước khi nhận lượt mới", async () => {
    const { feed, rerender, result, onSequence } = mount();
    await feed(gesture());
    expect(onSequence).toHaveBeenCalledOnce();
    rerender({ enabled: true, paused: true, captureContextKey: "server" });
    expect(result.current.phase).toBe("rearming");
    rerender({ enabled: true, paused: false, captureContextKey: "server" });
    await feed(Array.from({ length: 30 }, (_, index) => tracking(3000 + index * 50, 0.2 + index * 0.025)));
    expect(onSequence).toHaveBeenCalledOnce();
    expect(result.current.phase).toBe("rearming");
    await feed(gesture(5000));
    expect(onSequence).toHaveBeenCalledTimes(2);
    expect(result.current.phase).toBe("waiting");
  });
});
