# Workspace Integrations

Approved scope: enterprise owner/admin manage scoped read-only API keys, HTTPS
webhooks and subscriptions, shared rate limits and sanitized integration history.
Keep local admin and legacy recognition/collection unchanged. Never expose model
registration, approval, deploy, raw video or filesystem paths to API keys.

## Boundaries

Management: `/api/v1/workspace/integrations`. Machine reads:
`/api/v1/integrations/models`, `/snapshots`, `/evaluations`. Authentication is
explicit Bearer only on machine endpoints. Bearer on other platform endpoints
is rejected even in local-admin mode. Workspace comes from server settings and
persisted key, not request parameters. Scopes: models:read, snapshots:read,
evaluations:read. Keys: 256 random bits, hash only, display once, expiration and
revocation; a lost creation acknowledgement requires revoke and recreate.

Webhook signing keys require an operator Fernet key in
`INTEGRATION_ENCRYPTION_KEY`; ciphertext only in DB. No operator key means
creation/rotation fail closed, other functions remain available. HTTPS port443,
no credentials/query/fragment; reject nonpublic IPs and all nonpublic DNS
answers, connect to a validated IP with hostname TLS verification, no redirects
or proxies. Whole delivery subprocess has a 20-second deadline.

## Delivery

Audit insertion and fanout share one DB transaction via a session flush hook.
Only allowlisted server events, never browser_report or integration logs, fan
out to subscriptions existing at that time. Payload v1: stable event ID,
workspace, type, time, outcome, resource IDs; no arbitrary audit metadata.
Unique webhook/event pair, stable delivery ID, HMAC-SHA256 over timestamp + dot
+ canonical body. At-least-once: recipient deduplicates delivery ID and checks
timestamp. Independent process worker; SQLite immediate/Postgres workspace row
lock; claim fencing and60-second lease, max5 attempts, backoff15/60/300/900s.
Disable cancels pending work; in-flight network request cannot be recalled.
Manual retry of failed delivery is permitted with a new mutation request ID.

Incoming ceilings:60/key/minute,300/workspace/minute, persisted counters. Admin
can lower a key limit but not raise ceilings. Webhook ceilings:30/endpoint/minute,
60/workspace/minute.429 includes Retry-After. Logs omit authorization, bodies,
exception text and URL paths; keep status, IDs, duration, attempt and safe errors.
Log cursor pages50; latest50 keys/hooks/deliveries on overview.20 active keys,
10 webhooks/workspace. Durable counters prune expired buckets on writes.

## UI And Acceptance

Enterprise workspace tabs: API keys, Webhooks, Logs. No login, developer controls,
fake metrics or external traffic on page load. Explicit submit for sending test.
No localStorage persistence of secrets. Abort/timeout, stale write lock and
workspace/actor/role changes clear visible data/secrets. Role checks server-side.

Tests: permission and tenant isolation, bearer no-admin escalation, invalid,
expired/revoked key, scopes and pagination, shared/concurrent counters, secret
redaction, transactional/rollback fanout, idempotent mutations, SSRF/pinned TLS,
lease expiry/stale completion, retry/disable/rotate, UI error/stale/scope cases.
Use isolated fixtures for writes and outbound transport; live checks read-only.
