import type { CollectionHandCounts } from "@contracts";
import plan from "../v5CollectionTargets.json";

interface V5CollectionPlan {
  targetPerLabel: number;
  excludedPublicSplits: string[];
  targets: Record<string, CollectionHandCounts>;
}

const collectionPlan = plan as V5CollectionPlan;

export const V5_TARGET_PER_LABEL = collectionPlan.targetPerLabel;

export function v5CollectionTargetsFor(
  label: string,
  fallbackPerHand: number,
): CollectionHandCounts {
  const target = collectionPlan.targets[label];
  if (!target) return { right: fallbackPerHand, left: fallbackPerHand };
  return { right: target.right, left: target.left };
}
