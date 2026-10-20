import { describe, expect, it } from "vitest";
import { AutomaticInferenceQueue } from "./automaticInferenceQueue";

function job(sequence: number) {
  return { sequence, frame: `capture-${sequence}` };
}

describe("bounded automatic inference FIFO", () => {
  it("giữ một lượt chạy và hai lượt chờ, không ghi đè khi đầy", () => {
    const queue = new AutomaticInferenceQueue<ReturnType<typeof job>>();
    expect(queue.enqueue(job(0), 100)).toBe(true);
    expect(queue.startNext(110)?.sequence).toBe(0);
    expect(queue.enqueue(job(1), 120)).toBe(true);
    expect(queue.enqueue(job(2), 130)).toBe(true);
    expect(queue.full).toBe(true);
    expect(queue.pendingCount).toBe(2);
    expect(queue.enqueue(job(3), 140)).toBe(false);
    expect(queue.startNext(150)).toBeNull();

    expect(queue.complete(0, 200)?.cancelled).toBe(false);
    expect(queue.startNext(200)?.sequence).toBe(1);
    expect(queue.full).toBe(false);
    queue.complete(1, 250);
    expect(queue.startNext(250)?.sequence).toBe(2);
    queue.complete(2, 300);
    expect(queue.startNext(300)).toBeNull();
    expect(queue.busy).toBe(false);
  });

  it("reply sai sequence hoặc lặp không giải phóng inference đang chạy", () => {
    const queue = new AutomaticInferenceQueue<ReturnType<typeof job>>();
    queue.enqueue(job(10), 0);
    queue.startNext(10);
    queue.enqueue(job(11), 15);
    expect(queue.complete(9, 20)).toBeNull();
    expect(queue.busy).toBe(true);
    expect(queue.startNext(20)).toBeNull();
    queue.complete(10, 30);
    queue.startNext(30);
    expect(queue.complete(10, 40)).toBeNull();
    expect(queue.busy).toBe(true);
    expect(queue.complete(11, 50)?.job.frame).toBe("capture-11");
  });

  it("hủy lượt chờ nhưng giữ slot đã gửi đến khi reply cũ về", () => {
    const queue = new AutomaticInferenceQueue<ReturnType<typeof job>>();
    queue.enqueue(job(0), 0);
    queue.startNext(10);
    queue.enqueue(job(1), 20);
    queue.enqueue(job(2), 30);
    queue.cancel();
    expect(queue.pendingCount).toBe(0);
    expect(queue.busy).toBe(true);
    expect(queue.enqueue(job(3), 40)).toBe(true);
    expect(queue.startNext(50)).toBeNull();
    expect(queue.complete(0, 100)?.cancelled).toBe(true);
    expect(queue.startNext(100)?.sequence).toBe(3);
    expect(queue.complete(3, 130)?.cancelled).toBe(false);
  });

  it("đo chờ hàng đợi và phản hồi bằng cùng đồng hồ monotonic", () => {
    const queue = new AutomaticInferenceQueue<ReturnType<typeof job>>();
    queue.enqueue(job(7), 100);
    queue.startNext(350);
    expect(queue.complete(7, 950)).toEqual({
      job: job(7), cancelled: false, queueWaitMs: 250, responseMs: 600,
    });
  });

  it("không nhận trùng sequence hoặc tạo thời gian âm", () => {
    const queue = new AutomaticInferenceQueue<ReturnType<typeof job>>();
    queue.enqueue(job(5), 100);
    expect(queue.enqueue(job(5), 101)).toBe(false);
    queue.startNext(90);
    expect(queue.enqueue(job(5), 102)).toBe(false);
    expect(queue.complete(5, 80)).toMatchObject({ queueWaitMs: 0, responseMs: 0 });
  });
});
