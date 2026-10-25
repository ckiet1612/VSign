// Usage reports: see contracts/v1/usage.py. One aggregated summary per conversation, counts and word labels only.

export interface ConversationSummaryRequest {
  id: string; started_at: string; ended_at: string;
  channel: "counter" | "same_screen"; display_id: string | null;
  words: number; uncertain: number; failed: number;
  staff_undos: number; customer_undos: number; replies: number; voice_replies: number;
  labels: Record<string, number>; undone_labels: Record<string, number>;
}

export interface UsageLabelCount { label: string; count: number }

export interface UsageReportResponse {
  api_version: "1";
  workspace_id: string;
  generated_at: string;
  timezone: "Asia/Ho_Chi_Minh";
  days: 7 | 30 | 90;
  start_date: string;
  totals: {
    conversations: number; counter_conversations: number; words: number; avg_words: number; avg_duration_seconds: number;
    replies: number; voice_replies: number; uncertain: number; failed: number; undos: number; customer_undos: number;
    unhandled_conversations: number;
  };
  daily: Array<{ date: string; conversations: number; words: number; unhandled: number }>;
  scenarios: Array<{ id: string; label: string; conversations: number; words: number }>;
  top_words: UsageLabelCount[];
  unhandled: { no_word: number; mostly_unclear: number; undone_labels: UsageLabelCount[] };
}
