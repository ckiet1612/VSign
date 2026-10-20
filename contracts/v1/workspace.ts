export const WORKSPACE_API_VERSION = "1" as const;

export type WorkspaceRole = "owner" | "admin" | "operator" | "reviewer" | "viewer";

export interface AuthLoginRequest {
  email: string;
  password: string;
}

export interface AuthenticatedUser {
  id: string;
  email: string;
  display_name: string;
  role: WorkspaceRole | "model_admin" | "system_admin";
}

export interface AuthSessionResponse {
  authenticated: true;
  auth_mode?: "session" | "local_admin";
  user: AuthenticatedUser;
}

export interface AuthLogoutResponse {
  authenticated: false;
}

export type WorkspaceEnvironment = "development" | "production";

export interface WorkspaceContextResponse {
  api_version: typeof WORKSPACE_API_VERSION;
  workspace_id: string;
  name: string;
  environment: WorkspaceEnvironment;
  scope_source: "local-config";
  auth_required: boolean;
}

export interface WorkspaceCapabilities {
  overview: boolean;
  recognize: boolean;
  data: boolean;
  evaluation: boolean;
  monitoring: boolean;
  models: boolean;
  activity: boolean;
  integrations: boolean;
  team: boolean;
  settings: boolean;
}

export interface WorkspaceCapabilitiesResponse {
  api_version: typeof WORKSPACE_API_VERSION;
  workspace_id: string;
  capabilities: WorkspaceCapabilities;
}

export interface WorkspaceMemberResponse {
  id: string;
  email: string;
  display_name: string;
  role: AuthenticatedUser["role"];
  active: boolean;
}

export interface WorkspaceMembersResponse {
  api_version: typeof WORKSPACE_API_VERSION;
  workspace_id: string;
  members: WorkspaceMemberResponse[];
}

export interface WorkspaceAuditEvent {
  event_id: string;
  workspace_id: string;
  event_type: string;
  actor_type: "system" | "user" | "service";
  actor_id: string | null;
  occurred_at: string;
  resource_type: string | null;
  resource_id: string | null;
  outcome: "success" | "failure";
  metadata: Record<string, unknown>;
}

export interface WorkspaceAuditPageResponse {
  api_version: typeof WORKSPACE_API_VERSION;
  workspace_id: string;
  events: WorkspaceAuditEvent[];
  next_cursor: string | null;
  has_more: boolean;
  source: "not_configured" | "store";
}

export interface WorkspaceClientEventRequest {
  event_id: string;
  event_type: "model.switched" | "collection.started" | "collection.paused" | "collection.resumed" |
    "collection.stopped" | "collection.completed" | "collection.sample_saved";
  resource_id: string;
  model_version: string;
  previous_model_version?: string;
  model_option?: "current" | "seated";
  previous_model_option?: "current" | "seated";
  capture_session_id?: string;
  saved_samples?: number;
  sample_id?: string;
  reason?: "manual" | "capture_error" | "save_error" | "navigation" | "camera_off" | "completed" | "context_changed";
}

export interface WorkspaceClientEventResponse {
  status: "recorded";
  event_id: string;
}
