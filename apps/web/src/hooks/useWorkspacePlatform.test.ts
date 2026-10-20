import { act, renderHook, waitFor } from "@testing-library/react";
import { StrictMode, createElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useWorkspacePlatform } from "./useWorkspacePlatform";

const context = {
  api_version: "1",
  workspace_id: "local",
  name: "VSign workspace",
  environment: "production",
  scope_source: "local-config",
  auth_required: true,
};
const capabilities = {
  api_version: "1",
  workspace_id: "local",
  capabilities: {
    overview: true, recognize: true, data: true, evaluation: false, monitoring: false,
    models: false, activity: true, integrations: false, team: true, settings: false,
  },
};
const user = { id: "user-1", email: "admin@example.com", display_name: "Admin", role: "owner" };

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("useWorkspacePlatform", () => {
  it("uses the backend local admin identity without a login request", async () => {
    const admin = { ...user, role: "admin" };
    vi.stubGlobal("fetch", async (url: string) => new Response(JSON.stringify(
      url.endsWith("/auth/me") ? { authenticated: true, auth_mode: "local_admin", user: admin }
        : url.endsWith("/capabilities") ? capabilities : { ...context, auth_required: false },
    )));
    const { result } = renderHook(() => useWorkspacePlatform("http://localhost:8000"));
    await waitFor(() => expect(result.current.user).toEqual(admin));
    expect(result.current.authMode).toBe("local_admin");
    expect(result.current.authRequired).toBe(false);
  });

  it("restores the existing session through auth/me", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(context)))
      .mockResolvedValueOnce(new Response(JSON.stringify(capabilities)))
      .mockResolvedValueOnce(new Response(JSON.stringify({ authenticated: true, user })));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useWorkspacePlatform("http://localhost:8000"));

    await waitFor(() => expect(result.current.user?.email).toBe("admin@example.com"));
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/v1/auth/me", expect.objectContaining({ credentials: "include" }));
    expect(result.current.authRequired).toBe(false);
  });

  it("exposes a submitting state and keeps the gate active if refresh fails", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ user }), { status: 200 }))
      .mockResolvedValueOnce(new Response(null, { status: 503 }));
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useWorkspacePlatform("http://localhost:8000"));
    await waitFor(() => expect(result.current.authRequired).toBe(true));

    let login!: Promise<void>;
    act(() => { login = result.current.login("admin@example.com", "password"); });
    expect(result.current.submitting).toBe(true);
    await expect(login).rejects.toThrow();
    expect(result.current.authRequired).toBe(true);
    await waitFor(() => expect(result.current.submitting).toBe(false));
  });

  it("does not update state after unmount when a request resolves late", async () => {
    let resolve!: (value: Response) => void;
    vi.stubGlobal("fetch", () => new Promise<Response>(complete => { resolve = complete; }));
    const { result, unmount } = renderHook(() => useWorkspacePlatform("http://localhost:8000"));
    unmount();
    resolve(new Response(JSON.stringify(context)));
    await Promise.resolve();
    expect(result.current.loading).toBe(true);
  });

  it("still finishes loading when StrictMode replays effects", async () => {
    vi.stubGlobal("fetch", async (url: string) => new Response(JSON.stringify(
      url.endsWith("/auth/me") ? { authenticated: true, user } : url.endsWith("/capabilities") ? capabilities : context,
    )));
    const { result } = renderHook(() => useWorkspacePlatform("http://localhost:8000"), {
      wrapper: ({ children }) => createElement(StrictMode, null, children),
    });
    await waitFor(() => expect(result.current.user).toEqual(user));
  });

  it("clears the authenticated user when the session expires", async () => {
    let expired = false;
    vi.stubGlobal("fetch", async (url: string) => expired
      ? new Response(null, { status: 401 })
      : new Response(JSON.stringify(url.endsWith("/auth/me") ? { authenticated: true, user } : url.endsWith("/capabilities") ? capabilities : context)));
    const { result } = renderHook(() => useWorkspacePlatform("http://localhost:8000"));
    await waitFor(() => expect(result.current.user).toEqual(user));
    expired = true;
    await act(async () => { await result.current.reload(); });
    expect(result.current.user).toBeNull();
    expect(result.current.authRequired).toBe(true);
  });

  it("clears local authentication state when logout cannot reach the backend", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith("/auth/logout")) throw new Error("offline");
      return new Response(JSON.stringify(
        url.endsWith("/auth/me") ? { authenticated: true, user } : url.endsWith("/capabilities") ? capabilities : context,
      ));
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useWorkspacePlatform("http://localhost:8000"));
    await waitFor(() => expect(result.current.user).toEqual(user));

    await act(async () => { await result.current.logout(); });

    expect(result.current.user).toBeNull();
    expect(result.current.authRequired).toBe(true);
  });

  it("locks locally before awaiting logout and does not restore an unconfirmed session", async () => {
    const fetcher=vi.fn(async (url:string) => url.endsWith('/auth/logout') ? new Promise<Response>(()=>{}) : new Response(JSON.stringify(
      url.endsWith('/auth/me') ? {authenticated:true,user} : url.endsWith('/capabilities') ? capabilities : context,
    )));
    vi.stubGlobal('fetch',fetcher);
    const {result}=renderHook(()=>useWorkspacePlatform('http://localhost:8000'));
    await waitFor(()=>expect(result.current.user).toEqual(user));
    vi.useFakeTimers();
    let logout!:Promise<void>;
    act(()=>{logout=result.current.logout();});
    expect(result.current.user).toBeNull();
    expect(result.current.submitting).toBe(true);
    await act(async()=>{await result.current.reload();});
    expect(result.current.user).toBeNull();
    await act(async()=>{await vi.advanceTimersByTimeAsync(8000);await logout;});
    expect(result.current.submitting).toBe(false);
    expect(result.current.authRequired).toBe(true);
    expect(result.current.error).toMatch(/chưa xác nhận/);
    const reads=fetcher.mock.calls.length;
    await act(async()=>{await result.current.reload();});
    expect(fetcher.mock.calls.length).toBe(reads);
  });

  it("reports database failures instead of falling back to anonymous local capabilities", async () => {
    vi.stubGlobal("fetch", async () => new Response(null, { status: 503 }));
    const { result } = renderHook(() => useWorkspacePlatform("http://localhost:8000"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).not.toBe("");
    expect(result.current.capabilities).toBeNull();
  });

  it("rejects missing capability flags", async () => {
    vi.stubGlobal("fetch", async (url: string) => new Response(JSON.stringify(url.endsWith("/capabilities")
      ? { ...capabilities, capabilities: { overview: true } } : context)));
    const { result } = renderHook(() => useWorkspacePlatform("http://localhost:8000"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).not.toBe("");
    expect(result.current.capabilities).toBeNull();
  });
});
