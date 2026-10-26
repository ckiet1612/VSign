import { useCallback, useEffect, useRef, useState } from "react";
import type {
  AuthSessionResponse,
  AuthenticatedUser,
  WorkspaceCapabilities,
  WorkspaceCapabilitiesResponse,
  WorkspaceContextResponse,
  WorkspaceAuditEvent,
  WorkspaceMemberResponse,
  WorkspaceAuditPageResponse,
} from "@workspace-contracts";
import { workspaceRequest, WorkspaceApiError } from "../lib/workspaceApi";
import { clearViewCache } from "../lib/viewCache";
import { workspaceHref } from "../lib/appRoutes";

interface PlatformState {
  loading: boolean;
  submitting: boolean;
  available: boolean;
  authRequired: boolean;
  authMode: "session" | "local_admin";
  context: WorkspaceContextResponse | null;
  capabilities: WorkspaceCapabilities | null;
  user: AuthenticatedUser | null;
  error: string;
  members: WorkspaceMemberResponse[] | null;
  auditEvents: WorkspaceAuditEvent[] | null;
}

const initialState: PlatformState = {
  loading: true,
  submitting: false,
  available: false,
  authRequired: false,
  authMode: "session",
  context: null,
  capabilities: null,
  user: null,
  error: "",
  members: null,
  auditEvents: null,
};

function isContext(value: unknown): value is WorkspaceContextResponse {
  if (!value || typeof value !== "object") return false;
  const record = value as Record<string, unknown>;
  return record.api_version === "1" && typeof record.workspace_id === "string" &&
    typeof record.name === "string" && (record.environment === "development" || record.environment === "production") &&
    typeof record.auth_required === "boolean";
}

function isCapabilities(value: unknown): value is WorkspaceCapabilitiesResponse {
  if (!value || typeof value !== "object") return false;
  const record = value as Record<string, unknown>;
  if (record.api_version !== "1" || typeof record.workspace_id !== "string" ||
      !record.capabilities || typeof record.capabilities !== "object") return false;
  const flags = record.capabilities as Record<string, unknown>;
  return ["overview", "recognize", "data", "evaluation", "monitoring", "models", "activity", "reports", "integrations", "team", "settings"]
    .every(key => typeof flags[key] === "boolean");
}

function isUser(value: unknown): value is AuthenticatedUser {
  if (!value || typeof value !== "object") return false;
  const record = value as Record<string, unknown>;
  return typeof record.id === "string" && typeof record.email === "string" &&
    typeof record.display_name === "string" &&
    ["owner", "admin", "operator", "reviewer", "viewer", "model_admin", "system_admin"].includes(String(record.role));
}

export function useWorkspacePlatform(platformUrl: string, enabled = true) {
  const [state, setState] = useState<PlatformState>(() => enabled ? initialState : { ...initialState, loading: false });
  const mountedRef = useRef(true);
  const controllerRef = useRef<AbortController | null>(null);
  const localLockRef = useRef(false);
  const loggingOutRef = useRef(false);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      controllerRef.current?.abort();
    };
  }, []);

  const load = useCallback(async (): Promise<boolean> => {
    if (localLockRef.current || loggingOutRef.current) return false;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const timeout = window.setTimeout(() => controller.abort(), 8000);
    const isCurrent = () => mountedRef.current && controllerRef.current === controller;
    try {
      const contextResponse = await workspaceRequest<WorkspaceContextResponse>(platformUrl, "/api/v1/workspace", {}, controller.signal);
      if (!isContext(contextResponse.body)) throw new Error("workspace contract unavailable");
      const context = contextResponse.body;
      const capabilitiesResponse = await workspaceRequest<WorkspaceCapabilitiesResponse>(platformUrl, "/api/v1/workspace/capabilities", {}, controller.signal);
      if (!isCapabilities(capabilitiesResponse.body)) throw new Error("capabilities contract unavailable");
      if (capabilitiesResponse.body.workspace_id !== context.workspace_id) throw new Error("workspace mismatch");

      let user: AuthenticatedUser | null = null;
      let authMode: "session" | "local_admin" = "session";
      try {
        const meResponse = await workspaceRequest<AuthSessionResponse>(platformUrl, "/api/v1/auth/me", {}, controller.signal);
        if (!meResponse.body || meResponse.body.authenticated !== true || !isUser(meResponse.body.user)) throw new Error("session contract unavailable");
        if (meResponse.body.auth_mode !== undefined && !["session", "local_admin"].includes(meResponse.body.auth_mode)) throw new Error("auth mode unavailable");
        user = meResponse.body.user;
        authMode = meResponse.body.auth_mode ?? "session";
      } catch (error) {
        if (!(error instanceof WorkspaceApiError && error.status === 401)) throw error;
      }
      if (!isCurrent() || controller.signal.aborted) return false;
      const authRequired = context.auth_required && user === null;
      setState({
        loading: false,
        submitting: false,
        available: true,
        authRequired,
        authMode,
        context,
        capabilities: capabilitiesResponse.body.capabilities,
        user,
        error: "",
        members: null,
        auditEvents: null,
      });
      return !authRequired;
    } catch (error) {
      if (!isCurrent()) return false;
      if (error instanceof WorkspaceApiError && error.status === 401) {
        setState(current => ({ ...current, loading: false, available: false, user: null, capabilities: null, authRequired: true, error: "" }));
        return false;
      }
      if (error instanceof WorkspaceApiError && error.status === 404) {
        setState(current => current.context?.auth_required || current.authRequired
          ? { ...current, loading: false, available: false, user: null, capabilities: null, error: "Không thể tải workspace. Vui lòng thử lại." }
          : { ...initialState, loading: false });
        return false;
      }
      setState(current => ({ ...current, loading: false, available: false, user: null, capabilities: null,
        error: "Không thể tải workspace. Vui lòng thử lại." }));
      return false;
    } finally {
      window.clearTimeout(timeout);
    }
  }, [platformUrl]);

  useEffect(() => {
    if (!enabled) return;
    void load();
    return () => controllerRef.current?.abort();
  }, [enabled, load]);

  useEffect(() => {
    if (!enabled) return;
    const refresh = () => { if (document.visibilityState === "visible") void load(); };
    const interval = window.setInterval(refresh, 60000);
    window.addEventListener("focus", refresh);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener("focus", refresh);
    };
  }, [enabled, load]);

  const login = useCallback(async (email: string, password: string) => {
    if (loggingOutRef.current) throw new Error("Đang đăng xuất. Vui lòng thử lại.");
    if (mountedRef.current) setState(current => ({ ...current, submitting: true, error: "" }));
    try {
      const response = await workspaceRequest<AuthSessionResponse>(platformUrl, "/api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!response.body || !isUser(response.body.user)) throw new Error("Phản hồi đăng nhập không hợp lệ");
      localLockRef.current = false;
      const loaded = await load();
      if (!loaded) throw new Error("Không thể tải workspace sau khi đăng nhập");
    } finally {
      if (mountedRef.current) setState(current => ({ ...current, submitting: false }));
    }
  }, [load, platformUrl]);

  const loadMembers = useCallback(async () => {
    try {
      const response = await workspaceRequest<{ members?: WorkspaceMemberResponse[] }>(platformUrl, "/api/v1/workspace/members");
      if (!response.body || !Array.isArray(response.body.members)) throw new Error("members contract unavailable");
      const members = response.body.members;
      if (mountedRef.current) setState(current => ({ ...current, members }));
    } catch (error) {
      if (mountedRef.current && error instanceof WorkspaceApiError && error.status === 401) {
        setState(current => ({ ...current, user: null, members: null, authRequired: true }));
      }
      throw error;
    }
  }, [platformUrl]);

  const loadAudit = useCallback(async () => {
    try {
      const response = await workspaceRequest<WorkspaceAuditPageResponse>(platformUrl, "/api/v1/workspace/audit/events?limit=50");
      if (!response.body || !Array.isArray(response.body.events)) throw new Error("audit contract unavailable");
      if (mountedRef.current) setState(current => ({ ...current, auditEvents: response.body!.events }));
    } catch (error) {
      if (mountedRef.current && error instanceof WorkspaceApiError && error.status === 401) {
        setState(current => ({ ...current, user: null, auditEvents: null, authRequired: true }));
      }
      throw error;
    }
  }, [platformUrl]);

  const logout = useCallback(async () => {
    if (loggingOutRef.current) return;
    loggingOutRef.current = true;
    localLockRef.current = true;
    controllerRef.current?.abort();
    controllerRef.current = null;
    // Cached tab contents belong to the session that read them.
    clearViewCache();
    window.history.replaceState(window.history.state, "", workspaceHref());
    if (mountedRef.current) setState(current => ({ ...current, user: null, capabilities: null,
      members: null, auditEvents: null, available: false, authRequired: true, submitting: true, error: "" }));
    const controller = new AbortController();
    let timer = 0;
    let serverConfirmed = false;
    let error = "";
    try {
      await Promise.race([
        workspaceRequest(platformUrl, "/api/v1/auth/logout", { method: "POST" }, controller.signal),
        new Promise<never>((_resolve, reject) => { timer = window.setTimeout(() => {
          controller.abort(); reject(new Error("logout_timeout"));
        }, 8000); }),
      ]);
      serverConfirmed = true;
    } catch (logoutError) {
      // A 401 means the server has already discarded this session. For a network
      // failure, lock the local UI immediately instead of leaving private data open.
      if (!(logoutError instanceof WorkspaceApiError && logoutError.status === 401)) {
        error = "Đã khóa phiên trên giao diện, nhưng máy chủ chưa xác nhận đăng xuất.";
      } else {
        serverConfirmed = true;
      }
    } finally {
      window.clearTimeout(timer);
      loggingOutRef.current = false;
    }
    if (!mountedRef.current) return;
    setState(current => ({
      ...current,
      user: null,
      capabilities: null,
      members: null,
      auditEvents: null,
      available: false,
      submitting: false,
      authRequired: serverConfirmed ? (current.context?.auth_required ?? true) : true,
      error,
    }));
    if (serverConfirmed) {
      localLockRef.current = false;
      await load();
    }
  }, [load, platformUrl]);

  return { ...state, login, logout, reload: load, loadMembers, loadAudit };
}
