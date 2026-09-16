import { useCallback, useEffect, useRef, useState } from "react";
import type { PredictionMessage } from "@contracts";
import wasmUrl from "onnxruntime-web/ort-wasm-simd-threaded.wasm?url";
import {
  averageLogitViews,
  flattenLandmarkBatch,
  BASELINE_MODEL_VERSION,
  LANDMARK_MODEL_VERSION,
  V5_MODEL_VERSION,
  landmarkInferenceViews,
  predictionFromLogits,
  type LandmarkRuntime,
  type PredictionThresholds,
} from "../lib/landmarkInference";
import {
  hasHandLandmarks,
  LANDMARK_FEATURE_DIM,
  LANDMARK_SEQUENCE_LENGTH,
} from "../lib/landmarkFeatures";
import {
  BASELINE_FEATURE_DIM,
  baselineInferenceViews,
  hasBaselineHandLandmarks,
} from "../lib/landmarkFeaturesV3";
import {
  hasV5HandLandmarks,
  V5_FEATURE_DIM,
  v5InferenceViews,
} from "../lib/landmarkFeaturesV5";

type LocalModelStatus = "loading" | "ready" | "unavailable";
type OrtModule = typeof import("onnxruntime-web/wasm");
type OrtSession = import("onnxruntime-web").InferenceSession;

export interface LandmarkInferenceController {
  status: LocalModelStatus;
  labels: string[];
  error: string | null;
  runtime: LandmarkRuntime;
  modelVersion: string;
  predict: (
    frames: readonly (readonly number[])[],
    sequence: number,
    thresholds?: PredictionThresholds,
  ) => Promise<PredictionMessage>;
}

const RUNTIME_ARTIFACTS = {
  v3: {
    model: "vsign-landmark-keyframe-v3.onnx",
    labels: "vsign-landmark-v2.labels.json",
    version: BASELINE_MODEL_VERSION,
    featureDim: BASELINE_FEATURE_DIM,
    views: baselineInferenceViews,
    hasHands: hasBaselineHandLandmarks,
  },
  v4_2: {
    model: "vsign-landmark-v4.onnx",
    labels: "vsign-landmark-v4.labels.json",
    version: LANDMARK_MODEL_VERSION,
    featureDim: LANDMARK_FEATURE_DIM,
    views: landmarkInferenceViews,
    hasHands: hasHandLandmarks,
  },
  v5: {
    model: "vsign-landmark-v5.onnx",
    labels: "vsign-landmark-v5.labels.json",
    version: V5_MODEL_VERSION,
    featureDim: V5_FEATURE_DIM,
    views: v5InferenceViews,
    hasHands: hasV5HandLandmarks,
  },
} as const;

export function useLandmarkInference(
  runtime: LandmarkRuntime,
): LandmarkInferenceController {
  const modelRef = useRef<OrtSession | null>(null);
  const ortRef = useRef<OrtModule | null>(null);
  const labelsRef = useRef<string[]>([]);
  const [status, setStatus] = useState<LocalModelStatus>("loading");
  const [labels, setLabels] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let disposed = false;
    const baseUrl = import.meta.env.BASE_URL;
    const artifact = RUNTIME_ARTIFACTS[runtime];
    setStatus("loading");
    setError(null);
    setLabels([]);
    labelsRef.current = [];
    void Promise.all([
      import("onnxruntime-web/wasm"),
      fetch(
        `${baseUrl}models/${artifact.labels}?v=${encodeURIComponent(artifact.version)}`,
      ).then(
        async (response) => {
          if (!response.ok) throw new Error("Không tải được nhãn AI local.");
          const value: unknown = await response.json();
          if (!Array.isArray(value) || !value.every((item) => typeof item === "string")) {
            throw new Error("Nhãn AI local không hợp lệ.");
          }
          return value as string[];
        },
      ),
    ])
      .then(async ([ort, modelLabels]) => {
        ort.env.wasm.numThreads = 1;
        ort.env.wasm.wasmPaths = { wasm: wasmUrl };
        const sessionOptions = {
          executionProviders: ["wasm"] as const,
          graphOptimizationLevel: "all" as const,
        };
        const session = await ort.InferenceSession.create(
          `${baseUrl}models/${artifact.model}?v=${encodeURIComponent(artifact.version)}`,
          sessionOptions,
        );
        if (disposed) {
          await session.release();
          return;
        }
        ortRef.current = ort;
        modelRef.current = session;
        labelsRef.current = modelLabels;
        setLabels(modelLabels);
        setError(null);
        setStatus("ready");
      })
      .catch((reason: unknown) => {
        if (!disposed) {
          setError(
            reason instanceof Error
              ? reason.message
              : "Không khởi tạo được model local.",
          );
          setStatus("unavailable");
        }
      });
    return () => {
      disposed = true;
      const model = modelRef.current;
      modelRef.current = null;
      if (model) void model.release();
    };
  }, [runtime]);

  const predict = useCallback(
    async (
      frames: readonly (readonly number[])[],
      sequence: number,
      thresholds?: PredictionThresholds,
    ): Promise<PredictionMessage> => {
      const model = modelRef.current;
      const ort = ortRef.current;
      if (!model || !ort || !labelsRef.current.length) {
        throw new Error("AI realtime chưa sẵn sàng.");
      }
      const artifact = RUNTIME_ARTIFACTS[runtime];
      const views = artifact.views(frames);
      const input = new ort.Tensor(
        "float32",
        flattenLandmarkBatch(views, artifact.featureDim),
        [views.length, LANDMARK_SEQUENCE_LENGTH, artifact.featureDim],
      );
      try {
        const outputs = await model.run({ landmarks: input });
        const tensor = outputs.logits ?? outputs[model.outputNames[0]];
        if (!tensor) throw new Error("Model AI không trả kết quả.");
        const logits = averageLogitViews(
          Array.from(tensor.data as Float32Array),
          views.length,
          labelsRef.current.length,
        );
        return predictionFromLogits(
          logits,
          labelsRef.current,
          frames,
          sequence,
          thresholds,
          { modelVersion: artifact.version, hasHands: artifact.hasHands },
        );
      } catch (reason) {
        modelRef.current = null;
        setError(
          reason instanceof Error ? reason.message : "Model local gặp lỗi.",
        );
        setStatus("unavailable");
        void model.release();
        throw reason;
      }
    },
    [runtime],
  );

  return {
    status,
    labels,
    error,
    runtime,
    modelVersion: RUNTIME_ARTIFACTS[runtime].version,
    predict,
  };
}
