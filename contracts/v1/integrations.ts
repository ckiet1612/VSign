export const integrationScopes = ['models:read','snapshots:read','evaluations:read'] as const;
export type IntegrationScope = typeof integrationScopes[number];
export const integrationEvents = ['collection.started','collection.paused','collection.resumed','collection.stopped','collection.completed',
  'data.snapshot_created','evaluation.requested','evaluation.started','evaluation.completed','evaluation.failed','evaluation.cancelled',
  'deployment.succeeded','deployment.failed'] as const;
export type IntegrationEvent = typeof integrationEvents[number];
export interface IntegrationKey {
  id:string;name:string;prefix:string;scopes:IntegrationScope[];requests_per_minute:number;
  created_at:string;expires_at:string;revoked_at:string|null;last_used_at:string|null;
}
export interface IntegrationWebhook {
  id:string;name:string;url:string;events:IntegrationEvent[];enabled:boolean;secret_version:number;created_at:string;
}
export interface IntegrationDelivery {
  id:string;webhook_id:string;event_id:string;event_type:string;
  status:'pending'|'sending'|'delivered'|'failed'|'cancelled';attempts:number;status_code:number|null;error:string|null;
  created_at:string;available_at:string;
}
export interface IntegrationLog {
  id:string;kind:'api'|'webhook';resource_id:string;action:string;status_code:number;duration_ms:number;attempt:number;error:string|null;created_at:string;
}
export interface WorkspaceIntegrations {
  api_version:'1';workspace_id:string;permissions:{manage:boolean};webhook_ready:boolean;worker_online:boolean;
  available_scopes:IntegrationScope[];available_events:IntegrationEvent[];
  limits:{key_per_minute:number;workspace_per_minute:number;webhook_per_minute:number;webhook_workspace_per_minute:number};
  keys:IntegrationKey[];webhooks:IntegrationWebhook[];deliveries:IntegrationDelivery[];
}
export interface IntegrationLogs {
  api_version:'1';workspace_id:string;logs:IntegrationLog[];next_cursor:string|null;
}
