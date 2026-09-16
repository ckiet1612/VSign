import type { NormalizedLandmark } from "@mediapipe/tasks-vision";

export const LANDMARK_SEQUENCE_LENGTH = 16;
export const MAX_LANDMARK_HANDS = 2;
export const LANDMARKS_PER_HAND = 21;
export const COORDINATES_PER_LANDMARK = 3;
export const FEATURES_PER_HAND = LANDMARKS_PER_HAND * COORDINATES_PER_LANDMARK;
export const HAND_SHAPE_OFFSET = 0;
export const HAND_GLOBAL_OFFSET = MAX_LANDMARK_HANDS * FEATURES_PER_HAND;
export const POSE_SOURCE_INDICES = [0, 2, 5, 9, 10, 11, 12, 13, 14, 15, 16] as const;
export const POSE_LANDMARK_COUNT = POSE_SOURCE_INDICES.length;
export const POSE_COORDINATE_OFFSET = HAND_GLOBAL_OFFSET + MAX_LANDMARK_HANDS * 3;
export const PAIR_GEOMETRY_OFFSET = POSE_COORDINATE_OFFSET + POSE_LANDMARK_COUNT * 3;
export const PAIR_PRESENCE_OFFSET = PAIR_GEOMETRY_OFFSET + 4;
export const HAND_PRESENCE_OFFSET = PAIR_PRESENCE_OFFSET + 1;
export const POSE_PRESENCE_OFFSET = HAND_PRESENCE_OFFSET + MAX_LANDMARK_HANDS;
export const LANDMARK_FEATURE_DIM = POSE_PRESENCE_OFFSET + POSE_LANDMARK_COUNT;

const LEFT_SHOULDER = 11;
const RIGHT_SHOULDER = 12;
const LEFT_WRIST = 15;
const RIGHT_WRIST = 16;
const VISIBILITY_THRESHOLD = 0.35;
type HandSlot = readonly NormalizedLandmark[] | null;

function distance2D(left: NormalizedLandmark, right: NormalizedLandmark): number {
  return Math.hypot(left.x - right.x, left.y - right.y);
}

function isVisible(point: NormalizedLandmark | undefined): point is NormalizedLandmark {
  return Boolean(
    point && Number.isFinite(point.x) && Number.isFinite(point.y) &&
      Number.isFinite(point.z) && (point.visibility ?? 1) >= VISIBILITY_THRESHOLD,
  );
}

export function isUsableUpperBodyPose(
  pose: readonly NormalizedLandmark[] | null,
): pose is readonly NormalizedLandmark[] {
  if (pose?.length !== 33) return false;
  const nose = pose[0];
  const leftShoulder = pose[LEFT_SHOULDER];
  const rightShoulder = pose[RIGHT_SHOULDER];
  if (!isVisible(nose) || !isVisible(leftShoulder) || !isVisible(rightShoulder)) {
    return false;
  }
  const centerY = (leftShoulder.y + rightShoulder.y) / 2;
  const width = distance2D(leftShoulder, rightShoulder);
  return width >= 0.08 && width <= 0.75 && centerY < 0.82 && nose.y < centerY - 0.03;
}

function assignHandsToPose(
  hands: readonly (readonly NormalizedLandmark[])[],
  pose: readonly NormalizedLandmark[] | null,
): [HandSlot, HandSlot] {
  const valid = hands.filter((hand) => hand.length === LANDMARKS_PER_HAND).slice(0, 2);
  if (!valid.length) return [null, null];
  const leftWrist = pose?.[LEFT_WRIST];
  const rightWrist = pose?.[RIGHT_WRIST];
  if (isVisible(leftWrist) && isVisible(rightWrist)) {
    if (valid.length === 1) {
      return distance2D(valid[0][0], leftWrist) <= distance2D(valid[0][0], rightWrist)
        ? [valid[0], null]
        : [null, valid[0]];
    }
    const direct = distance2D(valid[0][0], leftWrist) + distance2D(valid[1][0], rightWrist);
    const crossed = distance2D(valid[0][0], rightWrist) + distance2D(valid[1][0], leftWrist);
    return direct <= crossed ? [valid[0], valid[1]] : [valid[1], valid[0]];
  }
  const ordered = [...valid].sort((left, right) => left[0].x - right[0].x);
  return [ordered[0] ?? null, ordered[1] ?? null];
}

function clipped(value: number): number {
  return Math.max(-4, Math.min(4, value));
}

export function packLandmarkFrame(
  hands: readonly (readonly NormalizedLandmark[])[],
  pose: readonly NormalizedLandmark[] | null,
): number[] | null {
  const validPose = isUsableUpperBodyPose(pose) ? pose : null;
  const slots = assignHandsToPose(hands, validPose);
  const packed = new Array<number>(LANDMARK_FEATURE_DIM).fill(0);
  const leftShoulder = validPose?.[LEFT_SHOULDER];
  const rightShoulder = validPose?.[RIGHT_SHOULDER];
  const shouldersVisible = isVisible(leftShoulder) && isVisible(rightShoulder);
  const shoulderCenter = shouldersVisible
    ? [
        (leftShoulder.x + rightShoulder.x) / 2,
        (leftShoulder.y + rightShoulder.y) / 2,
        (leftShoulder.z + rightShoulder.z) / 2,
      ]
    : [0, 0, 0];
  const shoulderWidth = shouldersVisible
    ? Math.max(distance2D(leftShoulder, rightShoulder), 0.05)
    : 1;

  slots.forEach((hand, handIndex) => {
    if (!hand) return;
    const wrist = hand[0];
    const palmScale = Math.max(distance2D(wrist, hand[9]), 0.025);
    hand.forEach((point, pointIndex) => {
      const offset = handIndex * FEATURES_PER_HAND + pointIndex * 3;
      packed[offset] = clipped((point.x - wrist.x) / palmScale);
      packed[offset + 1] = clipped((point.y - wrist.y) / palmScale);
      packed[offset + 2] = clipped((point.z - wrist.z) / palmScale);
    });
    packed[HAND_PRESENCE_OFFSET + handIndex] = 1;
    if (shouldersVisible) {
      const offset = HAND_GLOBAL_OFFSET + handIndex * 3;
      packed[offset] = clipped((wrist.x - shoulderCenter[0]) / shoulderWidth);
      packed[offset + 1] = clipped((wrist.y - shoulderCenter[1]) / shoulderWidth);
      packed[offset + 2] = clipped((wrist.z - shoulderCenter[2]) / shoulderWidth);
    }
  });

  if (shouldersVisible && validPose) {
    POSE_SOURCE_INDICES.forEach((sourceIndex, poseIndex) => {
      const point = validPose[sourceIndex];
      if (!isVisible(point)) return;
      const offset = POSE_COORDINATE_OFFSET + poseIndex * 3;
      packed[offset] = clipped((point.x - shoulderCenter[0]) / shoulderWidth);
      packed[offset + 1] = clipped((point.y - shoulderCenter[1]) / shoulderWidth);
      packed[offset + 2] = clipped((point.z - shoulderCenter[2]) / shoulderWidth);
      packed[POSE_PRESENCE_OFFSET + poseIndex] = 1;
    });
  }
  setPairGeometry(packed);
  return hasLandmarks(packed) ? packed : null;
}

function setPairGeometry(frame: number[]): void {
  frame.fill(0, PAIR_GEOMETRY_OFFSET, PAIR_PRESENCE_OFFSET + 1);
  const shouldersAvailable =
    frame[POSE_PRESENCE_OFFSET + 5] > 0.5 &&
    frame[POSE_PRESENCE_OFFSET + 6] > 0.5;
  const wrists: ([number, number, number] | null)[] = [null, null];
  [9, 10].forEach((poseWristIndex, handIndex) => {
    if (shouldersAvailable && frame[HAND_PRESENCE_OFFSET + handIndex] > 0.5) {
      const offset = HAND_GLOBAL_OFFSET + handIndex * 3;
      wrists[handIndex] = [frame[offset], frame[offset + 1], frame[offset + 2]];
      return;
    }
    if (frame[POSE_PRESENCE_OFFSET + poseWristIndex] > 0.5) {
      const offset = POSE_COORDINATE_OFFSET + poseWristIndex * 3;
      wrists[handIndex] = [frame[offset], frame[offset + 1], frame[offset + 2]];
    }
  });
  if (!wrists[0] || !wrists[1]) return;
  const delta = wrists[1].map((value, axis) => value - wrists[0]![axis]);
  frame[PAIR_GEOMETRY_OFFSET] = Math.max(-8, Math.min(8, delta[0]));
  frame[PAIR_GEOMETRY_OFFSET + 1] = Math.max(-8, Math.min(8, delta[1]));
  frame[PAIR_GEOMETRY_OFFSET + 2] = Math.max(-8, Math.min(8, delta[2]));
  frame[PAIR_GEOMETRY_OFFSET + 3] = Math.min(Math.hypot(...delta), 8);
  frame[PAIR_PRESENCE_OFFSET] = 1;
}

function swapRanges(values: number[], first: number, second: number, length: number) {
  const left = values.slice(first, first + length);
  const right = values.slice(second, second + length);
  values.splice(first, length, ...right);
  values.splice(second, length, ...left);
}

export function mirrorLandmarkFrame(frame: readonly number[]): number[] {
  if (frame.length !== LANDMARK_FEATURE_DIM) {
    throw new Error(`Frame phải có ${LANDMARK_FEATURE_DIM} đặc trưng V4.`);
  }
  const output = Array.from(frame);
  for (let hand = 0; hand < 2; hand += 1) {
    for (let point = 0; point < 21; point += 1) {
      output[hand * FEATURES_PER_HAND + point * 3] *= -1;
    }
    output[HAND_GLOBAL_OFFSET + hand * 3] *= -1;
  }
  swapRanges(output, 0, FEATURES_PER_HAND, FEATURES_PER_HAND);
  swapRanges(output, HAND_GLOBAL_OFFSET, HAND_GLOBAL_OFFSET + 3, 3);
  [output[HAND_PRESENCE_OFFSET], output[HAND_PRESENCE_OFFSET + 1]] = [
    output[HAND_PRESENCE_OFFSET + 1], output[HAND_PRESENCE_OFFSET],
  ];
  for (let poseIndex = 0; poseIndex < POSE_LANDMARK_COUNT; poseIndex += 1) {
    output[POSE_COORDINATE_OFFSET + poseIndex * 3] *= -1;
  }
  for (const [left, right] of [[1, 2], [3, 4], [5, 6], [7, 8], [9, 10]] as const) {
    swapRanges(output, POSE_COORDINATE_OFFSET + left * 3, POSE_COORDINATE_OFFSET + right * 3, 3);
    [output[POSE_PRESENCE_OFFSET + left], output[POSE_PRESENCE_OFFSET + right]] = [
      output[POSE_PRESENCE_OFFSET + right], output[POSE_PRESENCE_OFFSET + left],
    ];
  }
  output[PAIR_GEOMETRY_OFFSET + 1] *= -1;
  output[PAIR_GEOMETRY_OFFSET + 2] *= -1;
  return output;
}

export function emptyLandmarkFrame(): number[] {
  return new Array<number>(LANDMARK_FEATURE_DIM).fill(0);
}

export function hasHandLandmarks(frame: readonly number[]): boolean {
  if (frame.length !== LANDMARK_FEATURE_DIM) return false;
  return (
    frame[HAND_PRESENCE_OFFSET] > 0.5 ||
    frame[HAND_PRESENCE_OFFSET + 1] > 0.5
  );
}

export function hasLandmarks(frame: readonly number[]): boolean {
  if (frame.length !== LANDMARK_FEATURE_DIM) return false;
  const hands = frame.slice(HAND_PRESENCE_OFFSET, POSE_PRESENCE_OFFSET);
  const upperBody = frame.slice(POSE_PRESENCE_OFFSET + 5);
  return Math.max(...hands, ...upperBody) > 0.5;
}
