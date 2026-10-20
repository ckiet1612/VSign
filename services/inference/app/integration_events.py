"""Fan out allowlisted audit insertions in the same transaction, never replay history."""
from uuid import uuid4

from sqlalchemy import select
from app.platform_db import AuditEvent, utc_now
from app.integration_db import IntegrationWebhook, IntegrationDelivery
from contracts.v1.integrations import EVENT_NAMES


def envelope(event):
    when=event.occurred_at or utc_now()
    return {'api_version':'1','event_id':event.id,'workspace_id':event.workspace_id,
            'event_type':event.event_type,'occurred_at':when.isoformat(),
            'outcome':event.outcome,'resource_type':event.resource_type,'resource_id':event.resource_id}


def capture_events(session, _context, _instances):
    events=[e for e in session.new if isinstance(e,AuditEvent) and e.event_type in EVENT_NAMES
            and (e.metadata_json or {}).get('source') != 'browser_report']
    for event in events:
        hooks=session.scalars(select(IntegrationWebhook).where(
            IntegrationWebhook.workspace_id == event.workspace_id,IntegrationWebhook.enabled.is_(True))).all()
        for hook in hooks:
            if event.event_type in hook.events:
                session.add(IntegrationDelivery(id=str(uuid4()),workspace_id=event.workspace_id,webhook_id=hook.id,
                    event_id=event.id,event_type=event.event_type,payload=envelope(event)))
