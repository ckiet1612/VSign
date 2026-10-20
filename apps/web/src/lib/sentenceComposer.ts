import type { SentenceComposeResponse } from "@contracts";

type Fetcher = (
  input: string,
  init: RequestInit,
) => Promise<Pick<Response, "ok" | "json">>;

export async function composeSentence(
  inferenceHttpUrl: string,
  words: string[],
  fetcher: Fetcher = fetch,
  signal?: AbortSignal,
): Promise<SentenceComposeResponse> {
  const response = await fetcher(`${inferenceHttpUrl}/sentence/compose`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ words }),
    ...(signal ? { signal } : {}),
  });
  if (!response.ok) throw new Error("Máy chủ chưa thể hoàn thiện câu.");
  const payload: unknown = await response.json();
  if (
    typeof payload !== "object" ||
    payload === null ||
    typeof (payload as { sentence?: unknown }).sentence !== "string" ||
    !(payload as { sentence: string }).sentence.trim() ||
    ("warnings" in payload && (!Array.isArray(payload.warnings) ||
      !payload.warnings.every((warning: unknown) => typeof warning === "string")))
  ) {
    throw new Error("Câu hoàn thiện không hợp lệ.");
  }
  return payload as SentenceComposeResponse;
}
