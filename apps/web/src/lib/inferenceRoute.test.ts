import { describe, expect, it } from "vitest";
import * as inferenceRoute from "./inferenceRoute";

const { chooseInferenceRoute } = inferenceRoute;

describe("chooseInferenceRoute", () => {
  it("ưu tiên máy chủ khi kết nối sẵn sàng", () => {
    expect(
      chooseInferenceRoute({
        publicDemo: false,
        serverConnected: true,
        localReady: true,
      }),
    ).toBe("server");
  });

  it("dùng model local làm fallback khi máy chủ mất kết nối", () => {
    expect(
      chooseInferenceRoute({
        publicDemo: false,
        serverConnected: false,
        localReady: true,
      }),
    ).toBe("local");
  });

  it("không gửi video lên máy chủ ở public demo", () => {
    expect(
      chooseInferenceRoute({
        publicDemo: true,
        serverConnected: true,
        localReady: true,
      }),
    ).toBe("local");
  });

  it("không dùng máy chủ ở public demo khi model local chưa sẵn sàng", () => {
    expect(
      chooseInferenceRoute({
        publicDemo: true,
        serverConnected: true,
        localReady: false,
      }),
    ).toBe("unavailable");
  });
});

describe("chooseCapturePipeline", () => {
  const chooseCapturePipeline = (
    inferenceRoute as typeof inferenceRoute & {
      chooseCapturePipeline?: (input: {
        purpose: "recognize" | "collect";
        inferenceRoute: "server" | "local" | "unavailable";
      }) => {
        sampling: "uniform" | "motion-weighted";
        framing: "fixed" | "adaptive";
      };
    }
  ).chooseCapturePipeline;

  it("dùng pipeline RGB đã đồng bộ khi nhận dạng qua server", () => {
    expect(chooseCapturePipeline).toBeTypeOf("function");
    expect(
      chooseCapturePipeline!({ purpose: "recognize", inferenceRoute: "server" }),
    ).toEqual({ sampling: "uniform", framing: "fixed" });
  });

  it("dùng cùng pipeline RGB khi thu dữ liệu fine-tune", () => {
    expect(chooseCapturePipeline).toBeTypeOf("function");
    expect(
      chooseCapturePipeline!({ purpose: "collect", inferenceRoute: "local" }),
    ).toEqual({ sampling: "uniform", framing: "fixed" });
  });

  it("giữ pipeline chuyển động cho model landmark local", () => {
    expect(chooseCapturePipeline).toBeTypeOf("function");
    expect(
      chooseCapturePipeline!({ purpose: "recognize", inferenceRoute: "local" }),
    ).toEqual({ sampling: "motion-weighted", framing: "adaptive" });
  });
});
