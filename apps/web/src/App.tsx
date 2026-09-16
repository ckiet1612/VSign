import {
  type PointerEvent as ReactPointerEvent,
  useCallback,
  useEffect,
  useReducer,
  useRef,
  useState,
} from "react";
import type {
  CaptureDistance,
  CaptureLighting,
  CollectionHand,
  CollectionHandCounts,
  CollectionSampleRequest,
  CollectionSampleResponse,
  CollectionSummaryResponse,
  FramesMessage,
  InferenceMetadata,
  NegativeAction,
  PredictionMessage,
} from "@contracts";
import {
  CameraPanel,
  type CaptureInputMode,
} from "./components/CameraPanel";
import type { HandTrackingFrame } from "./components/HandTrackingOverlay";
import {
  CollectionPanel,
  type PendingCollectionSample,
} from "./components/CollectionPanel";
import { ResultPanel } from "./components/ResultPanel";
import { TranscriptPanel } from "./components/TranscriptPanel";
import { config } from "./config";
import { useCamera } from "./hooks/useCamera";
import { useAutomaticSignCapture } from "./hooks/useAutomaticSignCapture";
import { useAutomaticCollectionCycle } from "./hooks/useAutomaticCollectionCycle";
import { useInferenceSocket } from "./hooks/useInferenceSocket";
import { useLandmarkInference } from "./hooks/useLandmarkInference";
import { useSignCapture } from "./hooks/useSignCapture";
import { copyText } from "./lib/copy";
import { shouldStartSpaceCapture } from "./lib/keyboard";
import {
  DEFAULT_LANDMARK_RUNTIME,
  IDLE_LABEL,
  type LandmarkRuntime,
} from "./lib/landmarkInference";
import { combineV5LandmarkSequence } from "./lib/landmarkFeaturesV5";
import { hasBaselineHandLandmarks } from "./lib/landmarkFeaturesV3";
import { v5CollectionTargetsFor } from "./lib/v5CollectionPlan";
import { REFERENCE_SIGNS } from "./referenceSigns";
import {
  inferenceReducer,
  initialInferenceState,
} from "./state/inferenceMachine";
import {
  initialTranscriptState,
  TRANSCRIPT_COOLDOWN_MS,
  transcriptReducer,
} from "./state/transcript";

function createSessionId(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (character) => {
    const random = Math.floor(Math.random() * 16);
    const value = character === "x" ? random : (random & 0x3) | 0x8;
    return value.toString(16);
  });
}

type AppMode = "recognize" | "collect";

function framesForRuntime(
  runtime: LandmarkRuntime,
  contextualFrames: readonly (readonly number[])[],
  baselineFrames: readonly (readonly number[])[],
): number[][] {
  if (runtime === "v3") return baselineFrames.map((frame) => Array.from(frame));
  if (runtime === "v5") {
    return combineV5LandmarkSequence(baselineFrames, contextualFrames);
  }
  return contextualFrames.map((frame) => Array.from(frame));
}

const AUTOMATIC_PREDICTION_THRESHOLDS = {
  confidence: 0.66,
  margin: 0.24,
} as const;

export default function App() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const sequenceRef = useRef(0);
  const sessionIdRef = useRef(createSessionId());
  const spaceHeldRef = useRef(false);
  const trackingFrameRef = useRef<HandTrackingFrame | null>(null);
  const continueAutomaticCollectionRef = useRef<() => void>(() => undefined);
  const [inference, dispatchInference] = useReducer(
    inferenceReducer,
    initialInferenceState,
  );
  const [transcript, dispatchTranscript] = useReducer(
    transcriptReducer,
    initialTranscriptState,
  );
  const [notice, setNotice] = useState("");
  const [metadata, setMetadata] = useState<InferenceMetadata | null>(null);
  const [metadataError, setMetadataError] = useState(false);
  const [mode, setMode] = useState<AppMode>("recognize");
  const [captureInputMode, setCaptureInputMode] =
    useState<CaptureInputMode>("manual");
  const [selectedLabel, setSelectedLabel] = useState(REFERENCE_SIGNS[0].label);
  const [selectedHand, setSelectedHand] = useState<CollectionHand>("right");
  const [selectedDistance, setSelectedDistance] =
    useState<CaptureDistance>("standard");
  const [selectedLighting, setSelectedLighting] =
    useState<CaptureLighting>("normal");
  const [selectedNegativeAction, setSelectedNegativeAction] =
    useState<NegativeAction>("still");
  const [pendingSample, setPendingSample] =
    useState<PendingCollectionSample | null>(null);
  const [collectionCounts, setCollectionCounts] = useState<
    Record<string, CollectionHandCounts>
  >({});
  const [collectionNotice, setCollectionNotice] = useState("");
  const [savingSample, setSavingSample] = useState(false);
  const [landmarkRuntime, setLandmarkRuntime] =
    useState<LandmarkRuntime>(DEFAULT_LANDMARK_RUNTIME);

  const handlePrediction = useCallback((prediction: PredictionMessage) => {
    dispatchInference({ type: "prediction_received", prediction });
  }, []);
  const socket = useInferenceSocket(
    config.publicDemo ? null : config.inferenceWsUrl,
    handlePrediction,
  );
  const localModel = useLandmarkInference(landmarkRuntime);
  const predictLandmarks = localModel.predict;
  const camera = useCamera(videoRef);
  const handleAutomaticSequence = useCallback(
    (landmarkFrames: number[][], baselineLandmarkFrames: number[][]) => {
      const sequence = sequenceRef.current;
      sequenceRef.current += 1;
      dispatchInference({ type: "request_started", sequence });
      void predictLandmarks(
          framesForRuntime(
            landmarkRuntime,
            landmarkFrames,
            baselineLandmarkFrames,
          ),
          sequence,
          AUTOMATIC_PREDICTION_THRESHOLDS,
        )
        .then(handlePrediction)
        .catch(() =>
          dispatchInference({
            type: "failed",
            message:
              "AI tự động gặp lỗi tạm thời. Hãy chuyển sang “Giữ để ký” và thử lại.",
          }),
        );
    },
    [handlePrediction, landmarkRuntime, predictLandmarks],
  );
  const automaticCapture = useAutomaticSignCapture({
    enabled:
      mode === "recognize" &&
      captureInputMode === "automatic" &&
      camera.status === "ready" &&
      localModel.status === "ready",
    paused: inference.pendingSequence !== null,
    onSequence: handleAutomaticSequence,
  });
  const automaticPhase = automaticCapture.phase;
  const ingestAutomaticFrame = automaticCapture.ingest;
  const handleTrackingFrame = useCallback((frame: HandTrackingFrame) => {
    trackingFrameRef.current = frame;
    ingestAutomaticFrame(frame);
  }, [ingestAutomaticFrame]);
  const getFreshCropRegion = useCallback(() => {
    const frame = trackingFrameRef.current;
    if (
      !frame ||
      !frame.crop ||
      !frame.handCount ||
      performance.now() - frame.updatedAt > 500
    ) {
      return null;
    }
    return frame.crop;
  }, []);
  const getFreshLandmarkFeatures = useCallback(() => {
    const frame = trackingFrameRef.current;
    if (
      !frame?.features ||
      performance.now() - frame.updatedAt > 500
    ) {
      return null;
    }
    return frame.features;
  }, []);
  const getFreshBaselineLandmarkFeatures = useCallback(() => {
    const frame = trackingFrameRef.current;
    if (
      !frame?.baselineFeatures ||
      performance.now() - frame.updatedAt > 500
    ) {
      return null;
    }
    return frame.baselineFeatures;
  }, []);

  useEffect(() => {
    if (socket.status === "connected" || localModel.status === "ready") {
      dispatchInference({ type: "connection_ready" });
    } else if (
      socket.status === "disconnected" &&
      localModel.status === "unavailable"
    ) {
      dispatchInference({ type: "connection_lost" });
    }
  }, [localModel.status, socket.status]);

  useEffect(() => {
    if (config.publicDemo) return;
    const controller = new AbortController();
    fetch(`${config.inferenceHttpUrl}/metadata`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error("metadata unavailable");
        return response.json() as Promise<InferenceMetadata>;
      })
      .then((body) => {
        setMetadata(body);
        setMetadataError(false);
      })
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setMetadataError(true);
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (config.publicDemo) return;
    if (!metadata?.collection_enabled) return;
    const controller = new AbortController();
    fetch(`${config.inferenceHttpUrl}/collection/summary`, {
      signal: controller.signal,
    })
      .then((response) => {
        if (!response.ok) throw new Error("collection summary unavailable");
        return response.json() as Promise<CollectionSummaryResponse>;
      })
      .then((body) => {
        setCollectionCounts(body.counts);
        setCollectionNotice("");
      })
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setCollectionNotice("Chưa đọc được tiến độ các mẫu đã lưu.");
        }
      });
    return () => controller.abort();
  }, [metadata?.collection_enabled]);

  const canCapture =
    camera.status === "ready" &&
    (localModel.status === "ready" || socket.status === "connected") &&
    inference.pendingSequence === null &&
    (mode === "collect" || captureInputMode === "manual") &&
    (mode === "recognize" || pendingSample === null);

  const capture = useSignCapture({
    videoRef,
    canStart: canCapture,
    encodeVideoFrames:
      mode === "collect" || localModel.status !== "ready",
    preserveSourceFrames: mode === "collect",
    getCropRegion: getFreshCropRegion,
    getLandmarkFeatures: getFreshLandmarkFeatures,
    getBaselineLandmarkFeatures: getFreshBaselineLandmarkFeatures,
    onCaptureStart: () => dispatchInference({ type: "capture_started" }),
    onCaptureCancel: () =>
      dispatchInference({
        type: "capture_cancelled",
        message: "Đã hủy lượt thu vì camera hoặc kết nối không còn sẵn sàng.",
      }),
    onTooShort: (message) =>
      {
        dispatchInference({ type: "capture_cancelled", message });
        continueAutomaticCollectionRef.current();
      },
    onError: (message) => {
      dispatchInference({ type: "failed", message });
      continueAutomaticCollectionRef.current();
    },
    onFrames: (captured) => {
      const sequence = sequenceRef.current;
      sequenceRef.current += 1;
      const capturedAt = Date.now();
      if (mode === "collect") {
        const sourceFrames = captured.sourceFrames ?? captured.frames;
        const automaticCollection = captureInputMode === "automatic";
        const detectedHandFrames = captured.baselineLandmarkFrames.filter(
          hasBaselineHandLandmarks,
        ).length;
        if (
          automaticCollection &&
          (sourceFrames.length < 8 ||
            (selectedLabel !== IDLE_LABEL && detectedHandFrames < 8))
        ) {
          setCollectionNotice(
            "Đã bỏ lượt tự động vì chưa thấy tay đủ lâu. Hệ thống sẽ đếm ngược lại; hãy giữ trọn bàn tay trong khung.",
          );
          dispatchInference({
            type: "capture_cancelled",
            message: "Lượt tự động chưa đủ dữ liệu tay để lưu.",
          });
          continueAutomaticCollectionRef.current();
          return;
        }
        setPendingSample({
          sequence,
          expectedLabel: selectedLabel,
          hand: selectedHand,
          durationMs: captured.durationMs,
          capturedAt,
          frames: sourceFrames,
          distance: selectedDistance,
          lighting: selectedLighting,
          negativeAction:
            selectedLabel === "Không ký hiệu" ? selectedNegativeAction : null,
        });
        setCollectionNotice(
          automaticCollection
            ? "Đã thu đủ hình tay. Hệ thống đang kiểm tra rồi tự lưu lượt này."
            : "Mẫu đang nằm trong bộ nhớ. Kiểm tra kết quả rồi bấm Lưu mẫu vào máy.",
        );
      }
      dispatchInference({ type: "request_started", sequence });
      const sendToServer = () => {
        if (!captured.frames.length) {
          dispatchInference({
            type: "failed",
            message:
              "AI realtime gặp lỗi tạm thời. Hãy thử lại; model máy chủ sẽ được dùng dự phòng.",
          });
          return;
        }
        const message: FramesMessage = {
          type: "frames",
          session_id: sessionIdRef.current,
          sequence,
          captured_at: capturedAt,
          frames: captured.frames,
        };
        try {
          socket.sendFrames(message);
        } catch {
          dispatchInference({ type: "connection_lost" });
        }
      };
      if (localModel.status === "ready") {
        void localModel
          .predict(
            framesForRuntime(
              landmarkRuntime,
              captured.landmarkFrames,
              captured.baselineLandmarkFrames,
            ),
            sequence,
          )
          .then(handlePrediction)
          .catch(sendToServer);
      } else {
        sendToServer();
      }
    },
  });

  const automaticCollectionEnabled =
    mode === "collect" && captureInputMode === "automatic";
  const automaticCollection = useAutomaticCollectionCycle({
    enabled: automaticCollectionEnabled,
    ready:
      camera.status === "ready" &&
      (localModel.status === "ready" || socket.status === "connected"),
    blocked:
      pendingSample !== null ||
      savingSample ||
      inference.pendingSequence !== null,
    captureStatus: capture.status,
    onStart: capture.start,
    onStop: capture.stop,
  });
  continueAutomaticCollectionRef.current =
    automaticCollection.continueAfterRejectedTake;

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (captureInputMode === "automatic") return;
      if (!shouldStartSpaceCapture(event)) return;
      event.preventDefault();
      spaceHeldRef.current = true;
      capture.start();
    };
    const handleKeyUp = (event: KeyboardEvent) => {
      if (event.code !== "Space" || !spaceHeldRef.current) return;
      event.preventDefault();
      spaceHeldRef.current = false;
      capture.stop();
    };
    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("keyup", handleKeyUp);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
    };
  }, [capture, captureInputMode]);

  useEffect(() => {
    if (
      capture.status === "capturing" &&
      (camera.status !== "ready" ||
        (socket.status !== "connected" && localModel.status !== "ready"))
    ) {
      capture.cancel();
    }
  }, [camera.status, capture, localModel.status, socket.status]);

  const handlePointerDown = (event: ReactPointerEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    capture.start();
  };
  const finishPointerCapture = (event: ReactPointerEvent<HTMLButtonElement>) => {
    event.preventDefault();
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    capture.stop();
  };

  const addPrediction = () => {
    if (
      inference.phase !== "ok" ||
      inference.prediction?.status !== "ok" ||
      !inference.prediction.label
    ) {
      return;
    }
    const now = Date.now();
    const lastAdded = transcript.lastAdded;
    if (
      lastAdded?.label === inference.prediction.label &&
      now - lastAdded.at < TRANSCRIPT_COOLDOWN_MS
    ) {
      setNotice("Từ giống nhau vừa được thêm. Hãy chờ một giây trước khi thêm lại.");
      return;
    }
    dispatchTranscript({ type: "add", label: inference.prediction.label, at: now });
    setNotice(`Đã thêm “${inference.prediction.label}” vào câu.`);
  };

  const copyTranscript = async () => {
    try {
      await copyText(transcript.words.join(" "));
      setNotice("Đã sao chép câu.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Không thể sao chép câu.");
    }
  };

  const switchMode = (nextMode: AppMode) => {
    if (nextMode === "collect" && !metadata?.collection_enabled) return;
    setMode(nextMode);
    if (nextMode === "collect") setCaptureInputMode("manual");
    setPendingSample(null);
    setCollectionNotice("");
  };

  const saveCollectionSample = useCallback(async () => {
    if (!pendingSample || savingSample) return;
    const prediction =
      inference.prediction?.sequence === pendingSample.sequence
        ? inference.prediction
        : null;
    const topPrediction = prediction?.top_k[0] ?? null;
    const payload: CollectionSampleRequest = {
      session_id: sessionIdRef.current,
      captured_at: pendingSample.capturedAt,
      duration_ms: pendingSample.durationMs,
      expected_label: pendingSample.expectedLabel,
      hand: pendingSample.hand,
      frames: pendingSample.frames,
      predicted_label: prediction?.label ?? topPrediction?.label ?? null,
      predicted_confidence:
        prediction?.confidence ?? topPrediction?.confidence ?? null,
      distance: pendingSample.distance,
      lighting: pendingSample.lighting,
      negative_action: pendingSample.negativeAction,
    };
    setSavingSample(true);
    setCollectionNotice("");
    try {
      const response = await fetch(
        `${config.inferenceHttpUrl}/collection/samples`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
      );
      if (!response.ok) {
        const failure = (await response.json().catch(() => null)) as
          | { detail?: string }
          | null;
        throw new Error(failure?.detail ?? "Máy chủ không thể lưu mẫu.");
      }
      const saved = (await response.json()) as CollectionSampleResponse;
      setCollectionCounts((current) => {
        const existing = current[saved.expected_label] ?? { right: 0, left: 0 };
        return {
          ...current,
          [saved.expected_label]: {
            ...existing,
            [saved.hand]: saved.label_hand_count,
          },
        };
      });
      setPendingSample(null);
      const target = v5CollectionTargetsFor(
        saved.expected_label,
        metadata?.collection_target_per_hand ?? 12,
      )[saved.hand];
      const completedHand = saved.label_hand_count >= target;
      if (automaticCollectionEnabled && completedHand) {
        setCaptureInputMode("manual");
      }
      setCollectionNotice(
        automaticCollectionEnabled && completedHand
          ? `Đã đủ ${saved.label_hand_count}/${target} mẫu “${saved.expected_label}” · ${saved.hand === "right" ? "tay phải" : "tay trái"}. Phiên tự động đã dừng để bạn đổi tay hoặc đổi từ.`
          : automaticCollectionEnabled
            ? `Đã tự lưu mẫu ${saved.label_hand_count}/${target} cho “${saved.expected_label}” · ${saved.hand === "right" ? "tay phải" : "tay trái"}. Chuẩn bị lượt tiếp theo.`
            : `Đã lưu mẫu ${saved.label_hand_count}/${target} cho “${saved.expected_label}” · ${saved.hand === "right" ? "tay phải" : "tay trái"}.`,
      );
    } catch (error) {
      if (automaticCollectionEnabled) setCaptureInputMode("manual");
      setCollectionNotice(
        `${error instanceof Error ? error.message : "Không thể lưu mẫu video."}${automaticCollectionEnabled ? " Phiên tự động đã dừng để tránh lưu lặp." : ""}`,
      );
    } finally {
      setSavingSample(false);
    }
  }, [
    automaticCollectionEnabled,
    inference.prediction,
    metadata?.collection_target_per_hand,
    pendingSample,
    savingSample,
  ]);

  useEffect(() => {
    if (
      !automaticCollectionEnabled ||
      !pendingSample ||
      savingSample ||
      inference.pendingSequence !== null
    ) {
      return;
    }
    void saveCollectionSample();
  }, [
    automaticCollectionEnabled,
    inference.pendingSequence,
    pendingSample,
    saveCollectionSample,
    savingSample,
  ]);

  const selectLandmarkRuntime = (runtime: LandmarkRuntime) => {
    if (runtime === landmarkRuntime) return;
    dispatchInference({ type: "connection_lost" });
    setLandmarkRuntime(runtime);
  };

  const visiblePhase =
    capture.status === "capturing" ||
    automaticPhase === "capturing" || automaticPhase === "postroll"
      ? "capturing"
      : capture.status === "encoding"
        ? "processing"
        : inference.phase;
  const mockMode =
    !config.publicDemo &&
    localModel.status !== "ready" &&
    (metadata?.mock ?? true);
  const labelsVerified =
    localModel.status === "ready" ||
    metadata?.candidate_labels_unverified === false;
  const collectionEnabled =
    !config.publicDemo && metadata?.collection_enabled === true;
  const recognitionLabels = localModel.labels.length
    ? localModel.labels
    : metadata?.labels.length
    ? metadata.labels
    : REFERENCE_SIGNS.map((item) => item.label);
  const collectionLabels = [
    ...recognitionLabels.filter((label) => label !== IDLE_LABEL),
    IDLE_LABEL,
  ];
  const selectedCollectionTargets = v5CollectionTargetsFor(
    selectedLabel,
    metadata?.collection_target_per_hand ?? 12,
  );

  return (
    <div className="app-shell">
      <header className="app-header">
        <a className="brand" href="#workspace" aria-label="VSign, về khu vực làm việc">
          <span className="brand-mark" aria-hidden="true">VS</span>
          <span><strong>VSign</strong><small>Nhận dạng ký hiệu VSL rời rạc</small></span>
        </a>
        <p>Thử nghiệm từng từ · Không phải dịch hội thoại liên tục</p>
      </header>

      {mockMode && (
        <div className="mock-banner" role="status">
          <strong>Mô phỏng – chưa dùng mô hình AI thật.</strong>
          <span>Common-20 đã được chốt từ ViSignLanguage-Video; kết quả ở chế độ này chỉ là mô phỏng.</span>
        </div>
      )}
      {!mockMode && !labelsVerified && (
        !config.publicDemo &&
        <div className="ai-banner" role="status">
          <strong>AI baseline legacy đang hoạt động.</strong>
          <span>
            Đây là checkpoint Multi‑VSL cũ và chỉ hiển thị class ID; chưa phải model common‑20 của nguồn mới.
          </span>
        </div>
      )}
      {localModel.status === "ready" && (
        <div className="ai-banner" role="status">
          <strong>
            {landmarkRuntime === "v3"
              ? "V3 baseline đang làm model demo."
              : landmarkRuntime === "v5"
                ? "V5 bootstrap đang ở chế độ thử nghiệm."
                : "V4.2 thử nghiệm — không dùng cho demo."}
          </strong>
          <span>
            {landmarkRuntime === "v3"
              ? "V3 vẫn là mặc định cho đến khi candidate mới vượt A/B camera độc lập."
              : landmarkRuntime === "v5"
                ? "V3 được khóa làm lõi; ngữ cảnh chỉ hiệu chỉnh 5 từ mục tiêu. Chưa dùng làm demo chính."
                : "Smoke test camera thực tế kém ổn định hơn V3; không dùng kết quả này để train hoặc chỉnh ngưỡng."}
          </span>
          <div className="runtime-switch" role="group" aria-label="Chọn model AI">
            <button
              type="button"
              className={landmarkRuntime === "v3" ? "active" : ""}
              aria-pressed={landmarkRuntime === "v3"}
              disabled={
                capture.status !== "idle" ||
                inference.pendingSequence !== null ||
                automaticPhase === "capturing" ||
                automaticPhase === "postroll"
              }
              onClick={() => selectLandmarkRuntime("v3")}
            >
              V3 demo
            </button>
            <button
              type="button"
              className={landmarkRuntime === "v5" ? "active" : ""}
              aria-pressed={landmarkRuntime === "v5"}
              disabled={
                capture.status !== "idle" ||
                inference.pendingSequence !== null ||
                automaticPhase === "capturing" ||
                automaticPhase === "postroll"
              }
              onClick={() => selectLandmarkRuntime("v5")}
            >
              V5 thử nghiệm
            </button>
            <button
              type="button"
              className={landmarkRuntime === "v4_2" ? "active" : ""}
              aria-pressed={landmarkRuntime === "v4_2"}
              disabled={
                capture.status !== "idle" ||
                inference.pendingSequence !== null ||
                automaticPhase === "capturing" ||
                automaticPhase === "postroll"
              }
              onClick={() => selectLandmarkRuntime("v4_2")}
            >
              V4.2 thử nghiệm
            </button>
          </div>
        </div>
      )}
      {metadataError && (
        <p className="metadata-warning" role="status">
          Chưa đọc được metadata của máy chủ; trạng thái kết nối vẫn được theo dõi bên dưới.
        </p>
      )}
      {localModel.status === "unavailable" && (
        <p className="metadata-warning" role="status">
          AI realtime local chưa tải được ({localModel.error ?? "lỗi không xác định"});
          {config.publicDemo
            ? " hãy tải lại trang hoặc thử trên Chrome/Edge. Bản công khai không có máy chủ dự phòng."
            : " đang dùng model máy chủ dự phòng."}
        </p>
      )}
      {config.publicDemo && (
        <p className="metadata-warning" role="status">
          Bản demo công khai: camera và AI chạy trên thiết bị của bạn; không gửi
          video lên máy chủ. Thu và lưu mẫu AI chỉ có ở bản chạy local.
        </p>
      )}

      <nav className="workflow-bar" aria-label="Chế độ làm việc">
        <div>
          <strong>
            {mode === "recognize" ? "Nhận dạng ký hiệu" : "Thu dữ liệu cải thiện AI"}
          </strong>
          <span>
            {mode === "recognize"
              ? "Thử một ký hiệu và xác nhận kết quả."
              : captureInputMode === "automatic"
                ? "Đếm ngược, quay và tự lưu từng lượt đạt kiểm tra hình tay."
                : "Chỉ lưu vào máy sau khi bạn xác nhận từng mẫu."}
          </span>
        </div>
        <div className="workflow-actions" role="group" aria-label="Chọn chế độ">
          <button
            type="button"
            className={mode === "recognize" ? "active" : ""}
            aria-pressed={mode === "recognize"}
            disabled={capture.status !== "idle" || savingSample}
            onClick={() => switchMode("recognize")}
          >
            Nhận dạng
          </button>
          <button
            type="button"
            className={mode === "collect" ? "active" : ""}
            aria-pressed={mode === "collect"}
            disabled={
              !collectionEnabled ||
              capture.status !== "idle" ||
              automaticPhase === "capturing" ||
              automaticPhase === "postroll" ||
              savingSample
            }
            title={
              collectionEnabled
                ? undefined
                : config.publicDemo
                  ? "Bản công khai không lưu video; hãy dùng bản local để thu dữ liệu"
                  : "Thu dữ liệu chưa được bật ở máy chủ"
            }
            onClick={() => switchMode("collect")}
          >
            Thu dữ liệu AI
          </button>
        </div>
      </nav>

      <main id="workspace" className={`workspace mode-${mode}`}>
        <CameraPanel
          videoRef={videoRef}
          camera={camera}
          connection={
            localModel.status === "ready"
              ? "connected"
              : config.publicDemo && localModel.status === "loading"
                ? "connecting"
                : socket.status
          }
          captureStatus={capture.status}
          canCapture={canCapture}
          purpose={mode}
          captureInputMode={captureInputMode}
          automaticPhase={automaticPhase}
          automaticAvailable={localModel.status === "ready"}
          automaticCollectionPhase={automaticCollection.phase}
          automaticCollectionCountdown={automaticCollection.countdown}
          onCaptureInputModeChange={(nextMode) => {
            if (nextMode === "automatic" && pendingSample) {
              setCollectionNotice(
                "Hãy lưu hoặc bỏ mẫu đang chờ trước khi bắt đầu phiên tự động.",
              );
              return;
            }
            setCaptureInputMode(nextMode);
          }}
          onTrackingFrame={handleTrackingFrame}
          onPointerDown={handlePointerDown}
          onPointerUp={finishPointerCapture}
          onPointerCancel={finishPointerCapture}
        />
        <div className="side-column">
          {mode === "collect" && (
            <CollectionPanel
              labels={collectionLabels}
              selectedLabel={selectedLabel}
              selectedHand={selectedHand}
              selectedDistance={selectedDistance}
              selectedLighting={selectedLighting}
              selectedNegativeAction={selectedNegativeAction}
              counts={collectionCounts}
              targetCounts={selectedCollectionTargets}
              pending={pendingSample}
              prediction={inference.prediction}
              saving={savingSample}
              notice={collectionNotice}
              controlsLocked={automaticCollectionEnabled}
              automaticActive={automaticCollectionEnabled}
              onLabelChange={setSelectedLabel}
              onHandChange={setSelectedHand}
              onDistanceChange={setSelectedDistance}
              onLightingChange={setSelectedLighting}
              onNegativeActionChange={setSelectedNegativeAction}
              onSave={() => void saveCollectionSample()}
              onDiscard={() => {
                setPendingSample(null);
                setCollectionNotice("Đã bỏ mẫu; không có tệp nào được lưu.");
              }}
            />
          )}
          <ResultPanel
            phase={visiblePhase}
            prediction={inference.prediction}
            guidance={
              config.publicDemo && localModel.status === "loading"
                ? "Đang tải AI trên thiết bị của bạn…"
                : inference.guidance
            }
            onAdd={addPrediction}
            canUseLabels={labelsVerified}
            eyebrow={mode === "collect" ? "Bước 3" : "Bước 2"}
            collectionReview={mode === "collect"}
            automaticCapture={
              mode === "recognize" && captureInputMode === "automatic"
            }
          />
          {mode === "recognize" && (
            <TranscriptPanel
              words={transcript.words}
              notice={notice}
              onUndo={() => {
                dispatchTranscript({ type: "undo" });
                setNotice("Đã hoàn tác từ cuối.");
              }}
              onClear={() => {
                dispatchTranscript({ type: "clear" });
                setNotice("Đã xóa toàn bộ câu.");
              }}
              onCopy={() => void copyTranscript()}
            />
          )}
        </div>
      </main>

      <footer>
        <span>VSign MVP · Dữ liệu camera không được lưu mặc định</span>
        <span>
          Nguồn video ký hiệu: <a href="https://huggingface.co/datasets/star092304/ViSignLanguage-Video" target="_blank" rel="noopener noreferrer">ViSignLanguage-Video</a> · CC BY 4.0
        </span>
        <span>
          Protocol {metadata?.protocol_version ?? "1.0"} · {localModel.status === "ready"
            ? localModel.modelVersion
            : metadata?.model_version ?? "đang đọc metadata"}
        </span>
      </footer>
    </div>
  );
}
