import type { NormalizedLandmark } from "@mediapipe/tasks-vision";
import { isUsableUpperBodyPose } from "./landmarkFeatures";

const HOLD_MS = 150;
const FULL_OPACITY_MS = 75;
const MAX_MATCH_DISTANCE = 0.55;
type Handedness = "Left" | "Right";

export interface DisplayHand {
  id: number;
  landmarks: readonly NormalizedLandmark[];
  opacity: number;
  held: boolean;
}

export interface TrackingDisplayFrame {
  hands: readonly DisplayHand[];
  pose: {
    landmarks: readonly NormalizedLandmark[];
    opacity: number;
  } | null;
}

class CoordinateFilter {
  private derivative = 0;
  private filtered: number;

  constructor(private raw: number, private at: number) {
    this.filtered = raw;
  }

  update(value: number, timestamp: number): number {
    const seconds = (timestamp - this.at) / 1000;
    if (seconds <= 0) return this.filtered;
    // One Euro filtering: stronger smoothing at rest, less lag during motion.
    const alpha = (cutoff: number) => 1 / (1 + 1 / (2 * Math.PI * cutoff * seconds));
    this.derivative += alpha(1) * ((value - this.raw) / seconds - this.derivative);
    this.filtered += alpha(1.5 + 16 * Math.abs(this.derivative)) * (value - this.filtered);
    this.raw = value;
    this.at = timestamp;
    return this.filtered;
  }
}

class LandmarkFilter {
  private coordinates: CoordinateFilter[][];

  constructor(points: readonly NormalizedLandmark[], timestamp: number) {
    this.coordinates = points.map((point) =>
      [point.x, point.y, point.z].map((value) => new CoordinateFilter(value, timestamp)),
    );
  }

  update(points: readonly NormalizedLandmark[], timestamp: number): NormalizedLandmark[] {
    return points.map((point, index) => ({
      ...point,
      x: this.coordinates[index][0].update(point.x, timestamp),
      y: this.coordinates[index][1].update(point.y, timestamp),
      z: this.coordinates[index][2].update(point.z, timestamp),
    }));
  }
}

interface HandTrack {
  id: number;
  handedness: Handedness | null;
  seenAt: number;
  wrist: { x: number; y: number };
  velocity: { x: number; y: number };
  filter: LandmarkFilter;
  landmarks: readonly NormalizedLandmark[];
}

interface HandObservation {
  landmarks: readonly NormalizedLandmark[];
  handedness: Handedness | null;
}

function validPoints(points: readonly NormalizedLandmark[], count: number): boolean {
  return points.length === count && points.every((point) =>
    Number.isFinite(point.x) && Number.isFinite(point.y) && Number.isFinite(point.z),
  );
}

function matchHands(observations: readonly HandObservation[], tracks: readonly HandTrack[], timestamp: number) {
  let bestCost = Number.POSITIVE_INFINITY;
  let best: (HandTrack | null)[] = [];
  const visit = (index: number, chosen: (HandTrack | null)[], cost: number) => {
    if (index === observations.length) {
      if (cost < bestCost) { bestCost = cost; best = chosen; }
      return;
    }
    const observation = observations[index];
    const wrist = observation.landmarks[0];
    for (const track of tracks) {
      if (chosen.includes(track)) continue;
      const seconds = Math.min((timestamp - track.seenAt) / 1000, 0.075);
      const distance = Math.hypot(
        wrist.x - track.wrist.x - track.velocity.x * seconds,
        wrist.y - track.wrist.y - track.velocity.y * seconds,
      );
      if (distance > MAX_MATCH_DISTANCE) continue;
      const identityCost = observation.handedness && track.handedness
        ? observation.handedness === track.handedness ? -0.08 : 0.12
        : 0;
      visit(index + 1, [...chosen, track], cost + distance + identityCost);
    }
    visit(index + 1, [...chosen, null], cost + 0.7);
  };
  visit(0, [], 0);
  return best;
}

/** Display-only state. Never feed these smoothed or held points to inference. */
export class TrackingDisplayFilter {
  private hands: HandTrack[] = [];
  private handFrameAt: number | null = null;
  private poseFrameAt: number | null = null;
  private pose: {
    seenAt: number;
    filter: LandmarkFilter;
    landmarks: readonly NormalizedLandmark[];
  } | null = null;

  reset(): void {
    this.hands = [];
    this.pose = null;
    this.handFrameAt = null;
    this.poseFrameAt = null;
  }

  update(
    hands: readonly (readonly NormalizedLandmark[])[],
    timestamp: number,
    options: { handedness?: readonly (string | null)[]; pose?: readonly NormalizedLandmark[] | null } = {},
  ): void {
    if (!Number.isFinite(timestamp)) { this.reset(); return; }
    if (this.handFrameAt !== null && timestamp < this.handFrameAt) this.reset();
    if (timestamp === this.handFrameAt) return;
    this.hands = this.hands.filter((track) => timestamp - track.seenAt < HOLD_MS);
    const observations = hands.flatMap((landmarks, index): HandObservation[] => {
      if (!validPoints(landmarks, 21)) return [];
      const label = options.handedness?.[index];
      return [{ landmarks, handedness: label === "Left" || label === "Right" ? label : null }];
    }).slice(0, 2);
    const matches = matchHands(observations, this.hands, timestamp);
    const matched = new Set(matches.filter((track) => track !== null));
    observations.forEach((observation, index) => {
      let track = matches[index];
      const wrist = observation.landmarks[0];
      if (track) {
        const seconds = (timestamp - track.seenAt) / 1000;
        const dx = (wrist.x - track.wrist.x) / seconds;
        const dy = (wrist.y - track.wrist.y) / seconds;
        const scale = Math.min(1, 6 / Math.max(Math.hypot(dx, dy), 0.001));
        track.velocity = { x: dx * scale, y: dy * scale };
        track.handedness ??= observation.handedness;
      } else {
        if (this.hands.length === 2) {
          const replace = this.hands.filter((item) => !matched.has(item))
            .sort((left, right) => left.seenAt - right.seenAt)[0];
          this.hands = this.hands.filter((item) => item !== replace);
        }
        const preferredId = observation.handedness === "Right" ? 1 : 0;
        const id = this.hands.some((item) => item.id === preferredId) ? 1 - preferredId : preferredId;
        track = {
          id, handedness: observation.handedness, seenAt: timestamp,
          wrist: { x: wrist.x, y: wrist.y }, velocity: { x: 0, y: 0 },
          filter: new LandmarkFilter(observation.landmarks, timestamp), landmarks: [],
        };
        this.hands.push(track);
        matched.add(track);
      }
      track.landmarks = track.filter.update(observation.landmarks, timestamp);
      track.wrist = { x: wrist.x, y: wrist.y };
      track.seenAt = timestamp;
    });
    this.handFrameAt = timestamp;

    if (options.pose !== undefined) {
      this.poseFrameAt = timestamp;
      if (options.pose && validPoints(options.pose, 33) && isUsableUpperBodyPose(options.pose)) {
        if (!this.pose || timestamp - this.pose.seenAt >= HOLD_MS) {
          this.pose = { seenAt: timestamp, filter: new LandmarkFilter(options.pose, timestamp), landmarks: [] };
        }
        this.pose.landmarks = this.pose.filter.update(options.pose, timestamp);
        this.pose.seenAt = timestamp;
      }
    }
  }

  read(timestamp: number): TrackingDisplayFrame {
    if (!Number.isFinite(timestamp)) return { hands: [], pose: null };
    // Video-frame and animation-frame callbacks can have slightly different clocks.
    const at = Math.max(timestamp, this.handFrameAt ?? timestamp);
    const opacity = (seenAt: number, held: boolean) => held
      ? 0.65 * Math.max(0, 1 - (at - seenAt) / HOLD_MS)
      : Math.min(1, Math.max(0, (HOLD_MS - (at - seenAt)) / (HOLD_MS - FULL_OPACITY_MS)));
    const hands = this.hands.filter((track) => at - track.seenAt < HOLD_MS)
      .sort((left, right) => left.id - right.id)
      .map((track) => ({
        id: track.id, landmarks: track.landmarks,
        held: track.seenAt !== this.handFrameAt,
        opacity: opacity(track.seenAt, track.seenAt !== this.handFrameAt),
      }));
    const pose = this.pose && at - this.pose.seenAt < HOLD_MS
      ? { landmarks: this.pose.landmarks, opacity: opacity(this.pose.seenAt, this.pose.seenAt !== this.poseFrameAt) }
      : null;
    return { hands, pose };
  }
}
