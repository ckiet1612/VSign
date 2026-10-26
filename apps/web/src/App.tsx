import {
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useLayoutEffect,
  useReducer,
  useRef,
  useState,
} from "react";
import { Database, FlaskConical, PanelLeft, RefreshCw, Robot, Wrench } from "./icons";
import type { WorkspaceClientEventRequest } from "@workspace-contracts";
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
import { AppSidebar } from "./components/AppSidebar";
import { SidebarResizer } from "./components/SidebarResizer";
import { SignWordmark } from "./components/SignWordmark";
import { LoginGate } from "./components/LoginGate";
import { BackendLocationBadge } from "./components/BackendLocationBadge";
import type { HandTrackingFrame } from "./components/HandTrackingOverlay";
import { BodyBoxTracker } from "./lib/bodyFraming";
import {
  CollectionPanel,
  CollectionWordPicker,
  type PendingCollectionSample,
} from "./components/CollectionPanel";
import { ResultPanel } from "./components/ResultPanel";
import { ServerModelSelector } from "./components/ServerModelSelector";
import { TranscriptPanel } from "./components/TranscriptPanel";
import { WorkspaceReports } from "./components/WorkspaceReports";
import { StaffReplyPanel } from "./components/StaffReplyPanel";
import { REPLY_MAX } from "../../../contracts/v1/display";
import { useUsageTracker } from "./hooks/useUsageTracker";
import type { UsageEvent } from "./lib/usageTracker";
import { WorkspacePage } from "./components/WorkspacePage";
import { WorkspaceActivity } from "./components/WorkspaceActivity";
import { WorkspaceModels } from "./components/WorkspaceModels";
import { WorkspaceEvaluations } from "./components/WorkspaceEvaluations";
import { WorkspaceIntegrations } from "./components/WorkspaceIntegrations";
import { WorkspaceTeam } from "./components/WorkspaceTeam";
import { WorkspaceSettings } from "./components/WorkspaceSettings";
import { useWorkspaceSessionDefaults } from "./hooks/useWorkspaceSessionDefaults";
import { WorkspaceData, type DataTab } from "./components/WorkspaceData";
import { useUrlTab } from "./hooks/useUrlTab";
import { useWorkspaceData } from "./hooks/useWorkspaceData";
import { WorkspaceTopbar } from "./components/WorkspaceTopbar";
import { config } from "./config";
import { useCamera } from "./hooks/useCamera";
import { useCounterDisplay } from "./hooks/useCounterDisplay";
import { CounterDisplayControl } from "./components/CounterDisplayControl";
import { useAutomaticSignCapture } from "./hooks/useAutomaticSignCapture";
import { useAutomaticInferenceQueue } from "./hooks/useAutomaticInferenceQueue";
import { useAutomaticSentence } from "./hooks/useAutomaticSentence";
import { useAutomaticCollectionCycle } from "./hooks/useAutomaticCollectionCycle";
import { useInferenceSocket, type ConnectionStatus } from "./hooks/useInferenceSocket";
import { useInferenceEndpoint } from "./hooks/useInferenceEndpoint";
import { useServerModel } from "./hooks/useServerModel";
import { useLandmarkInference } from "./hooks/useLandmarkInference";
import { useSignCapture } from "./hooks/useSignCapture";
import { useSidebarLayout } from "./hooks/useSidebarLayout";
import { useWorkspaceNavigation } from "./hooks/useWorkspaceNavigation";
import { useWorkspacePlatform } from "./hooks/useWorkspacePlatform";
import { useRuntimeStatus } from "./hooks/useRuntimeStatus";
import { useActivityRecorder } from "./hooks/useActivityRecorder";
import { copyText } from "./lib/copy";
import { shouldStartSpaceCapture } from "./lib/keyboard";
import { chooseCapturePipeline, chooseInferenceRoute } from "./lib/inferenceRoute";
import { composeSentence } from "./lib/sentenceComposer";
import type { SentenceCapture } from "./lib/automaticSentence";
import type { AutomaticCaptureTiming, AutomaticInferenceJob } from "./lib/automaticInferenceQueue";
import {
  AutoTranscriptInsertion,
  type AutoTranscriptCapture,
  type WordInsertionMode,
} from "./lib/autoTranscriptInsertion";
import {
  DEFAULT_LANDMARK_RUNTIME,
  IDLE_LABEL,
  type LandmarkRuntime,
} from "./lib/landmarkInference";
import { combineV5LandmarkSequence } from "./lib/landmarkFeaturesV5";
import { hasBaselineHandLandmarks } from "./lib/landmarkFeaturesV3";
import { REFERENCE_SIGNS } from "./referenceSigns";
import {
  inferenceReducer,
  initialInferenceState,
} from "./state/inferenceMachine";
import {
  initialTranscriptState,
  transcriptReducer,
  type TranscriptAction,
} from "./state/transcript";
import type { WorkspaceView } from "./lib/workspaceNavigation";
import { workspaceBasePath } from "./lib/appRoutes";
import { DashboardPageSkeleton } from "./components/SystemDashboardSkeleton";

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
  confidence: 0.40,
  margin: 0,
} as const;

const DATA_TABS: readonly DataTab[] = ["collect", "sessions", "datasets", "labels"];
const PERSONAL_COLLECTION_BATCH = "personal-100";
const PERSONAL_COLLECTION_TARGET = 100;

type WorkspacePlatform = ReturnType<typeof useWorkspacePlatform>;
// One shared request: App starts it as soon as it knows the user is a system admin (in parallel with the shell),
// so the overview usually renders without ever showing its Suspense fallback.
let systemDashboardChunk: Promise<typeof import("./components/SystemDashboard")> | null = null;
const loadSystemDashboard = () => systemDashboardChunk ??= import("./components/SystemDashboard");
const SystemDashboard = lazy(() => loadSystemDashboard().then(module => ({ default: module.SystemDashboard })));

export default function App() {
  const platform = useWorkspacePlatform(config.platformHttpUrl, !config.publicDemo);

  useLayoutEffect(() => {
    if (platform.loading) return;
    const ready = !platform.error && (!platform.authRequired || !!platform.user);
    try {
      if (ready) sessionStorage.setItem("vsign.workspace-boot", "ready");
      else sessionStorage.removeItem("vsign.workspace-boot");
    } catch { /* The shell hint is optional. */ }
    if (!ready) document.documentElement.removeAttribute("data-workspace-boot");
  }, [platform.loading, platform.error, platform.authRequired, platform.user]);

  if (platform.loading && !config.publicDemo) {
    return <main className="platform-loading" aria-label="Đang tải workspace">
      {document.documentElement.hasAttribute("data-workspace-boot") && <div className="boot-frame" aria-hidden="true" />}
      <span aria-hidden="true" />
    </main>;
  }
  if (platform.error) {
    return <main className="platform-failure"><p role="alert">{platform.error}</p><button type="button" onClick={() => void platform.reload()}>Thử lại</button></main>;
  }
  if (platform.user?.role === "system_admin") void loadSystemDashboard();
  if (platform.authRequired && !platform.user) {
    return (
      <>
        <LoginGate
          workspaceName="VSign"
          busy={platform.submitting}
          onLogin={platform.login}
        />
        <BackendLocationBadge location={null} floating requiresLogin />
      </>
    );
  }
  return <WorkspaceApp platform={platform} />;
}

function WorkspaceApp({ platform }: { platform: WorkspacePlatform }) {
  const serverModel = useServerModel(config.serverModels);
  const workspaceToolsRef = useRef<HTMLDetailsElement>(null);
  const { view: workspaceView, navigate: navigateWorkspaceView } = useWorkspaceNavigation(platform.user?.role === "system_admin" ? "overview" : "recognize");
  const sidebar = useSidebarLayout();
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  // A new view starts at the top; otherwise it opens mid-page and jumps when its data changes the page height.
  useLayoutEffect(() => {
    const panel = panelRef.current;
    if (panel && panel.scrollTop > 0) panel.scrollTop = 0;
  }, [workspaceView]);
  const shellRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!mobileSidebarOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMobileSidebarOpen(false);
    };
    document.body.classList.add("mobile-sidebar-lock");
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.classList.remove("mobile-sidebar-lock");
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [mobileSidebarOpen]);

  useEffect(() => {
    if (!serverModel.error) return;
    const tools = workspaceToolsRef.current;
    if (!tools) return;
    const restoreFocus = tools.contains(document.activeElement);
    tools.open = false;
    if (restoreFocus) tools.querySelector("summary")?.focus();
  }, [serverModel.error]);

  const inferenceHttpUrl = serverModel.active.httpUrl;
  const runtime = useRuntimeStatus(inferenceHttpUrl, !config.publicDemo && (workspaceView === "overview" || workspaceView === "monitoring" || workspaceView === "models"));
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
  const transcriptRef = useRef(transcript);
  transcriptRef.current = transcript;
  const [wordInsertionMode, setWordInsertionMode] = useState<WordInsertionMode>("manual");
  const autoTranscriptRef = useRef(new AutoTranscriptInsertion());
  const manualTranscriptCaptureRef = useRef<AutoTranscriptCapture | null>(null);
  const automaticTranscriptCaptureRef = useRef<AutoTranscriptCapture | null>(null);
  const transcriptContextRef = useRef({
    contextKey: "", eligible: false, labels: [] as string[], modelVersion: "",
  });
  const [automaticAddedSequence, setAutomaticAddedSequence] = useState<number | null>(null);
  const [notice, setNotice] = useState("");
  // The staff member's latest answer to the customer (F05); shown on the counter screen, or here without one.
  const [staffReply, setStaffReply] = useState("");
  // Usage report (F08): set once the tracker exists below; earlier callbacks reach it through this ref.
  const usageRef = useRef<{ note: (event: UsageEvent) => void; end: () => void }>({ note: () => undefined, end: () => undefined });
  const customerActionRef = useRef<(action: "undo_word") => void>(() => undefined);
  const [composedSentence, setComposedSentence] = useState("");
  const [composedWarning, setComposedWarning] = useState("");
  const [composingSentence, setComposingSentence] = useState(false);
  const composeRevisionRef = useRef(0);
  const sentenceEventsRef = useRef<Pick<ReturnType<typeof useAutomaticSentence>, "activity" | "finish" | "accept" | "skip" | "missing" | "cancelPending">>({
    activity: () => null, finish: () => undefined, accept: () => undefined, skip: () => undefined,
    missing: () => undefined, cancelPending: () => undefined,
  });
  const sentenceSequencesRef = useRef(new Map<number, { capture: SentenceCapture; at: number }>());
  const sentenceCaptureRef = useRef<{ capture: SentenceCapture; at: number } | null>(null);
  const [metadata, setMetadata] = useState<InferenceMetadata | null>(null);
  const [metadataError, setMetadataError] = useState(false);
  // Until the first connection attempt resolves, "disconnected" is only the initial state, not a lost connection.
  const [connectionSettled, setConnectionSettled] = useState(false);
  const [mode, setMode] = useState<AppMode>(workspaceView === "data" && platform.available ? "collect" : "recognize");
  const recognizingRef = useRef(mode === "recognize");
  recognizingRef.current = mode === "recognize";
  const managedData = platform.available && platform.context !== null && !config.publicDemo;
  const [dataTab, setDataTab] = useUrlTab(DATA_TABS, "collect", workspaceView === "data");
  const [datasetId, setDatasetId] = useState("");
  const data = useWorkspaceData({ platformUrl: config.platformHttpUrl,
    workspaceId: platform.context?.workspace_id ?? "local", user: platform.user, enabled: managedData });
  const mutateData = data.mutate, refreshData = data.refresh, holdDataReads = data.holdReads;
  const selectedDataset = data.snapshot?.datasets.find(row => row.id === datasetId);
  const selectedDatasetLabels = data.snapshot?.labels.find(row => row.id === selectedDataset?.label_version_id);
  const collectionTarget = managedData ? selectedDataset?.quota_per_label ?? 100 : PERSONAL_COLLECTION_TARGET;
  const remoteSessionRef = useRef<{ id: string; datasetId: string; context: object | null } | null>(null);
  const pendingRemoteSessionRef = useRef<typeof remoteSessionRef.current>(null);
  const remoteStateRef = useRef<"idle" | "running" | "paused">("idle");
  const remoteQueueRef = useRef<Promise<void>>(Promise.resolve());
  const deferredSessionStateRef = useRef<{ next: "idle" | "running" | "paused"; reason: WorkspaceClientEventRequest["reason"] } | null>(null);
  const [captureInputMode, setCaptureInputMode] =
    useState<CaptureInputMode>(workspaceView === "data" && managedData ? "automatic" : "manual");
  const recognizeCaptureModeRef = useRef<CaptureInputMode>("manual");
  const modeRef = useRef(mode);
  modeRef.current = mode;
  const captureInputModeRef = useRef(captureInputMode);
  captureInputModeRef.current = captureInputMode;
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
  const [collectionProgressReady, setCollectionProgressReady] = useState(false);
  const [collectionSession, setCollectionSession] = useState<"idle" | "running" | "paused">("idle");
  const collectionSessionRef = useRef(collectionSession);
  collectionSessionRef.current = collectionSession;
  useEffect(() => {
    if (managedData && workspaceView === "data" && collectionSessionRef.current === "idle") {
      if (modeRef.current === "recognize") recognizeCaptureModeRef.current = captureInputModeRef.current;
      setMode("collect"); setCaptureInputMode("automatic");
    }
  }, [managedData, workspaceView]);
  const activityRecorder = useActivityRecorder(config.platformHttpUrl,
    platform.user ? `${platform.context?.workspace_id ?? "local"}:${platform.user.id}:${platform.user.role}` : null);
  const collectionContext = activityRecorder.context;
  const collectionContextRef = useRef(collectionContext);
  collectionContextRef.current = collectionContext;
  const [collectionConsent, setCollectionConsent] = useState<{ context: object; datasetId: string; revision: number; accepted: boolean } | null>(null);
  const consentRevision = data.snapshot?.collection_policy?.revision ?? 0;
  const explicitCollectionConsent = collectionConsent?.context === collectionContext && collectionConsent?.datasetId === datasetId &&
    collectionConsent?.revision === consentRevision && collectionConsent.accepted;
  const collectionPolicyReady = !data.snapshot?.collection_policy?.require_consent || !!explicitCollectionConsent;
  const previousCollectionContext = useRef(collectionContext);
  const [collectionSummaryRevision, refreshCollectionSummary] = useState(0);
  const recordActivity = activityRecorder.record;
  const auditCollectionRef = useRef<null | { id: string; modelVersion: string; savedSamples: Set<string>;
    record: typeof recordActivity }>(null);
  const changeCollectionSession = useCallback((next: "idle" | "running" | "paused",
    reason: WorkspaceClientEventRequest["reason"] = "manual") => {
    if (managedData) {
      if (next === 'running' && !collectionPolicyReady) {
        setCollectionNotice('Cần đồng ý lưu mẫu trước khi bắt đầu phiên thu.'); return;
      }
      remoteStateRef.current = next;
      if (next !== "running") { collectionSessionRef.current = next; setCollectionSession(next); }
      if (savingSampleRef.current) { deferredSessionStateRef.current = { next, reason }; return; }
      const context = collectionContextRef.current;
      remoteQueueRef.current = remoteQueueRef.current.then(async () => {
        if (collectionContextRef.current !== context) return;
        let session = remoteSessionRef.current;
        const starting = !session && next === "running";
        if (starting) {
          if (!datasetId || selectedDataset?.status !== "draft") return;
          session = { id: createSessionId(), datasetId, context };
          remoteSessionRef.current = session;
        }
        if (!session || session.context !== context) return;
        const snapshot = await mutateData(starting ? "/sessions" : `/sessions/${session.id}/state`, starting
          ? { request_id: session.id, dataset_version_id: session.datasetId, ...(explicitCollectionConsent ? { consent: true } : {}) }
          : { state: next === "idle" ? reason === "completed" ? "completed" : "stopped" : next });
        if (!snapshot || collectionContextRef.current !== context) return;
        const row = snapshot.sessions.find(row => row.id === session!.id);
        if (!row) return;
        if (next === "idle") remoteSessionRef.current = null;
        if (remoteStateRef.current === next) {
          collectionSessionRef.current = next; setCollectionSession(next);
        }
      }).catch(() => { setCollectionNotice("Chưa xác nhận được trạng thái phiên thu. Hãy làm mới dữ liệu."); });
      return;
    }
    const previous = collectionSessionRef.current;
    if (previous === next) return;
    if (previous === "idle" && next === "running") {
      auditCollectionRef.current = { id: createSessionId(), modelVersion: metadata?.model_version ?? "unknown",
        savedSamples: new Set(), record: recordActivity };
    }
    const session = auditCollectionRef.current;
    if (session) session.record({ event_id: createSessionId(),
      event_type: next === "running" ? previous === "paused" ? "collection.resumed" : "collection.started"
        : next === "paused" ? "collection.paused" : reason === "completed" ? "collection.completed" : "collection.stopped",
      resource_id: session.id, capture_session_id: sessionIdRef.current, model_version: session.modelVersion,
      saved_samples: session.savedSamples.size, reason });
    collectionSessionRef.current = next;
    setCollectionSession(next);
  }, [metadata?.model_version, recordActivity, managedData, mutateData, datasetId, selectedDataset?.status, collectionPolicyReady, explicitCollectionConsent]);
  const savingSampleRef = useRef(false);
  const [savingSample, setSavingSample] = useState(false);
  const selectedCollectionCounts = collectionCounts[selectedLabel] ?? { right: 0, left: 0 };
  const selectedCollectionCount = selectedCollectionCounts.right + selectedCollectionCounts.left;
  const [landmarkRuntime, setLandmarkRuntime] =
    useState<LandmarkRuntime>(DEFAULT_LANDMARK_RUNTIME);
  const automaticPredictionRef = useRef<(prediction: PredictionMessage) => boolean>(() => false);
  const manualRequestRef = useRef<{
    sequence: number;
    route: "server" | "local";
    contextKey: string;
  } | null>(null);
  const [manualBusy, setManualBusy] = useState(false);
  const [automaticCaptureNotice, setAutomaticCaptureNotice] = useState("");

  const invalidateManualComposition = useCallback(() => {
    composeRevisionRef.current += 1;
    setComposingSentence(false);
    setComposedSentence("");
    setComposedWarning("");
  }, []);

  const applyTranscriptAction = useCallback((action: TranscriptAction) => {
    const previous = transcriptRef.current;
    const next = transcriptReducer(previous, action);
    transcriptRef.current = next;
    dispatchTranscript(action);
    return next !== previous;
  }, []);

  const appendWord = useCallback((label: string, automatic: boolean, at = Date.now()) => {
    if (!applyTranscriptAction({ type: "add", label, at })) {
      if (!automatic) {
        setNotice("Từ giống nhau vừa được thêm. Hãy chờ một giây trước khi thêm lại.");
      }
      return false;
    }
    invalidateManualComposition();
    if (recognizingRef.current) usageRef.current.note({ type: "word", label });
    setNotice(automatic ? `Đã tự thêm “${label}” vào câu.` : `Đã thêm “${label}” vào câu.`);
    return true;
  }, [applyTranscriptAction, invalidateManualComposition]);

  const acceptPrediction = useCallback((prediction: PredictionMessage) => {
    dispatchInference({ type: "prediction_received", prediction });
    if (recognizingRef.current && prediction.status === "uncertain") usageRef.current.note({ type: "uncertain" });
    else if (recognizingRef.current && prediction.status === "error") usageRef.current.note({ type: "failed" });
    const context = transcriptContextRef.current;
    const label = autoTranscriptRef.current.consume(
      prediction, context.contextKey, context.eligible &&
        prediction.model_version === context.modelVersion &&
        prediction.label !== null && prediction.label !== IDLE_LABEL &&
        context.labels.includes(prediction.label),
    );
    const sentenceCapture = sentenceSequencesRef.current.get(prediction.sequence);
    sentenceSequencesRef.current.delete(prediction.sequence);
    // Debounce actual signing, not consecutive replies released from a slow FIFO.
    if (label && appendWord(label, true, sentenceCapture?.at)) {
      if (sentenceCapture) sentenceEventsRef.current.accept(sentenceCapture.capture, transcriptRef.current.words);
      setAutomaticAddedSequence(prediction.sequence);
    } else if (sentenceCapture) {
      // An unrecognized sign is dropped silently; a warning here only clutters the draft.
      sentenceEventsRef.current.skip(sentenceCapture.capture);
    }
  }, [appendWord]);

  const handlePrediction = useCallback((prediction: PredictionMessage) => {
    if (automaticPredictionRef.current(prediction)) return;
    const request = manualRequestRef.current;
    if (request?.sequence !== prediction.sequence) return;
    manualRequestRef.current = null;
    setManualBusy(false);
    if (request.contextKey !== transcriptContextRef.current.contextKey) {
      autoTranscriptRef.current.discard(prediction.sequence);
      return;
    }
    acceptPrediction(prediction);
  }, [acceptPrediction]);
  // Recognition prefers the Modal GPU runtime and falls back to the Mac; metadata, login and
  // sentence composition always stay on the Mac.
  const endpointBusyRef = useRef<() => boolean>(() => false);
  const [inferenceSocketStatus, setInferenceSocketStatus] = useState<ConnectionStatus>("connecting");
  const inferenceEndpoint = useInferenceEndpoint({
    gpu: config.gpuRuntime,
    macWsUrl: config.publicDemo ? null : serverModel.active.wsUrl,
    platformUrl: config.platformHttpUrl,
    macMetadata: metadata,
    enabled: !config.publicDemo && serverModel.active.id === "current" && !serverModel.switching,
    socketStatus: inferenceSocketStatus,
    isBusy: () => endpointBusyRef.current(),
  });
  const noteRecognitionActivity = inferenceEndpoint.noteActivity;
  const socket = useInferenceSocket(
    inferenceEndpoint.wsUrl,
    handlePrediction,
    serverModel.active.id,
  );
  useEffect(() => { setInferenceSocketStatus(socket.status); }, [socket.status]);
  const localModel = useLandmarkInference(landmarkRuntime);
  const inferenceRoute = chooseInferenceRoute({
    publicDemo: config.publicDemo,
    serverConnected: socket.status === "connected",
    localReady: localModel.status === "ready" && serverModel.active.id === "current",
  });
  const backendLocation = inferenceRoute === "local" ? "browser"
    : socket.status === "connected" && socket.activeUrl
      ? config.gpuRuntime && socket.activeUrl.split("?")[0] === config.gpuRuntime.wsUrl.split("?")[0]
        ? "modal" : "mac"
      : null;
  const capturePipeline = chooseCapturePipeline({
    purpose: mode,
    inferenceRoute,
  });
  // While the server connection is pending, the guide already shows the server's fixed square, so it does not
  // start as the wide local-model frame and jump to the square once the socket opens.
  const guideFraming = !config.publicDemo && (inferenceRoute === "unavailable" || !connectionSettled)
    ? "fixed" : capturePipeline.framing;
  // The server model decides whether RGB clips are trimmed and cropped around the signer.
  const bodyFraming = inferenceRoute === "server" && metadata?.input_framing === "trim-bodycrop-v1";
  const predictLandmarks = localModel.predict;
  // A counter display swaps the camera source for the customer laptop's camera; everything downstream is unchanged.
  const counterDisplay = useCounterDisplay({
    platformUrl: config.platformHttpUrl,
    enabled: !config.publicDemo && platform.available && platform.user !== null &&
      platform.capabilities?.recognize !== false && workspaceView === "recognize" && mode === "recognize",
    storageKey: platform.user ? `vsign.counterDisplay:${platform.context?.workspace_id ?? "local"}:${platform.user.id}` : null,
    onCustomerAction: action => customerActionRef.current(action),
  });
  const usage = useUsageTracker({
    platformUrl: config.platformHttpUrl,
    enabled: !config.publicDemo && platform.available && platform.user !== null && platform.capabilities?.recognize !== false,
    channel: counterDisplay.connected ? "counter" : "same_screen",
    displayId: counterDisplay.connected ? counterDisplay.selectedId : null,
  });
  usageRef.current = usage;
  const camera = useCamera(videoRef, counterDisplay.remoteStream);
  const captureModeTouched = useRef(false);
  useWorkspaceSessionDefaults({ platformUrl: config.platformHttpUrl, workspaceId: platform.context?.workspace_id ?? 'local',
    identity: platform.user ? `${platform.user.id}:${platform.user.role}` : null,
    enabled: platform.available && !config.publicDemo, blocked: camera.status !== 'off' || mode !== 'recognize' || captureModeTouched.current,
    onApply: setCaptureInputMode });
  const recognitionModelVersion = inferenceRoute === "local" ? localModel.modelVersion : metadata?.model_version ?? "";
  const recognitionContextKey = `${mode}:${captureInputMode}:${camera.status}:${inferenceRoute}:${landmarkRuntime}:${serverModel.active.id}:${recognitionModelVersion}`;
  // Turning the camera on for recognition is the cue to wake the GPU runtime.
  useEffect(() => {
    if (camera.status === "ready" && mode === "recognize") noteRecognitionActivity();
  }, [camera.status, mode, noteRecognitionActivity]);
  const recognitionContextRef = useRef(recognitionContextKey);
  const previousRecognitionContextRef = useRef(recognitionContextKey);
  recognitionContextRef.current = recognitionContextKey;
  const mockMode =
    !config.publicDemo &&
    inferenceRoute !== "local" &&
    (metadata?.mock ?? true);
  // Until the first metadata read settles the backend is unknown, not mock: warning then would flash on every reload.
  const showMockBanner = mockMode && (metadata !== null || metadataError);
  const labelsVerified =
    inferenceRoute === "local"
      ? localModel.status === "ready"
      : metadata?.candidate_labels_unverified === false;
  const transcriptLabels = inferenceRoute === "local" ? localModel.labels : metadata?.labels ?? [];
  const transcriptModelVersion = inferenceRoute === "local" ? localModel.modelVersion : metadata?.model_version ?? "";
  const autoTranscriptAvailable = mode === "recognize" && camera.status === "ready" &&
    inferenceRoute !== "unavailable" && labelsVerified && !mockMode &&
    (transcriptLabels?.length ?? 0) > 0 && Boolean(transcriptModelVersion);
  transcriptContextRef.current = {
    contextKey: recognitionContextKey, eligible: autoTranscriptAvailable,
    labels: transcriptLabels ?? [], modelVersion: transcriptModelVersion,
  };
  // Read when frames are sent, not captured: the FIFO only sends after the previous
  // reply, so the sentence already holds the word recognized just before.
  const sentenceContextWords = useCallback(() => {
    const labels = transcriptContextRef.current.labels;
    return transcriptRef.current.words.filter((word) => labels.includes(word)).slice(-8);
  }, []);
  useEffect(() => {
    const gate = autoTranscriptRef.current;
    return () => gate.invalidate();
  }, []);
  useEffect(() => {
    if (previousRecognitionContextRef.current === recognitionContextKey) return;
    previousRecognitionContextRef.current = recognitionContextKey;
    autoTranscriptRef.current.invalidate();
    sentenceSequencesRef.current.clear();
    sentenceCaptureRef.current = null;
    invalidateManualComposition();
    setAutomaticAddedSequence(null);
    if (
      inference.pendingSequence !== null ||
      inference.prediction !== null ||
      inference.phase === "capturing"
    ) {
      dispatchInference({
        type: "capture_cancelled",
        message: "Đã hủy lượt nhận dạng vì camera, chế độ hoặc kết nối đã thay đổi.",
      });
    }
  }, [
    inference.pendingSequence, inference.phase,
    inference.prediction, recognitionContextKey, invalidateManualComposition,
  ]);
  const automaticEnabled = mode === "recognize" &&
    !serverModel.switching &&
    captureInputMode === "automatic" && camera.status === "ready" &&
    inferenceRoute !== "unavailable";
  const sendAutomaticJob = useCallback((job: AutomaticInferenceJob) => {
    if (job.route === "server") {
      if (job.rgbFrames?.length !== 16) {
        throw new Error("Ảnh ký hiệu chưa đủ 16 frame. Hãy thử lại.");
      }
      noteRecognitionActivity();
      socket.sendFrames({
        type: "frames", session_id: sessionIdRef.current,
        sequence: job.sequence, captured_at: job.capturedAt, frames: job.rgbFrames,
        context_words: sentenceContextWords(),
      });
      return;
    }
    return predictLandmarks(
      framesForRuntime(landmarkRuntime, job.landmarkFrames, job.baselineLandmarkFrames),
      job.sequence, AUTOMATIC_PREDICTION_THRESHOLDS,
    );
  }, [landmarkRuntime, noteRecognitionActivity, predictLandmarks, sentenceContextWords, socket]);
  const automaticQueue = useAutomaticInferenceQueue({
    enabled: automaticEnabled,
    contextKey: recognitionContextKey,
    serverConnected: socket.status === "connected",
    blocked: manualBusy,
    send: sendAutomaticJob,
    onStarted: (sequence) => dispatchInference({ type: "request_started", sequence }),
    onPrediction: acceptPrediction,
    onError: (message) => {
      sentenceEventsRef.current.cancelPending("Có đoạn chưa được xử lý · cần kiểm tra");
      sentenceSequencesRef.current.clear();
      sentenceCaptureRef.current = null;
      autoTranscriptRef.current.invalidate();
      setAutomaticCaptureNotice(`${message} Các lượt chờ đã được hủy; hãy ký lại.`);
      dispatchInference({ type: "failed", message });
    },
  });
  automaticPredictionRef.current = automaticQueue.receive;
  // Only a sign awaiting its prediction pins the runtime; capture itself does not use the socket.
  endpointBusyRef.current = () => manualRequestRef.current !== null || automaticQueue.isPending();
  const enqueueAutomaticJob = automaticQueue.enqueue;
  const confirmAutomaticJob = automaticQueue.confirm;
  const retractAutomaticJob = automaticQueue.retract;
  // Provisional segment id → request sequence, while its result waits for confirmation.
  const provisionalSequencesRef = useRef(new Map<number, number>());
  const handleAutomaticProvisional = useCallback(
    (id: number, landmarkFrames: number[][], baselineLandmarkFrames: number[][],
      rgbFrames: string[], timing: AutomaticCaptureTiming) => {
      if (inferenceRoute !== "server") return;
      const sequence = sequenceRef.current;
      if (enqueueAutomaticJob({
        sequence, route: "server", capturedAt: Date.now(), landmarkFrames, baselineLandmarkFrames,
        rgbFrames, timing, provisional: true,
      })) {
        sequenceRef.current += 1;
        provisionalSequencesRef.current.set(id, sequence);
      }
    },
    [enqueueAutomaticJob, inferenceRoute],
  );
  const handleAutomaticProvisionalCancel = useCallback((id: number) => {
    const sequence = provisionalSequencesRef.current.get(id);
    provisionalSequencesRef.current.delete(id);
    if (sequence !== undefined) retractAutomaticJob(sequence);
  }, [retractAutomaticJob]);
  const handleAutomaticSequence = useCallback(
    (
      landmarkFrames: number[][],
      baselineLandmarkFrames: number[][],
      rgbFrames?: string[],
      timing: AutomaticCaptureTiming = { captureMs: 0, encodeMs: 0 },
      confirmedProvisional?: number,
    ) => {
      const provisionalSequence = confirmedProvisional === undefined
        ? undefined : provisionalSequencesRef.current.get(confirmedProvisional);
      if (confirmedProvisional !== undefined) provisionalSequencesRef.current.delete(confirmedProvisional);
      const sequence = provisionalSequence ?? sequenceRef.current++;
      autoTranscriptRef.current.register(sequence, automaticTranscriptCaptureRef.current);
      const sentenceCapture = sentenceCaptureRef.current;
      sentenceCaptureRef.current = null;
      if (sentenceCapture) {
        sentenceEventsRef.current.finish(sentenceCapture.capture, performance.now() - timing.encodeMs);
        sentenceSequencesRef.current.set(sequence, sentenceCapture);
      }
      // Its result may already be back; confirming releases it after the bookkeeping above.
      if (provisionalSequence !== undefined && confirmAutomaticJob(provisionalSequence)) return;
      if (!enqueueAutomaticJob({
        sequence, route: inferenceRoute === "server" ? "server" : "local",
        capturedAt: Date.now(), landmarkFrames, baselineLandmarkFrames, rgbFrames, timing,
      })) {
        autoTranscriptRef.current.discard(sequence);
        sentenceSequencesRef.current.delete(sequence);
        if (sentenceCapture) sentenceEventsRef.current.missing("Có đoạn bị bỏ do hàng đợi đầy · cần kiểm tra", sentenceCapture.capture);
        setAutomaticCaptureNotice("Hàng đợi đầy; lượt vừa thu chưa được nhận. Hãy chờ và ký lại.");
      }
    },
    [confirmAutomaticJob, enqueueAutomaticJob, inferenceRoute],
  );
  const automaticCapture = useAutomaticSignCapture({
    enabled: automaticEnabled,
    paused: automaticQueue.full,
    videoRef,
    captureVideoFrames: inferenceRoute === "server",
    bodyFraming,
    captureContextKey: recognitionContextKey,
    onSequence: handleAutomaticSequence,
    onProvisional: handleAutomaticProvisional,
    onProvisionalCancel: handleAutomaticProvisionalCancel,
    onCaptureStart: () => {
      const capture = sentenceEventsRef.current.activity();
      sentenceCaptureRef.current = capture ? { capture, at: Date.now() } : null;
      invalidateManualComposition();
      const context = transcriptContextRef.current;
      automaticTranscriptCaptureRef.current = autoTranscriptRef.current.beginCapture(
        context.contextKey, context.eligible,
      );
      setAutomaticCaptureNotice("");
      dispatchInference({ type: "capture_started" });
    },
    onCaptureCancel: () => {
      if (sentenceCaptureRef.current) sentenceEventsRef.current.missing("Có đoạn ký bị gián đoạn · cần kiểm tra", sentenceCaptureRef.current.capture);
      sentenceCaptureRef.current = null;
      if (!automaticQueue.busy && !manualBusy) dispatchInference({
        type: "capture_cancelled", message: "Đã dừng lượt ký hiệu tự động.",
      });
    },
    onError: (message) => {
      if (sentenceCaptureRef.current) sentenceEventsRef.current.missing("Có đoạn không thu được · cần kiểm tra", sentenceCaptureRef.current.capture);
      sentenceCaptureRef.current = null;
      setAutomaticCaptureNotice(message);
      if (!automaticQueue.busy && !manualBusy) dispatchInference({ type: "failed", message });
    },
  });
  const automaticPhase = automaticCapture.phase;
  // Hands-free capture composes sentences on its own, whether words are added automatically or confirmed by staff.
  const automaticSentenceEnabled = automaticEnabled && autoTranscriptAvailable &&
    !config.publicDemo && metadata !== null;
  const automaticSentence = useAutomaticSentence({
    enabled: automaticSentenceEnabled,
    // Camera and connection state stay out: a brief reconnect to the same model keeps the sentence being signed.
    contextKey: `${mode}:${captureInputMode}:${landmarkRuntime}:${serverModel.active.id}:${transcriptModelVersion}`,
    words: transcript.words,
    blocked: () => {
      const frame = trackingFrameRef.current;
      const age = frame ? performance.now() - frame.updatedAt : Infinity;
      return document.visibilityState === "hidden" || age < 0 || age > 500 ||
        automaticCapture.isBusy() || automaticQueue.isPending() || manualBusy;
    },
    compose: (words, signal) => composeSentence(inferenceHttpUrl, words, fetch, signal),
  });
  sentenceEventsRef.current = automaticSentence;
  const flagSentenceMissing = automaticSentence.missing;
  useEffect(() => {
    if (automaticSentenceEnabled && automaticQueue.full) {
      flagSentenceMissing("Hàng đợi đầy · có thể thiếu đoạn ký");
    }
  }, [automaticSentenceEnabled, automaticQueue.full, flagSentenceMissing]);
  useEffect(() => { setAutomaticCaptureNotice(""); }, [recognitionContextKey]);
  useEffect(() => {
    if (socket.status !== "connected" && manualRequestRef.current?.route === "server") {
      autoTranscriptRef.current.discard(manualRequestRef.current.sequence);
      manualRequestRef.current = null;
      setManualBusy(false);
    }
  }, [socket.status]);
  const ingestAutomaticFrame = automaticCapture.ingest;
  const bodyBoxTrackerRef = useRef(new BodyBoxTracker());
  const handleTrackingFrame = useCallback((frame: HandTrackingFrame) => {
    trackingFrameRef.current = frame;
    if (frame.framing) bodyBoxTrackerRef.current.push(frame.framing);
    ingestAutomaticFrame(frame);
  }, [ingestAutomaticFrame]);
  const getBodyBox = useCallback(
    (width: number, height: number) => bodyBoxTrackerRef.current.box(width, height),
    [],
  );
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
  const getFreshFramingFrame = useCallback(() => {
    const frame = trackingFrameRef.current;
    if (!frame?.framing || performance.now() - frame.updatedAt > 500) return null;
    return frame.framing;
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
  }, [inferenceRoute, localModel.status, socket.status]);

  useEffect(() => {
    if (config.publicDemo) return;
    let active = true;
    let controller: AbortController | null = null;
    const read = async () => {
      if (!active || controller) return;
      const request = new AbortController();
      controller = request;
      let timeout = 0;
      try {
        const response = await Promise.race([
          fetch(`${inferenceHttpUrl}/metadata`, { signal: request.signal }),
          new Promise<never>((_resolve, reject) => { timeout = window.setTimeout(() => {
            request.abort(); reject(new Error("metadata timeout"));
          }, 8000); }),
        ]);
        if (!response.ok) throw new Error("metadata unavailable");
        const body = await response.json() as InferenceMetadata;
        if (!active || request.signal.aborted) return;
        setMetadata(current => JSON.stringify(current) === JSON.stringify(body) ? current : body);
        setMetadataError(false);
      } catch {
        if (active) setMetadataError(true);
      } finally {
        window.clearTimeout(timeout);
        if (controller === request) controller = null;
      }
    };
    const refresh = () => { if (document.visibilityState === "visible") void read(); };
    void read();
    const interval = window.setInterval(refresh, 10000);
    window.addEventListener("focus", refresh);
    return () => { active = false; controller?.abort(); window.clearInterval(interval); window.removeEventListener("focus", refresh); };
  }, [inferenceHttpUrl, workspaceView]);

  useEffect(() => {
    if (config.publicDemo) return;
    if (managedData) return;
    if (!metadata?.collection_enabled) return;
    setCollectionProgressReady(false);
    const controller = new AbortController();
    fetch(`${inferenceHttpUrl}/collection/summary?batch=${PERSONAL_COLLECTION_BATCH}`, {
      credentials: "include",
      signal: controller.signal,
    })
      .then((response) => {
        if (!response.ok) throw new Error("collection summary unavailable");
        return response.json() as Promise<CollectionSummaryResponse>;
      })
      .then((body) => {
        if (controller.signal.aborted) return;
        if (body.batch !== PERSONAL_COLLECTION_BATCH || body.target_per_label !== PERSONAL_COLLECTION_TARGET) {
          throw new Error("Máy chủ chưa hỗ trợ đợt thu personal-100; hãy cập nhật máy chủ.");
        }
        setCollectionCounts(body.counts);
        setCollectionProgressReady(true);
        setCollectionNotice("");
      })
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setCollectionNotice("Chưa đọc được tiến độ các mẫu đã lưu.");
        }
      });
    return () => controller.abort();
  }, [metadata?.collection_enabled, inferenceHttpUrl, collectionContext, collectionSummaryRevision, managedData]);

  useEffect(() => {
    if (!managedData) return;
    const ready = data.ready && selectedDataset?.status === "draft" && data.snapshot?.permissions.collect === true && data.snapshot.collection_enabled;
    setCollectionProgressReady(ready);
    if (selectedDataset && data.ready) setCollectionCounts(selectedDataset.counts);
    else if (!selectedDataset) setCollectionCounts({});
    const availableLabels = selectedDatasetLabels?.entries.map(row => row.name) ??
      (!selectedDataset ? data.snapshot?.default_labels ?? [] : []);
    if (availableLabels.length && !availableLabels.includes(selectedLabel)) {
      setSelectedLabel(availableLabels[0]);
    }
    const session = remoteSessionRef.current;
    const persisted = session && session.context === collectionContextRef.current
      ? data.snapshot?.sessions.find(row => row.id === session.id) : null;
    if (session && data.ready && !persisted) {
      remoteSessionRef.current = null;
      remoteStateRef.current = "idle";
      collectionSessionRef.current = "idle"; setCollectionSession("idle");
    }
    if (persisted && ["stopped", "completed"].includes(persisted.state)) {
      remoteSessionRef.current = null;
      remoteStateRef.current = "idle";
      collectionSessionRef.current = "idle"; setCollectionSession("idle");
    } else if (persisted?.state === "running" && remoteStateRef.current === "running" && data.ready && !data.failed) {
      collectionSessionRef.current = "running"; setCollectionSession("running");
    }
    if (persisted?.state === "paused" && data.ready) {
      remoteStateRef.current = "paused"; collectionSessionRef.current = "paused"; setCollectionSession("paused");
    }
    if ((data.stale || data.error) && collectionSessionRef.current !== "idle") {
      if (!data.failed && remoteSessionRef.current) remoteStateRef.current = "paused";
      collectionSessionRef.current = "paused"; setCollectionSession(current => current === "idle" ? current : "paused");
    }
  }, [managedData, data.snapshot, data.ready, data.stale, data.error, data.failed, selectedDataset, selectedDatasetLabels, selectedLabel]);

  const canCapture =
    !serverModel.switching &&
    camera.status === "ready" &&
    (mode === "collect"
      ? collectionProgressReady && collectionSession === "running" &&
        selectedCollectionCount < collectionTarget &&
        pendingSample === null && !savingSample
      : inferenceRoute !== "unavailable" && inference.pendingSequence === null &&
        !automaticQueue.busy && !manualBusy && captureInputMode === "manual");
  const captureContextKey = [
    mode,
    mode === "collect" ? "collection" : inferenceRoute,
    capturePipeline.sampling,
    capturePipeline.framing,
    bodyFraming && mode === "recognize" ? "body" : "square",
  ].join(":");

  const capture = useSignCapture({
    videoRef,
    canStart: canCapture,
    captureContextKey,
    encodeVideoFrames:
      mode === "collect" || inferenceRoute === "server",
    preserveSourceFrames: mode === "collect",
    samplingStrategy: capturePipeline.sampling,
    getCropRegion:
      capturePipeline.framing === "adaptive" ? getFreshCropRegion : undefined,
    // Server recognition encodes each frame while the user signs.
    streamFrames: mode === "recognize" && inferenceRoute === "server",
    bodyFraming: bodyFraming && mode === "recognize",
    getFramingFrame: getFreshFramingFrame,
    getBodyBox,
    getLandmarkFeatures: getFreshLandmarkFeatures,
    getBaselineLandmarkFeatures: getFreshBaselineLandmarkFeatures,
    onCaptureStart: () => {
      const context = transcriptContextRef.current;
      manualTranscriptCaptureRef.current = autoTranscriptRef.current.beginCapture(
        context.contextKey, context.eligible,
      );
      dispatchInference({ type: "capture_started" });
    },
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
      if (mode === "collect") {
        if (collectionSessionRef.current !== "idle") changeCollectionSession("paused", "capture_error");
        setCollectionNotice(`${message} Phiên thu đã tạm dừng.`);
      } else {
        continueAutomaticCollectionRef.current();
      }
    },
    onFrames: (captured) => {
      const sequence = sequenceRef.current;
      sequenceRef.current += 1;
      const capturedAt = Date.now();
      if (mode === "collect") {
        const sourceFrames = captured.sourceFrames ?? captured.frames;
        const automaticCollection = collectionSession === "running";
        if (!automaticCollection) return;
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
        pendingRemoteSessionRef.current = remoteSessionRef.current;
        setPendingSample({
          sampleKey: createSessionId(),
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
          "Đã thu đủ hình tay. Đang lưu lượt này.",
        );
        dispatchInference({ type: "capture_cancelled", message: "Đã hoàn tất lượt thu dữ liệu." });
        return;
      }
      manualRequestRef.current = {
        sequence, route: inferenceRoute === "server" ? "server" : "local",
        contextKey: recognitionContextKey,
      };
      autoTranscriptRef.current.register(sequence, manualTranscriptCaptureRef.current);
      setManualBusy(true);
      dispatchInference({ type: "request_started", sequence });
      const sendToServer = () => {
        if (recognitionContextRef.current !== recognitionContextKey) {
          autoTranscriptRef.current.discard(sequence);
          manualRequestRef.current = null;
          setManualBusy(false);
          return;
        }
        if (!captured.frames.length) {
          autoTranscriptRef.current.discard(sequence);
          manualRequestRef.current = null;
          setManualBusy(false);
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
          context_words: sentenceContextWords(),
        };
        try {
          manualRequestRef.current = { sequence, route: "server", contextKey: recognitionContextKey };
          noteRecognitionActivity();
          socket.sendFrames(message);
        } catch {
          autoTranscriptRef.current.discard(sequence);
          manualRequestRef.current = null;
          setManualBusy(false);
          dispatchInference({ type: "connection_lost" });
        }
      };
      if (inferenceRoute === "server") {
        sendToServer();
      } else if (localModel.status === "ready") {
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
    mode === "collect" && collectionSession === "running";
  const automaticCollection = useAutomaticCollectionCycle({
    enabled: automaticCollectionEnabled,
    ready:
      camera.status === "ready" && collectionProgressReady &&
      selectedCollectionCount < collectionTarget,
    blocked:
      pendingSample !== null ||
      savingSample,
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
    if (previousCollectionContext.current === collectionContext) return;
    previousCollectionContext.current = collectionContext;
    if (managedData) {
      remoteSessionRef.current = null; pendingRemoteSessionRef.current = null; remoteStateRef.current = "idle"; deferredSessionStateRef.current = null;
      collectionSessionRef.current = "idle"; setCollectionSession("idle"); setDatasetId("");
    } else changeCollectionSession("idle", "context_changed");
    auditCollectionRef.current = null;
    setPendingSample(null);
    if (mode === "collect") {
      capture.cancel();
      setCollectionNotice("Tài khoản hoặc quyền đã thay đổi. Hãy bắt đầu phiên thu mới; mẫu đã lưu được giữ nguyên.");
    }
  }, [collectionContext, changeCollectionSession, capture, mode, managedData]);

  useEffect(() => {
    if (mode === "collect" && camera.status !== "ready" && collectionSessionRef.current === "running") {
      changeCollectionSession("paused", "camera_off");
      setCollectionNotice("Camera đã ngắt. Phiên thu đã tạm dừng; các mẫu đã lưu được giữ nguyên.");
    }
    if (
      capture.status === "capturing" &&
      (camera.status !== "ready" ||
        (mode === "recognize" && inferenceRoute === "unavailable"))
    ) {
      capture.cancel();
    }
  }, [camera.status, capture, inferenceRoute, mode, changeCollectionSession]);

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
      wordInsertionMode !== "manual" ||
      inference.phase !== "ok" ||
      inference.prediction?.status !== "ok" ||
      !inference.prediction.label
    ) {
      return;
    }
    appendWord(inference.prediction.label, false);
  };

  const changeWordInsertionMode = (nextMode: WordInsertionMode) => {
    invalidateManualComposition();
    sentenceSequencesRef.current.clear();
    sentenceCaptureRef.current = null;
    autoTranscriptRef.current.setMode(nextMode);
    setWordInsertionMode(nextMode);
    setNotice(nextMode === "automatic" ? "Đã bật thêm từ tự động." : "Đã bật thêm từ thủ công.");
  };

  const completeSentence = async () => {
    if (!transcript.words.length || composingSentence || config.publicDemo) return;
    setComposingSentence(true);
    const revision = ++composeRevisionRef.current;
    const words = [...transcript.words];
    try {
      const result = await composeSentence(
        inferenceHttpUrl,
        words,
      );
      if (revision !== composeRevisionRef.current) return;
      setComposedSentence(result.sentence);
      setComposedWarning((result.warnings ?? []).join(" · "));
      setNotice(
        result.warnings?.length ? result.warnings.join(" · ") : result.provider === "openai"
          ? "AI đã hoàn thiện câu."
          : "Đã chuẩn hóa câu bằng chế độ dự phòng nội bộ.",
      );
    } catch (error) {
      if (revision !== composeRevisionRef.current) return;
      setNotice(
        error instanceof Error ? error.message : "Không thể hoàn thiện câu.",
      );
    } finally {
      if (revision === composeRevisionRef.current) setComposingSentence(false);
    }
  };

  const clearSentence = () => {
    autoTranscriptRef.current.invalidate();
    sentenceSequencesRef.current.clear();
    sentenceCaptureRef.current = null;
    automaticTranscriptCaptureRef.current = null;
    manualTranscriptCaptureRef.current = null;
    automaticSentence.reset();
    applyTranscriptAction({ type: "clear" });
    setAutomaticAddedSequence(null);
    invalidateManualComposition();
  };

  const undoLastWord = (by: "staff" | "customer") => {
    const label = transcriptRef.current.words.at(-1);
    if (!label) return;
    autoTranscriptRef.current.invalidate();
    automaticSentence.skipPending();
    sentenceSequencesRef.current.clear();
    sentenceCaptureRef.current = null;
    automaticTranscriptCaptureRef.current = null;
    manualTranscriptCaptureRef.current = null;
    applyTranscriptAction({ type: "undo" });
    setAutomaticAddedSequence(null);
    invalidateManualComposition();
    usageRef.current.note({ type: "undo", by, label });
    setNotice(by === "customer" ? `Khách đã hoàn tác “${label}”.` : "Đã hoàn tác từ cuối.");
  };
  customerActionRef.current = action => { if (action === "undo_word") undoLastWord("customer"); };

  const sendStaffReply = (text: string, voice: boolean) => {
    setStaffReply(text);
    usageRef.current.note({ type: "reply", voice });
    setNotice(counterDisplay.connected ? "Đã gửi câu trả lời tới màn hình quầy." : "Câu trả lời đang hiển thị cho khách.");
  };

  // Both screens start over; the counter connection and the camera stay as they are.
  const startNewConversation = () => {
    usageRef.current.end();
    setStaffReply("");
    clearSentence();
    dispatchInference({ type: "capture_cancelled", message: "" });
    counterDisplay.newConversation();
    setNotice("Đã bắt đầu cuộc hội thoại mới.");
  };

  const copyTranscript = async () => {
    try {
      const draftText = automaticSentence.drafts.map(item => {
        const warning = [item.warning, item.compositionWarning].filter(Boolean).join(" · ");
        const text = item.warning ? item.words.join(" ") : item.sentence || item.words.join(" ");
        return warning ? `${text} [${warning}]` : text;
      }).join("\n");
      await copyText(automaticSentenceEnabled
        ? `Dự thảo chưa xác nhận:\n${draftText || transcript.words.join(" ")}`
        : composedWarning ? `${composedSentence} [${composedWarning}]` : composedSentence || transcript.words.join(" "));
      setNotice("Đã sao chép câu.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Không thể sao chép câu.");
    }
  };

  const switchMode = (nextMode: AppMode) => {
    if (nextMode === "collect" && !managedData && !metadata?.collection_enabled) return;
    // Collecting always runs automatically; recognizing returns to whichever capture mode the user left it in.
    if (mode === "recognize") recognizeCaptureModeRef.current = captureInputMode;
    setMode(nextMode);
    capture.cancel();
    changeCollectionSession("idle", "context_changed");
    setCaptureInputMode(nextMode === "collect" ? "automatic" : recognizeCaptureModeRef.current);
    setPendingSample(null);
    if (collectionProgressReady) setCollectionNotice("");
  };

  const pauseCollection = () => {
    changeCollectionSession("paused");
    capture.cancel();
    setCollectionNotice("Đã tạm dừng. Các mẫu đã lưu được giữ nguyên.");
  };

  const stopCollection = () => {
    changeCollectionSession("idle");
    capture.cancel();
    if (!savingSampleRef.current) setPendingSample(null);
    setCollectionNotice("Đã dừng phiên. Các mẫu đã lưu được giữ nguyên.");
  };

  const saveCollectionSample = useCallback(async () => {
    if (!pendingSample || savingSampleRef.current) return;
    const remoteSession = pendingRemoteSessionRef.current ?? remoteSessionRef.current;
    if (managedData && (!remoteSession || remoteSession.context !== collectionContextRef.current)) return;
    const pausedRetry = managedData && collectionSessionRef.current === "paused" && remoteSessionRef.current?.id === remoteSession?.id;
    const auditSession = auditCollectionRef.current;
    const saveContext = collectionContext;
    const payload: CollectionSampleRequest = {
      session_id: sessionIdRef.current,
      batch: PERSONAL_COLLECTION_BATCH,
      sample_key: pendingSample.sampleKey,
      captured_at: pendingSample.capturedAt,
      duration_ms: pendingSample.durationMs,
      expected_label: pendingSample.expectedLabel,
      hand: pendingSample.hand,
      frames: pendingSample.frames,
      predicted_label: null,
      predicted_confidence: null,
      distance: pendingSample.distance,
      lighting: pendingSample.lighting,
      negative_action: pendingSample.negativeAction,
    };
    savingSampleRef.current = true;
    setSavingSample(true);
    setCollectionNotice("");
    try {
      if (managedData) {
        await remoteQueueRef.current;
        if (collectionContextRef.current !== saveContext) return;
        if (pausedRetry && !await mutateData(`/sessions/${remoteSession!.id}/state`, { state: "running" })) {
          throw new Error("Chưa xác nhận được phiên thu để thử lưu lại.");
        }
        holdDataReads(true);
      }
      const response = await fetch(
        managedData ? `${config.platformHttpUrl}/api/v1/workspace/data/sessions/${remoteSession!.id}/samples` : `${inferenceHttpUrl}/collection/samples`,
        {
          method: "POST",
          credentials: "include",
          ...(managedData ? { signal: AbortSignal.timeout(60000) } : {}),
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
      );
      if (collectionContextRef.current !== saveContext) return;
      if (!response.ok) {
        const failure = (await response.json().catch(() => null)) as
          | { detail?: string }
          | null;
        throw new Error(failure?.detail ?? "Máy chủ không thể lưu mẫu.");
      }
      const saved = (await response.json()) as CollectionSampleResponse;
      if (collectionContextRef.current !== saveContext) return;
      if (saved.sample_id !== pendingSample.sampleKey ||
        saved.expected_label !== pendingSample.expectedLabel || saved.hand !== pendingSample.hand ||
        !Number.isSafeInteger(saved.label_count) || !Number.isSafeInteger(saved.label_hand_count) ||
        saved.label_hand_count < 1 || saved.label_count! < saved.label_hand_count ||
        saved.label_count! > collectionTarget) {
        throw new Error("Phản hồi lưu mẫu không hợp lệ; phiên đã tạm dừng.");
      }
      setCollectionCounts((current) => {
        const otherCount = saved.label_count! - saved.label_hand_count;
        return {
          ...current,
          [saved.expected_label]: saved.hand === "right"
            ? { right: saved.label_hand_count, left: otherCount }
            : { right: otherCount, left: saved.label_hand_count },
        };
      });
      setPendingSample(null);
      if (!managedData && auditSession && !auditSession.savedSamples.has(saved.sample_id)) {
        auditSession.savedSamples.add(saved.sample_id);
        auditSession.record({ event_id: createSessionId(), event_type: "collection.sample_saved",
          resource_id: auditSession.id, capture_session_id: payload.session_id,
          model_version: auditSession.modelVersion, saved_samples: auditSession.savedSamples.size,
          sample_id: saved.sample_id });
      }
      const target = collectionTarget;
      const completedLabel = saved.label_count! >= target;
      if (completedLabel && collectionSessionRef.current !== "idle") changeCollectionSession("idle", "completed");
      setCollectionNotice(
        completedLabel
          ? `Đã đủ ${saved.label_count}/${target} mẫu “${saved.expected_label}”. Phiên đã hoàn thành.`
          : `Đã lưu ${saved.label_count}/${target} mẫu “${saved.expected_label}”.`,
      );
    } catch (error) {
      if (collectionContextRef.current !== saveContext) return;
      if (collectionSessionRef.current !== "idle") changeCollectionSession("paused", "save_error");
      setCollectionNotice(
        `${error instanceof Error ? error.message : "Không thể lưu mẫu video."} ${collectionSessionRef.current === "idle" ? "Phiên đã dừng" : "Phiên đã tạm dừng"}; mẫu được giữ trong bộ nhớ để thử lưu lại.`,
      );
    } finally {
      if (!managedData && collectionContextRef.current !== saveContext) {
        setCollectionProgressReady(false);
        refreshCollectionSummary(current => current + 1);
      }
      savingSampleRef.current = false;
      setSavingSample(false);
      if (managedData) holdDataReads(false);
      if (managedData && collectionContextRef.current === saveContext) {
        await refreshData();
        if (collectionContextRef.current === saveContext) {
          const deferred = deferredSessionStateRef.current;
          deferredSessionStateRef.current = null;
          if (deferred) changeCollectionSession(deferred.next, deferred.reason);
          else if (pausedRetry && collectionSessionRef.current !== "idle") changeCollectionSession("paused");
        }
      }
    }
  }, [
    pendingSample,
    inferenceHttpUrl,
    changeCollectionSession,
    collectionContext,
    managedData,
    collectionTarget,
    refreshData,
    mutateData,
    holdDataReads,
  ]);

  useEffect(() => {
    if (
      !automaticCollectionEnabled ||
      !pendingSample ||
      savingSample
    ) {
      return;
    }
    void saveCollectionSample();
  }, [
    automaticCollectionEnabled,
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
    inference.phase === "disconnected" && !connectionSettled
      ? "ready"
      : inference.pendingSequence !== null
      ? inference.phase
      : capture.status === "capturing" ||
    automaticPhase === "capturing" || automaticPhase === "postroll"
      ? "capturing"
      : capture.status === "encoding" || automaticPhase === "encoding"
        ? "processing"
        : inference.phase;
  const publishToCounter = counterDisplay.publish;
  const counterConnected = counterDisplay.connected;
  const counterSentence = automaticSentenceEnabled
    ? automaticSentence.drafts.filter(draft => draft.sentence).at(-1)?.sentence ?? ""
    : composedSentence;
  const counterWord = inference.prediction?.status === "ok" && inference.prediction.label !== IDLE_LABEL
    ? inference.prediction.label : null;
  useEffect(() => {
    if (!counterConnected) return;
    publishToCounter({
      phase: visiblePhase, word: counterWord?.slice(0, 64) ?? null,
      words: transcript.words.slice(-200).map(word => word.slice(0, 64)),
      sentence: counterSentence.slice(0, 600), guide: guideFraming, reply: staffReply.slice(0, REPLY_MAX),
    });
  }, [counterConnected, publishToCounter, visiblePhase, counterWord, transcript.words, counterSentence, guideFraming, staffReply]);
  const collectionEnabled =
    managedData ? data.snapshot?.permissions.collect === true && data.snapshot.collection_enabled : !config.publicDemo &&
    metadata?.collection_enabled === true &&
    (metadata.collection_labels?.length ?? 0) > 0;
  const collectionLabels = managedData ? selectedDatasetLabels?.entries.map(row => row.name) ??
    (!selectedDataset ? data.snapshot?.default_labels ?? [] : []) : metadata?.collection_labels?.length
    ? [...metadata.collection_labels, IDLE_LABEL]
    : [];
  const modelSwitchLocked = capture.status !== "idle" || manualBusy || automaticQueue.isPending() ||
    automaticPhase === "capturing" || automaticPhase === "postroll" || automaticPhase === "encoding" ||
    composingSentence || automaticSentence.drafts.some(draft => draft.status === "composing") ||
    mode === "collect" || savingSample || pendingSample !== null || !labelsVerified ||
    metadata?.labels.length !== 31;

  const switchServerModel = async (id: string) => {
    if (modelSwitchLocked) return;
    const previousVersion = metadata?.model_version;
    const previousOption = serverModel.active.id;
    const verified = await serverModel.choose(id, metadata?.labels ?? []);
    if (!verified) return;
    if (previousVersion && previousOption !== id &&
      (previousOption === "current" || previousOption === "seated") && (id === "current" || id === "seated")) {
      recordActivity({ event_id: createSessionId(), event_type: "model.switched", resource_id: sessionIdRef.current,
        model_version: verified.model_version, previous_model_version: previousVersion,
        model_option: id, previous_model_option: previousOption });
    }
    setMetadata(verified);
    setMetadataError(false);
    manualRequestRef.current = null;
    setManualBusy(false);
    autoTranscriptRef.current.invalidate();
    sentenceSequencesRef.current.clear();
    sentenceCaptureRef.current = null;
    applyTranscriptAction({ type: "clear" });
    invalidateManualComposition();
    dispatchInference({ type: "connection_lost" });
    setNotice("Đã chuyển model và xóa câu nháp của lượt nhận dạng trước.");
  };

  const connectionState =
    inferenceRoute !== "unavailable"
      ? "connected"
      : config.publicDemo && localModel.status === "loading"
        ? "connecting"
        : socket.status;
  useEffect(() => {
    if (connectionState !== "connecting") setConnectionSettled(true);
  }, [connectionState]);
  const activeModelVersion = inferenceRoute === "local" && localModel.status === "ready"
    ? localModel.modelVersion
    : metadata?.model_version ?? "";
  const fallbackWorkspaceCapabilities: Partial<Record<WorkspaceView, boolean>> = {
    data: collectionEnabled,
    evaluation: false,
    monitoring: !config.publicDemo,
    activity: false,
    reports: false,
    integrations: false,
    team: false,
    models: true,
    settings: false,
  };
  const workspaceCapabilities: Partial<Record<WorkspaceView, boolean>> = {
    ...(platform.capabilities ?? fallbackWorkspaceCapabilities), activity: !config.publicDemo,
  };
  const { user: platformUser } = platform;
  const systemAdmin = platformUser?.role === "system_admin";
  const internalTools = systemAdmin || platformUser?.role === "model_admin";
  const enteredSystemRef = useRef<string | null>(null);
  useEffect(() => {
    if (!systemAdmin || !platformUser || enteredSystemRef.current === platformUser.id) return;
    enteredSystemRef.current = platformUser.id;
    if (["/", workspaceBasePath(), `${workspaceBasePath()}/`].includes(window.location.pathname)) navigateWorkspaceView("overview");
  }, [systemAdmin, platformUser, navigateWorkspaceView]);
  const activeWorkspaceView = (workspaceView === "data" && !managedData && !collectionEnabled) || workspaceCapabilities[workspaceView] === false
    ? "recognize"
    : workspaceView;
  const navigateWorkspace = (nextView: WorkspaceView) => {
    if (capture.status !== "idle" || savingSample) return;
    if (workspaceCapabilities[nextView] === false) return;
    if (nextView === "recognize") {
      switchMode("recognize");
    } else if (nextView === "data") {
      if (!managedData && !collectionEnabled) return;
      switchMode("collect");
    } else {
      capture.cancel();
      changeCollectionSession("idle", "navigation");
      if (camera.status === "ready") camera.disable();
    }
    navigateWorkspaceView(nextView);
  };

  return (
    <div ref={shellRef} className={`app-shell ${sidebar.collapsed ? "sidebar-collapsed" : ""}`}
      style={{ "--sidebar-width": `${sidebar.width}px` } as CSSProperties}>
      <header className="app-header">
        <button type="button" className="mobile-sidebar-toggle" onClick={() => setMobileSidebarOpen(true)}
          aria-label="Mở menu" aria-expanded={mobileSidebarOpen} title="Mở menu">
          <PanelLeft size={20} aria-hidden="true" />
        </button>
        <span className="mobile-header-logo" role="img" aria-label="VSign">
          <img className="mobile-header-logo-mark" src="/brand/vsign-mark.svg" alt="" draggable={false} />
          <SignWordmark />
        </span>
        <SidebarResizer shellRef={shellRef} width={sidebar.width} collapsed={sidebar.collapsed}
          onResize={sidebar.setWidth} onCollapse={sidebar.setCollapsed} onReset={sidebar.resetWidth} />
        <AppSidebar
          activeView={activeWorkspaceView}
          capabilities={workspaceCapabilities}
          user={platform.user}
          onLogout={platform.user && platform.authMode !== "local_admin" ? platform.logout : undefined}
          onNavigate={navigateWorkspace}
          mobileOpen={mobileSidebarOpen}
          onClose={() => setMobileSidebarOpen(false)}
        />
      </header>
      <button type="button" className={`mobile-sidebar-backdrop${mobileSidebarOpen ? " mobile-open" : ""}`}
        onClick={() => setMobileSidebarOpen(false)} aria-label="Đóng menu"
        aria-hidden={!mobileSidebarOpen} tabIndex={mobileSidebarOpen ? 0 : -1} />

      <div className="app-body">
      {/* The workspace lives in one rounded panel that scrolls on its own; the shell around it stays put. */}
      <div ref={panelRef} className="app-panel">
      <WorkspaceTopbar view={activeWorkspaceView} workspaceName={platform.context?.name} connection={connectionState}
        systemAdmin={systemAdmin}
        sidebarCollapsed={sidebar.collapsed} onToggleSidebar={sidebar.toggleCollapsed} />
      <div className="workspace-notices">
      {activityRecorder.dropped > 0 && <p className="metadata-warning" role="status">
        Nhật ký chờ đã đầy: {activityRecorder.dropped} sự kiện không được đưa vào hàng đợi và chưa được ghi.
      </p>}
      {activityRecorder.error && <p className="metadata-warning" role="status">
        {activityRecorder.error} {activityRecorder.pending} sự kiện đang chờ trong trang này.
        <button type="button" className="icon-button" title="Thử ghi lại nhật ký" aria-label="Thử ghi lại nhật ký"
          disabled={activityRecorder.busy} onClick={activityRecorder.retry}><RefreshCw size={16} /></button>
      </p>}
      {!platform.user && mode === "collect" && <p className="metadata-warning" role="status">
        Chưa đăng nhập: phiên thu vẫn lưu mẫu nhưng không được ghi vào nhật ký hoạt động.
      </p>}
      {serverModel.error && <p className="metadata-warning model-switch-error" role="alert">{serverModel.error}</p>}

      {showMockBanner && (
        <div className="mock-banner" role="status">
          <strong>Mô phỏng – chưa dùng mô hình AI thật.</strong>
          <span>Kết quả ở chế độ này chỉ là mô phỏng.</span>
        </div>
      )}
      {!mockMode && !labelsVerified && !config.publicDemo && (
        <div className="ai-banner" role="status">
          <strong>AI baseline legacy đang hoạt động.</strong>
          <span>Đây là checkpoint Multi‑VSL cũ và chỉ hiển thị class ID; chưa phải model common‑20 của nguồn mới.</span>
        </div>
      )}
      {inferenceRoute === "local" && localModel.status === "ready" && landmarkRuntime !== "v3" && (
        <p className="metadata-warning" role="status">AI thử nghiệm · Chưa dùng làm demo chính.</p>
      )}
      {metadataError && (
        <p className="metadata-warning" role="status">
          Chưa đọc được metadata của máy chủ; trạng thái kết nối vẫn được theo dõi bên dưới.
        </p>
      )}
      {localModel.status === "unavailable" && mode === "recognize" && (
        <p className="metadata-warning" role="status">
          AI realtime local chưa tải được ({localModel.error ?? "lỗi không xác định"});
          {config.publicDemo
            ? " hãy tải lại trang hoặc thử trên Chrome/Edge. Bản công khai không có máy chủ dự phòng."
            : " đang dùng model máy chủ dự phòng."}
        </p>
      )}
      {config.publicDemo && (
        <p className="metadata-warning" role="status">
          Bản demo: camera và AI chạy trên thiết bị của bạn, không gửi video lên máy chủ.
        </p>
      )}
      </div>

      <main
        id="workspace"
        data-view={activeWorkspaceView}
        className={`workspace ${activeWorkspaceView === "data" && managedData && dataTab !== "collect" ? "workspace-single" : activeWorkspaceView === "recognize" || activeWorkspaceView === "data" ? `mode-${mode}` : "workspace-single"}`}
        aria-labelledby={activeWorkspaceView === "data" && managedData ? "workspace-data-title" : activeWorkspaceView === "recognize" || activeWorkspaceView === "data" ? "workspace-title" : "workspace-page-title"}
      >
        {activeWorkspaceView === "data" && managedData && <WorkspaceData reader={data} tab={dataTab}
          collectAside={mode === "collect" ? <CollectionWordPicker labels={collectionLabels} selectedLabel={selectedLabel}
            counts={collectionCounts} target={collectionTarget} onLabelChange={setSelectedLabel} showReference={false}
            controlsLocked={automaticCollectionEnabled || capture.status !== "idle" || savingSample || pendingSample !== null} /> : undefined}
          datasetId={datasetId} userId={platform.user?.id}
          locked={savingSample || capture.status !== "idle" || collectionSession !== "idle"}
          consent={!!explicitCollectionConsent} onConsentChange={accepted => setCollectionConsent({ context: collectionContext, datasetId, revision: consentRevision, accepted })}
          onDatasetChange={setDatasetId}
          onTabChange={tab => { setDataTab(tab); if (tab === "collect") switchMode("collect"); else { capture.cancel(); if (camera.status === "ready") camera.disable(); } }}
          onUseSession={row => {
            setDatasetId(row.dataset_version_id); setDataTab("collect"); setMode("collect");
            remoteSessionRef.current = { id: row.id, datasetId: row.dataset_version_id, context: collectionContextRef.current };
            changeCollectionSession("paused");
          }} />}
        {activeWorkspaceView === "activity" ? <WorkspaceActivity
          platformUrl={config.platformHttpUrl} user={platform.user} canRead={platform.capabilities?.activity === true}
          workspaceName={platform.context?.name} workspaceId={platform.context?.workspace_id ?? "local"}
          onLogin={platform.login} loginBusy={platform.submitting}
          sessionLoading={platform.loading} authMode={platform.authMode}
        /> : activeWorkspaceView === "reports" && !config.publicDemo ? <WorkspaceReports
          platformUrl={config.platformHttpUrl} workspaceId={platform.context?.workspace_id ?? "local"}
          enabled={platform.capabilities?.reports === true}
        /> : activeWorkspaceView === "models" && !config.publicDemo ? <WorkspaceModels
          platformUrl={config.platformHttpUrl} user={platform.user}
          workspaceId={platform.context?.workspace_id ?? "local"} workspaceName={platform.context?.name}
          onLogin={platform.login} loginBusy={platform.submitting} runtime={runtime}
          modelSelector={internalTools && import.meta.env.DEV && config.serverModels.length > 1 ? (
            <ServerModelSelector options={config.serverModels} value={serverModel.active.id} disabled={modelSwitchLocked}
              switching={serverModel.switching} error={serverModel.error} onChange={id => void switchServerModel(id)} />
          ) : undefined}
          sessionLoading={platform.loading} authMode={platform.authMode}
        /> : activeWorkspaceView === "evaluation" && !config.publicDemo ? <WorkspaceEvaluations
          platformUrl={config.platformHttpUrl} workspaceId={platform.context?.workspace_id ?? "local"} user={platform.user}
        /> : activeWorkspaceView === "integrations" && !config.publicDemo ? <WorkspaceIntegrations
          platformUrl={config.platformHttpUrl} workspaceId={platform.context?.workspace_id ?? "local"} user={platform.user}
        /> : activeWorkspaceView === "team" && !config.publicDemo ? <WorkspaceTeam
          platformUrl={config.platformHttpUrl} workspaceId={platform.context?.workspace_id ?? "local"} user={platform.user}
        /> : activeWorkspaceView === "settings" && !config.publicDemo ? <WorkspaceSettings
          platformUrl={config.platformHttpUrl} workspaceId={platform.context?.workspace_id ?? "local"} user={platform.user}
          onWorkspaceChanged={() => { void platform.reload(); void refreshData(); }}
        /> : activeWorkspaceView === "overview" && systemAdmin ? <Suspense fallback={<DashboardPageSkeleton />}><SystemDashboard
          platformUrl={config.platformHttpUrl} workspaceId={platform.context?.workspace_id ?? "local"}
          user={platform.user} runtime={runtime} onNavigate={navigateWorkspace}
        /></Suspense> : activeWorkspaceView !== "recognize" && activeWorkspaceView !== "data" ? (
          <WorkspacePage
            systemAdmin={systemAdmin}
            view={activeWorkspaceView}
            connection={connectionState}
            modelVersion={activeModelVersion}
            backend={inferenceRoute === "local" ? "local" : metadata?.backend ?? serverModel.active.id}
            protocolVersion={metadata?.protocol_version ?? "1.0"}
            labelCount={metadata?.labels.length ?? localModel.labels.length}
            labelsVerified={labelsVerified}
            collectionEnabled={collectionEnabled}
            collectionTarget={metadata?.collection_target_per_hand ?? PERSONAL_COLLECTION_TARGET}
            members={platform.members}
            auditEvents={platform.auditEvents}
            capabilities={workspaceCapabilities}
            onNavigate={navigateWorkspace}
            runtime={!config.publicDemo ? runtime : undefined}
            onRefreshRuntime={!config.publicDemo ? () => void runtime.refresh() : undefined}
            modelSelector={internalTools && import.meta.env.DEV && !config.publicDemo && config.serverModels.length > 1 ? (
              <ServerModelSelector
                options={config.serverModels}
                value={serverModel.active.id}
                disabled={modelSwitchLocked}
                switching={serverModel.switching}
                error=""
                onChange={id => void switchServerModel(id)}
              />
            ) : undefined}
          />
        ) : activeWorkspaceView === "data" && managedData && dataTab !== "collect" ? null : <>
        {!(activeWorkspaceView === "data" && managedData) && <header className="workspace-intro">
          <h1 id="workspace-title" className="workspace-title">
            {mode === "recognize" ? "Nhận dạng ký hiệu" : "Thu dữ liệu cải thiện AI"}
          </h1>
          {mode === "recognize" && !config.publicDemo && platform.user && (
            <CounterDisplayControl display={counterDisplay} onNewConversation={startNewConversation}
              onEndSession={() => { usageRef.current.end(); setStaffReply(""); }}
              locked={capture.status !== "idle" || automaticPhase === "capturing" || automaticPhase === "postroll"} />
          )}
        </header>}
        <CameraPanel
          videoRef={videoRef}
          camera={camera}
          connection={connectionState}
          runtimeLabel={config.gpuRuntime && inferenceRoute === "server"
            ? inferenceEndpoint.kind === "gpu" ? "GPU" : "Mac" : undefined}
          captureStatus={capture.status}
          canCapture={canCapture}
          purpose={mode}
          framingMode={guideFraming}
          captureInputMode={captureInputMode}
          automaticPhase={automaticPhase}
          automaticQueue={{
            waitingCount: automaticQueue.waitingCount,
            busy: automaticQueue.busy || manualBusy,
            full: automaticQueue.full,
            lastTiming: automaticQueue.lastTiming,
            notice: automaticCaptureNotice,
          }}
          automaticAvailable={
            mode === "collect"
              ? collectionProgressReady
              : inferenceRoute !== "unavailable"
          }
          automaticCollectionPhase={automaticCollection.phase}
          automaticCollectionCountdown={automaticCollection.countdown}
          collectionControls={mode === "collect" ? {
            state: collectionSession,
            ready: camera.status === "ready" && collectionProgressReady && collectionPolicyReady && !pendingSample && !savingSample,
            completed: selectedCollectionCount >= collectionTarget,
            onStart: () => changeCollectionSession("running"),
            onPause: pauseCollection,
            onStop: stopCollection,
          } : undefined}
          onCaptureInputModeChange={(nextMode) => {
            captureModeTouched.current = true;
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
          remote={counterDisplay.connected ? { name: counterDisplay.displayName || "máy khách" } : undefined}
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
              target={collectionTarget}
              pending={pendingSample}
              prediction={inference.prediction}
              saving={savingSample}
              notice={collectionNotice}
              controlsLocked={automaticCollectionEnabled || capture.status !== "idle" || savingSample || pendingSample !== null}
              automaticActive={automaticCollectionEnabled}
              wordPickerElsewhere={managedData}
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
          {mode === "recognize" && (
            <TranscriptPanel
              words={transcript.words}
              notice={notice}
              composedSentence={composedSentence}
              composedWarning={composedWarning}
              composing={composingSentence}
              composeAvailable={!config.publicDemo && metadata !== null}
              composeWithAi={metadata?.sentence_ai_enabled === true}
              automatic={automaticSentenceEnabled}
              sentenceDrafts={automaticSentence.drafts}
              onCompose={() => void completeSentence()}
              onUndo={() => undoLastWord("staff")}
              onClear={() => {
                // Without a counter there is no "new conversation" button; clearing everything starts one.
                if (!counterDisplay.connected) { usageRef.current.end(); setStaffReply(""); }
                clearSentence();
                setNotice("Đã xóa toàn bộ câu.");
              }}
              onCopy={() => void copyTranscript()}
            />
          )}
          {mode === "recognize" && (
            <ResultPanel
              cameraReady={camera.status === "ready"}
              phase={visiblePhase}
              prediction={inference.prediction}
              guidance={
                config.publicDemo && localModel.status === "loading"
                  ? "Đang tải AI trên thiết bị của bạn…"
                  : inference.guidance
              }
              onAdd={addPrediction}
              canUseLabels={labelsVerified}
              collectionReview={false}
              automaticCapture={captureInputMode === "automatic"}
              wordInsertionMode={wordInsertionMode}
              onWordInsertionModeChange={changeWordInsertionMode}
              automaticInsertionAvailable={autoTranscriptAvailable}
              automaticAdded={automaticAddedSequence === inference.prediction?.sequence}
            />
          )}
          {mode === "recognize" && !config.publicDemo && platform.user && (
            <StaffReplyPanel reply={staffReply} counter={counterDisplay.connected}
              onSend={(text, source) => sendStaffReply(text, source === "voice")} onClear={() => setStaffReply("")} />
          )}
        </div>
        </>}
      </main>

      </div>
      <div className="app-statusbar">
        <div className="header-tools" aria-label="Công cụ hệ thống" role="group">
          <details ref={workspaceToolsRef} className="workspace-tools" name="header-tools">
            <summary title="Công cụ" aria-label="Công cụ"><Wrench size={18} aria-hidden="true" /><span className="sr-only">Công cụ</span></summary>
            <div className="workspace-tools-content">
              <button type="button" className={mode === "collect" ? "active" : ""}
                aria-pressed={mode === "collect"}
                disabled={(!managedData && !collectionEnabled) || capture.status !== "idle" || automaticPhase === "capturing" ||
                  automaticPhase === "postroll" || automaticPhase === "encoding" || savingSample}
                title={collectionEnabled ? undefined : config.publicDemo
                  ? "Bản công khai không lưu video; hãy dùng bản local để thu dữ liệu"
                  : "Thu dữ liệu chưa được bật ở máy chủ"}
                onClick={(event) => {
                  switchMode("collect");
                  if (managedData) { setDataTab("collect"); navigateWorkspaceView("data"); }
                  const disclosure = event.currentTarget.closest("details");
                  if (disclosure) {
                    disclosure.open = false;
                    disclosure.querySelector("summary")?.focus();
                  }
                }}>
                <Database size={18} aria-hidden="true" />Thu dữ liệu AI
              </button>
              {internalTools && import.meta.env.DEV && !config.publicDemo && <a href="/dev-test" className="dev-link"
                title="Dev / Test" aria-label="Dev / Test"><FlaskConical size={18} aria-hidden="true" />Dev / Test</a>}
            </div>
          </details>
          {internalTools && <details className="runtime-settings" name="header-tools" open={serverModel.switching || undefined}>
            <summary title="Cấu hình AI" aria-label="Cấu hình AI"><Robot size={18} aria-hidden="true" /><span className="sr-only">Cấu hình AI</span></summary>
            <div className="runtime-settings-content">
              {import.meta.env.DEV && !config.publicDemo && config.serverModels.length > 1 && <ServerModelSelector
                options={config.serverModels} value={serverModel.active.id} disabled={modelSwitchLocked}
                switching={serverModel.switching} error="" onChange={id => void switchServerModel(id)}
              />}
              {inferenceRoute === "local" && localModel.status === "ready" && (
                <div className="runtime-description">
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
                    <button type="button" className={landmarkRuntime === "v3" ? "active" : ""}
                      aria-pressed={landmarkRuntime === "v3"}
                      disabled={capture.status !== "idle" || inference.pendingSequence !== null ||
                        automaticPhase === "capturing" || automaticPhase === "postroll"}
                      onClick={() => selectLandmarkRuntime("v3")}>
                      V3 demo
                    </button>
                    <button type="button" className={landmarkRuntime === "v5" ? "active" : ""}
                      aria-pressed={landmarkRuntime === "v5"}
                      disabled={capture.status !== "idle" || inference.pendingSequence !== null ||
                        automaticPhase === "capturing" || automaticPhase === "postroll"}
                      onClick={() => selectLandmarkRuntime("v5")}>
                      V5 thử nghiệm
                    </button>
                    <button type="button" className={landmarkRuntime === "v4_2" ? "active" : ""}
                      aria-pressed={landmarkRuntime === "v4_2"}
                      disabled={capture.status !== "idle" || inference.pendingSequence !== null ||
                        automaticPhase === "capturing" || automaticPhase === "postroll"}
                      onClick={() => selectLandmarkRuntime("v4_2")}>
                      V4.2 thử nghiệm
                    </button>
                  </div>
                </div>
              )}
              <p className="runtime-footnote">Nhận dạng từng ký hiệu · Không phải dịch hội thoại liên tục.</p>
              <p className="runtime-version">Protocol {metadata?.protocol_version ?? "1.0"} · {inferenceRoute === "local" && localModel.status === "ready"
                ? localModel.modelVersion : metadata?.model_version ?? "đang đọc metadata"}</p>
            </div>
          </details>}
        </div>
        <BackendLocationBadge location={backendLocation} gpuName={socket.gpuName} connecting={socket.status === "connecting"} />
      </div>
      </div>
    </div>
  );
}
