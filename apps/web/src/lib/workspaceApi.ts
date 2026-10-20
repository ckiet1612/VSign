export class WorkspaceApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "WorkspaceApiError";
    this.status = status;
  }
}

function rootUrl(value: string): string {
  return value.replace(/\/$/, "");
}

export async function workspaceRequest<T>(
  platformUrl: string,
  path: string,
  init: RequestInit = {},
  signal?: AbortSignal,
): Promise<{ body: T | null; status: number }> {
  const response = await fetch(`${rootUrl(platformUrl)}${path}`, {
    ...init,
    credentials: "include",
    signal,
  });
  let body: T | null = null;
  try {
    body = await response.json() as T;
  } catch {
    body = null;
  }
  if (!response.ok) {
    const detail = body && typeof body === "object" && body !== null && "detail" in body
      ? String((body as { detail?: unknown }).detail ?? "")
      : "Workspace unavailable";
    throw new WorkspaceApiError(response.status, detail);
  }
  return { body, status: response.status };
}
