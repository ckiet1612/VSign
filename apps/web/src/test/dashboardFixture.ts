import type { DashboardResponse } from "../../../../contracts/v1/dashboard";

export function dashboardFixture(days: 7 | 30 | 90 = 7): DashboardResponse {
  const end = Date.UTC(2026, 9, 18);
  return { api_version: "1", workspace_id: "local", timezone: "UTC", days,
    generated_at: "2026-10-18T12:00:00Z", start_date: new Date(end - (days - 1) * 86400000).toISOString().slice(0, 10),
    totals: { samples: 128, datasets_draft: 2, datasets_sealed: 1, models: 3, evaluations: 5 },
    period: { samples: 12, evaluations: 1, events: 3 },
    daily_samples: Array.from({ length: days }, (_, i) => ({ date: new Date(end - (days - 1 - i) * 86400000).toISOString().slice(0, 10), count: i === days - 1 ? 12 : 0 })),
    label_progress: [{ label: "Chào", count: 128, target: 200 }, { label: "Mua", count: 0, target: 100 }],
    workers: { deployment: "offline", evaluation: "not_configured", integration: "online" },
    recent_activity: [{ id: "event", event_type: "model.registered", outcome: "success", occurred_at: "2026-10-18T11:00:00Z" }],
    recent_evaluations: [{ id: "run", model_version: "candidate-v1", status: "completed", progress: 100, created_at: "2026-10-18T11:00:00Z" }] };
}
