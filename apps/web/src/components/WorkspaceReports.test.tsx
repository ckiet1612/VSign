import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { WorkspaceReports } from "./WorkspaceReports";

vi.mock("recharts", async original => {
  const actual = await original<typeof import("recharts")>();
  return { ...actual, ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div style={{ width: 600, height: 220 }}>{children}</div> };
});

const report = (days: number) => ({
  api_version: "1", workspace_id: "local", generated_at: "2026-10-23T05:00:00Z", timezone: "Asia/Ho_Chi_Minh", days,
  start_date: "2026-10-17",
  totals: { conversations: 8, counter_conversations: 5, words: 26, avg_words: 3.3, avg_duration_seconds: 75, replies: 9,
    voice_replies: 3, uncertain: 6, failed: 1, undos: 4, customer_undos: 2, unhandled_conversations: 2 },
  daily: Array.from({ length: days }, (_, index) => ({ date: `2026-10-${String(17 + index).padStart(2, "0")}`, conversations: index ? 1 : 2, words: 3, unhandled: 0 })),
  scenarios: [{ id: "product", label: "Tìm và hỏi sản phẩm", conversations: 6, words: 15 }],
  top_words: [{ label: "Mua", count: 6 }, { label: "Tivi", count: 3 }],
  unhandled: { no_word: 1, mostly_unclear: 1, undone_labels: [{ label: "Rẻ", count: 2 }] },
});

afterEach(() => vi.unstubAllGlobals());

it("shows usage, situations and the cases that did not work for the chosen period", async () => {
  const fetcher = vi.fn(async (url: string) => {
    const days = Number(new URL(url).searchParams.get("days"));
    return new Response(JSON.stringify(report(days === 30 ? 7 : days)));
  });
  vi.stubGlobal("fetch", fetcher);
  render(<WorkspaceReports platformUrl="http://localhost:8000" workspaceId="local" enabled />);
  // A 30-day request answered with 7 days of data is refused rather than shown.
  expect(await screen.findByRole("alert")).toHaveTextContent("Phản hồi báo cáo không hợp lệ.");
  fireEvent.click(screen.getByRole("radio", { name: "7 ngày" }));
  expect(await screen.findByText("Tìm và hỏi sản phẩm")).toBeInTheDocument();
  // 2 of 8 conversations did not work: 75% handled in the summary strip, 25% named on the cases card.
  const metric = (label: string) => screen.getAllByText(label).map(node => node.closest<HTMLElement>(".report-metric")).find(Boolean)!;
  expect(within(metric("Xử lý được")).getByText("75", { selector: ".sr-only" })).toBeInTheDocument();
  expect(screen.getByText("25% cuộc chưa xử lý tốt")).toBeInTheDocument();
  expect(within(metric("Câu trả lời của nhân viên")).getByText("3 câu nhập bằng giọng nói")).toBeInTheDocument();
  expect(screen.getByText("Rẻ")).toBeInTheDocument();
  expect(screen.getByText(/không chứa video/)).toBeInTheDocument();
  expect(fetcher).toHaveBeenLastCalledWith("http://localhost:8000/api/v1/workspace/usage/report?days=7", expect.anything());
});

it("explains a missing permission", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "no" }), { status: 403 })));
  render(<WorkspaceReports platformUrl="http://localhost:8000" workspaceId="local" enabled />);
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("không có quyền xem báo cáo"));
});
