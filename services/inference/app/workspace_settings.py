"""Workspace-scoped preferences and read-only retention assessment."""
from datetime import timedelta, timezone
import hashlib
import json
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import and_, func, select

from app.platform_auth import Principal, local_admin_id
from app.platform_db import AuditEvent, AuthSession, Membership, User, Workspace, hash_session_token, utc_now
from app.workspace_data import WorkspaceData
from app.workspace_data_db import DataSample, DataSession, DatasetSnapshot, DatasetVersion
from app.workspace_settings_db import SettingsMutation, UserNotificationPreferences, WorkspacePreferences
from contracts.v1.settings import NotificationPreferences, StoredConfiguration


def stamp(value):
    if value is None:
        return None
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).isoformat()


def configuration(row):
    return StoredConfiguration.model_validate(row.configuration if row else {}).model_dump(mode='json')


def collection_policy(session, settings):
    row = session.get(WorkspacePreferences, settings.workspace_id)
    policy = configuration(row)['collection_policy']
    return {**policy, 'enabled': settings.collection_enabled and policy['enabled'],
            'process_enabled': settings.collection_enabled, 'revision': row.collection_revision if row else 0}


def check_collection_policy(session, settings, consented=False):
    policy = collection_policy(session, settings)
    if not policy['enabled']:
        raise HTTPException(403, 'Thu dữ liệu đang bị tắt theo chính sách workspace hoặc máy chủ')
    if policy['require_consent'] and not consented:
        raise HTTPException(403, 'Cần đồng ý lưu mẫu và bắt đầu phiên thu mới theo chính sách workspace')
    return policy


class WorkspaceSettings(WorkspaceData):
    def __init__(self, database, settings, session_token=None):
        super().__init__(database, settings)
        self.session_hash = hash_session_token(session_token) if session_token else None

    def actor(self, session, actor, permission='settings:preferences'):
        if actor.workspace.id != self.settings.workspace_id:
            raise HTTPException(403, 'Workspace không hợp lệ')
        row = session.execute(select(User, Membership).join(Membership, Membership.user_id == User.id).where(
            User.id == actor.user.id, User.is_active.is_(True), Membership.workspace_id == self.settings.workspace_id,
            Membership.status == 'active')).first()
        if not row:
            raise HTTPException(403, 'Quyền workspace đã thay đổi')
        current = Principal(row[0], actor.workspace, row[1].role)
        if not current.can(permission):
            raise HTTPException(403, 'Bạn không có quyền thay đổi cài đặt này')
        if self.settings.local_admin_enabled:
            if row[0].id != local_admin_id(actor.workspace.id, self.settings.local_admin_role) or row[0].password_hash != '!' or row[1].role != self.settings.local_admin_role:
                raise HTTPException(403, 'Quyền admin local không hợp lệ')
        elif not session.scalar(select(AuthSession.id).where(
                AuthSession.token_hash == self.session_hash, AuthSession.user_id == actor.user.id,
                AuthSession.workspace_id == actor.workspace.id, AuthSession.revoked_at.is_(None), AuthSession.expires_at > utc_now())):
            raise HTTPException(401, 'Phiên đăng nhập không còn hiệu lực')
        return current

    def overview(self, actor):
        with self.database.session() as session:
            actor = self.actor(session, actor)
            row = session.get(WorkspacePreferences, actor.workspace.id)
            personal = session.get(UserNotificationPreferences, (actor.workspace.id, actor.user.id))
            workspace = session.get(Workspace, actor.workspace.id)
            config = configuration(row)
            manage = actor.can('settings:manage')
            return dict(api_version='1', workspace_id=actor.workspace.id, user_id=actor.user.id,
                revision=row.revision if row else 0, updated_at=stamp(row.updated_at) if row else None,
                permissions={'manage': manage}, workspace={'name': workspace.name, 'timezone': config['timezone']} if manage else None,
                retention=config['retention'] if manage else None, collection_policy=config['collection_policy'] if manage else None,
                runtime_defaults=config['runtime_defaults'], process_collection_enabled=self.settings.collection_enabled,
                notifications=dict(revision=personal.revision if personal else 0,
                    updated_at=stamp(personal.updated_at) if personal else None,
                    preferences=NotificationPreferences.model_validate(personal.preferences).model_dump() if personal else
                        {'collection_completed': True, 'evaluation_finished': True, 'integration_failed': True},
                    delivery='not_configured'), request_id=None, applied_revision=None)

    def receipt(self, session, actor, payload, operation):
        digest = hashlib.sha256(json.dumps({'actor': actor.user.id, 'workspace': actor.workspace.id, 'operation': operation,
            'payload': payload.model_dump(mode='json')}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        row = session.get(SettingsMutation, str(payload.request_id))
        if row and (row.workspace_id != actor.workspace.id or row.request_hash != digest):
            raise HTTPException(409, 'Mã yêu cầu đã được dùng cho nội dung khác')
        return row, digest

    def record_change(self, session, actor, payload, digest, revision, event_type, metadata):
        session.add(SettingsMutation(id=str(payload.request_id), workspace_id=actor.workspace.id,
            request_hash=digest, result_revision=revision))
        session.add(AuditEvent(id=str(uuid4()), workspace_id=actor.workspace.id, event_type=event_type,
            actor_type='user', actor_id=actor.user.id, resource_type='settings',
            resource_id=actor.user.id if event_type == 'settings.notifications_updated' else actor.workspace.id,
            outcome='success', metadata_json={'source': 'server', **metadata}))

    def update(self, actor, payload):
        with self.write(actor) as session:
            actor = self.actor(session, actor, 'settings:manage')
            receipt, digest = self.receipt(session, actor, payload, 'workspace.update')
            if receipt:
                revision = receipt.result_revision
            else:
                row = session.get(WorkspacePreferences, actor.workspace.id)
                revision = row.revision if row else 0
                if revision != payload.expected_revision:
                    raise HTTPException(409, 'Cài đặt đã thay đổi. Làm mới trước khi lưu')
                workspace = session.get(Workspace, actor.workspace.id)
                before = {'workspace': {'name': workspace.name, 'timezone': configuration(row)['timezone']}, **configuration(row)}
                config = configuration(row)
                if payload.workspace:
                    workspace.name = payload.workspace.name
                    config['timezone'] = payload.workspace.timezone
                for key in ('retention', 'collection_policy', 'runtime_defaults'):
                    section = getattr(payload, key)
                    if section is not None:
                        config[key] = section.model_dump(mode='json')
                collection_revision = row.collection_revision if row else 0
                if config['collection_policy'] != before['collection_policy']:
                    collection_revision += 1
                revision += 1
                if row is None:
                    row = WorkspacePreferences(workspace_id=actor.workspace.id)
                    session.add(row)
                row.configuration, row.revision, row.collection_revision = config, revision, collection_revision
                row.updated_at, row.updated_by = utc_now(), actor.user.id
                after = {'workspace': {'name': workspace.name, 'timezone': config['timezone']}, **config}
                self.record_change(session, actor, payload, digest, revision, 'settings.updated',
                    {'before': before, 'after': after, 'revision': revision})
        return {**self.overview(actor), 'request_id': str(payload.request_id), 'applied_revision': revision}

    def notifications(self, actor, payload):
        with self.write(actor) as session:
            actor = self.actor(session, actor)
            receipt, digest = self.receipt(session, actor, payload, 'notifications.update')
            if receipt:
                revision = receipt.result_revision
            else:
                row = session.get(UserNotificationPreferences, (actor.workspace.id, actor.user.id))
                revision = row.revision if row else 0
                if revision != payload.expected_revision:
                    raise HTTPException(409, 'Tùy chọn thông báo đã thay đổi. Làm mới trước khi lưu')
                revision += 1
                if row is None:
                    row = UserNotificationPreferences(workspace_id=actor.workspace.id, user_id=actor.user.id)
                    session.add(row)
                row.revision, row.preferences, row.updated_at = revision, payload.preferences.model_dump(), utc_now()
                self.record_change(session, actor, payload, digest, revision, 'settings.notifications_updated',
                    {'revision': revision, 'fields': sorted(row.preferences)})
        return {**self.overview(actor), 'request_id': str(payload.request_id), 'applied_revision': revision}

    def effective(self, actor):
        with self.database.session() as session:
            self.actor(session, actor)
            config = configuration(session.get(WorkspacePreferences, actor.workspace.id))
            return dict(api_version='1', workspace_id=actor.workspace.id,
                collection=collection_policy(session, self.settings), runtime_defaults=config['runtime_defaults'])

    def preview(self, actor):
        with self.database.session() as session:
            self.actor(session, actor, 'settings:manage')
            row = session.get(WorkspacePreferences, actor.workspace.id)
            policy = configuration(row)['retention']
            now = utc_now()
            cutoff = lambda days: now - timedelta(days=days) if days else None
            sample_cutoff, audit_cutoff = cutoff(policy['draft_samples_days']), cutoff(policy['audit_events_days'])
            scope = actor.workspace.id
            snapshot_exists = select(DatasetSnapshot.id).where(DatasetSnapshot.workspace_id == scope,
                DatasetSnapshot.dataset_version_id == DatasetVersion.id).exists()
            active_exists = select(DataSession.id).where(DataSession.workspace_id == scope,
                DataSession.dataset_version_id == DatasetVersion.id, DataSession.state.in_(('running', 'paused'))).exists()
            eligible = and_(DatasetVersion.status == 'draft', ~snapshot_exists, ~active_exists)
            samples = select(func.count()).select_from(DataSample).join(DatasetVersion,
                and_(DataSample.workspace_id == DatasetVersion.workspace_id, DataSample.dataset_version_id == DatasetVersion.id)
            ).where(DataSample.workspace_id == scope)
            candidates = session.scalar(samples.where(eligible, DataSample.created_at < sample_cutoff)) if sample_cutoff else 0
            protected = session.scalar(samples.where(~eligible))
            audit = session.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.workspace_id == scope, AuditEvent.occurred_at < audit_cutoff)) if audit_cutoff else 0
            snapshots = session.scalar(select(func.count()).select_from(DatasetSnapshot).where(DatasetSnapshot.workspace_id == scope))
            return dict(api_version='1', workspace_id=scope, revision=row.revision if row else 0,
                generated_at=stamp(now), automatic_deletion=False, candidates={'draft_samples': candidates, 'audit_events': audit},
                protected={'samples': protected, 'snapshots': snapshots},
                cutoffs={'draft_samples': stamp(sample_cutoff), 'audit_events': stamp(audit_cutoff)})
