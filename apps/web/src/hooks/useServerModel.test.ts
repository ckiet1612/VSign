import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useServerModel, type ServerModelOption } from "./useServerModel";

const labels = [...Array.from({ length: 30 }, (_, i) => `word-${i}`), "Không ký hiệu"];
const options: ServerModelOption[] = [
  { id: "current", label: "Hiện tại", httpUrl: "http://localhost:8000", wsUrl: "ws://localhost:8000/ws/inference" },
  { id: "seated", label: "Seated + Personal", httpUrl: "http://localhost:8003", wsUrl: "ws://localhost:8003/ws/inference" },
];
const metadata = { backend: "coreml", model_version: "sales30-mvitv2s-seated-personal-v1-head-epoch20",
  protocol_version: "1.0", frame_count: 16, frame_width: 224, frame_height: 224,
  supported_image_formats: ["image/jpeg", "image/webp"], confidence_threshold: .7, margin_threshold: .15,
  labels, collection_labels: labels.slice(0, 30), candidate_labels_unverified: false, mock: false,
  collection_enabled: false, collection_target_per_hand: 50, sentence_ai_enabled: false };

afterEach(() => vi.unstubAllGlobals());

describe("server model selection", () => {
  it("defaults to the old endpoint and commits the candidate only after validation", async () => {
    let complete!: (value: Response) => void;
    vi.stubGlobal("fetch", () => new Promise<Response>(resolve => { complete = resolve; }));
    const { result } = renderHook(() => useServerModel(options));
    expect(result.current.active.id).toBe("current");
    let pending!: Promise<unknown>;
    act(() => { pending = result.current.choose("seated", labels); });
    expect(result.current.switching).toBe(true);
    expect(result.current.active.httpUrl).toBe("http://localhost:8000");
    await act(async () => { complete(new Response(JSON.stringify(metadata))); await pending; });
    expect(result.current.active.id).toBe("seated");
    expect(result.current.switching).toBe(false);
    await act(async () => {
      const back = result.current.choose("current", labels);
      complete(new Response(JSON.stringify({ ...metadata, model_version: "sales30-mvitv2s-personal-v1-head-epoch29" })));
      await back;
    });
    expect(result.current.active.id).toBe("current");
  });

  it.each(["offline", "labels", "threshold", "mock", "version", "shape", "unverified"])(
    "keeps the old model when candidate validation fails: %s", async kind => {
      const body = structuredClone(metadata);
      if (kind === "labels") body.labels.reverse();
      if (kind === "threshold") body.confidence_threshold = .3;
      if (kind === "mock") body.mock = true;
      if (kind === "version") body.model_version = "unrelated-model";
      if (kind === "shape") body.frame_count = 8;
      if (kind === "unverified") body.candidate_labels_unverified = true;
      vi.stubGlobal("fetch", async () => {
        if (kind === "offline") throw new Error("offline");
        return new Response(JSON.stringify(body));
      });
      const { result } = renderHook(() => useServerModel(options));
      await act(async () => { expect(await result.current.choose("seated", labels)).toBeNull(); });
      expect(result.current.active.id).toBe("current");
      expect(result.current.error).not.toBe("");
      expect(result.current.switching).toBe(false);
    },
  );

  it("ignores a response that arrives after unmount", async () => {
    let complete!: (value: Response) => void;
    vi.stubGlobal("fetch", () => new Promise<Response>(resolve => { complete = resolve; }));
    const { result, unmount } = renderHook(() => useServerModel(options));
    let pending!: Promise<unknown>;
    act(() => { pending = result.current.choose("seated", labels); });
    unmount();
    complete(new Response(JSON.stringify(metadata)));
    expect(await pending).toBeNull();
  });
});
