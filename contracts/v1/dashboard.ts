export interface DashboardResponse {
  api_version: "1";
  workspace_id: string;
  generated_at: string;
  timezone: "UTC";
  days: 7 | 30 | 90;
  start_date: string;
  totals: { samples: number; datasets_draft: number; datasets_sealed: number; models: number; evaluations: number };
  period: { samples: number; evaluations: number; events: number };
  daily_samples: Array<{ date: string; count: number }>;
  label_progress: Array<{ label: string; count: number; target: number }>;
  workers: Record<"deployment" | "evaluation" | "integration", "online" | "offline" | "not_configured">;
  recent_activity: Array<{ id: string; event_type: string; outcome: string; occurred_at: string }>;
  recent_evaluations: Array<{ id: string; model_version: string; status: string; progress: number; created_at: string }>;
}
