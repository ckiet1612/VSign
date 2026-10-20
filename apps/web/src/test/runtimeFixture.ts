import type { InferenceMetadata } from "@contracts";

export const runtimeMetadata: InferenceMetadata = {
  backend: "coreml",
  model_version: "sales30-runtime-v1",
  protocol_version: "1.0",
  frame_count: 16,
  frame_width: 224,
  frame_height: 224,
  supported_image_formats: ["image/jpeg", "image/webp"],
  confidence_threshold: 0.7,
  margin_threshold: 0.15,
  labels: ["Chào", "Không ký hiệu"],
  collection_labels: ["Chào"],
  candidate_labels_unverified: false,
  mock: false,
  collection_enabled: false,
  collection_target_per_hand: 50,
  sentence_ai_enabled: false,
};

export const runtimeHealth = {
  status: "ok" as const,
  backend: "coreml",
  model_version: "sales30-runtime-v1",
  protocol_version: "1.0",
};

export const runtimeSnapshot = {
  endpoint: "http://localhost:8003",
  health: runtimeHealth,
  metadata: runtimeMetadata,
  healthError: "",
  metadataError: "",
  checkedAt: 1792029600000,
  lastHealthyAt: 1792029600000,
  metadataUpdatedAt: 1792029600000,
  healthLatencyMs: 12.5,
  checking: false,
};
