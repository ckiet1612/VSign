import { useCallback, useEffect, useRef, useState } from "react";
import type { HandTrackingFrame } from "../components/HandTrackingOverlay";
import {
  AutomaticSignSegmenter,
  type AutomaticCapturePhase,
} from "../lib/autoSegmentation";

interface AutomaticSignCaptureOptions {
  enabled: boolean;
  paused: boolean;
  onSequence: (frames: number[][], baselineFrames: number[][]) => void;
}

export interface AutomaticSignCaptureController {
  phase: AutomaticCapturePhase;
  ingest: (frame: HandTrackingFrame) => void;
}

export function useAutomaticSignCapture({
  enabled,
  paused,
  onSequence,
}: AutomaticSignCaptureOptions): AutomaticSignCaptureController {
  const segmenterRef = useRef(new AutomaticSignSegmenter());
  const enabledRef = useRef(enabled);
  const pausedRef = useRef(paused);
  const onSequenceRef = useRef(onSequence);
  const [phase, setPhase] = useState<AutomaticCapturePhase>("off");
  enabledRef.current = enabled;
  pausedRef.current = paused;
  onSequenceRef.current = onSequence;

  useEffect(() => {
    segmenterRef.current.reset(enabled);
    setPhase(enabled ? "waiting" : "off");
  }, [enabled]);

  const ingest = useCallback((frame: HandTrackingFrame) => {
    if (!enabledRef.current || pausedRef.current) return;
    const update = segmenterRef.current.push(
      frame.features,
      frame.updatedAt,
      frame.baselineFeatures,
    );
    setPhase((current) =>
      current === update.phase ? current : update.phase,
    );
    if (update.sequence && update.baselineSequence) {
      onSequenceRef.current(update.sequence, update.baselineSequence);
    }
  }, []);

  return { phase, ingest };
}
