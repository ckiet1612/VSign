"""Workspace-local member management and explicit one-time invitation acceptance."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets
import time
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import and_, delete, func, or_, select

from app.platform_auth import Principal, ROLE_PERMISSIONS, local_admin_id, verify_password
from app.platform_db import AuditEvent, AuthSession, Membership, User, Workspace, hash_session_token, utc_now
from app.team_db import TeamInvitation, TeamMutation, TeamRateBucket
from app.workspace_data import WorkspaceData
from contracts.v1.team import TEAM_PRIVATE_EVENTS
from contracts.v1.workspace import WORKSPACE_ROLES, INTERNAL_ROLES


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def stamp(value):
    return aware(value).isoformat() if value else None


def invite_status(row):
    return 'revoked' if row.revoked_at else 'accepted' if row.accepted_at else 'expired' if aware(row.expires_at) <= utc_now() else 'pending'


class WorkspaceTeam(WorkspaceData):
    def __init__(self, database, settings, hasher, session_token=None):
        super().__init__(database, settings)
        self.hasher = hasher
        self.session_hash = hash_session_token(session_token) if session_token else None
        self.scope = SimpleNamespace(workspace=SimpleNamespace(id=settings.workspace_id))

    def manager(self, session, actor):
        if actor.workspace.id != self.settings.workspace_id:
            raise HTTPException(403, 'Workspace không hợp lệ')
        row = session.execute(select(User, Membership).join(Membership, Membership.user_id == User.id).where(
            User.id == actor.user.id, User.is_active.is_(True), Membership.workspace_id == actor.workspace.id,
            Membership.status == 'active')).first()
        if not row or row[1].role not in ('owner', 'admin', 'system_admin'):
            raise HTTPException(403, 'Quyền quản lý thành viên đã thay đổi')
        if self.settings.local_admin_enabled:
            if row[0].id != local_admin_id(actor.workspace.id, self.settings.local_admin_role) or row[0].password_hash != '!' or row[1].role != self.settings.local_admin_role:
                raise HTTPException(403, 'Quyền admin local không hợp lệ')
        elif not session.scalar(select(AuthSession.id).where(
            AuthSession.token_hash == self.session_hash, AuthSession.user_id == actor.user.id,
            AuthSession.workspace_id == actor.workspace.id, AuthSession.revoked_at.is_(None), AuthSession.expires_at > utc_now())):
            raise HTTPException(401, 'Phiên đăng nhập không còn hiệu lực')
        return Principal(row[0], actor.workspace, row[1].role)

    @contextmanager
    def management_write(self, actor):
        with self.write(actor) as session:
            yield session, self.manager(session, actor)

    def grantable(self, role):
        return ['admin', 'operator', 'reviewer', 'viewer'] if role in ('owner', 'system_admin') else ['operator', 'reviewer', 'viewer']

    def visible_roles(self, actor):
        return (*WORKSPACE_ROLES, *INTERNAL_ROLES) if actor.role == 'system_admin' else WORKSPACE_ROLES

    def receipt(self, session, actor, payload, operation):
        digest = hashlib.sha256(json.dumps({'actor':actor.user.id, 'operation':operation,
            'payload':payload.model_dump(mode='json')}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        identity = str(payload.request_id)
        if self.existing(session, TeamMutation, actor, identity, digest):
            return False
        session.add(TeamMutation(id=identity, workspace_id=actor.workspace.id, request_hash=digest))
        return True

    def record(self, session, actor_id, action, resource, before=None, after=None):
        session.add(AuditEvent(id=str(uuid4()), workspace_id=self.settings.workspace_id,
            event_type='permission.'+action, actor_type='user', actor_id=actor_id,
            resource_type='invitation' if action.startswith('invitation') else 'membership',
            resource_id=str(resource), outcome='success',
            metadata_json={'source':'server', 'before':before, 'after':after}))

    def member_query(self, actor):
        return select(User, Membership).join(Membership, Membership.user_id == User.id).where(
            Membership.workspace_id == self.settings.workspace_id, Membership.role.in_(self.visible_roles(actor)))

    def overview(self, actor, search='', cursor=None):
        with self.database.session() as session:
            actor = self.manager(session, actor)
            query = self.member_query(actor)
            if search:
                query = query.where(or_(User.email.icontains(search, autoescape=True), User.display_name.icontains(search, autoescape=True)))
            if cursor:
                query = query.where(User.id > str(cursor))
            rows = session.execute(query.order_by(User.id).limit(51)).all()
            counts = dict(session.execute(select(Membership.status, func.count()).where(
                Membership.workspace_id == actor.workspace.id, Membership.role.in_(self.visible_roles(actor))).group_by(Membership.status)).all())
            return {'api_version':'1', 'workspace_id':actor.workspace.id, 'permissions':{'manage':True},
                'grantable_roles':self.grantable(actor.role), 'counts':{k:counts.get(k,0) for k in ('active','suspended','removed')},
                'members':[{'id':u.id, 'email':u.email, 'display_name':u.display_name, 'role':m.role, 'status':m.status,
                    'active':u.is_active and m.status == 'active', 'revision':m.revision,
                    'protected':u.id in (actor.user.id, local_admin_id(actor.workspace.id)) or m.role not in self.grantable(actor.role),
                    'created_at':stamp(m.created_at)} for u,m in rows[:50]],
                'next_cursor':rows[49][0].id if len(rows)>50 else None}

    def roles(self, actor):
        with self.database.session() as session:
            actor = self.manager(session, actor)
        return {'api_version':'1', 'workspace_id':actor.workspace.id,
            'roles':[{'id':r, 'permissions':sorted(ROLE_PERMISSIONS[r])} for r in self.visible_roles(actor)]}

    def update(self, actor, identity, payload):
        with self.management_write(actor) as (session, actor):
            member = session.scalar(select(Membership).where(Membership.workspace_id == actor.workspace.id,
                Membership.user_id == str(identity), Membership.role.in_(WORKSPACE_ROLES)))
            if not member:
                raise HTTPException(404, 'Không tìm thấy thành viên')
            if not self.receipt(session, actor, payload, 'member.update:'+str(identity)):
                return
            if member.user_id in (actor.user.id, local_admin_id(actor.workspace.id)) or member.role not in self.grantable(actor.role):
                raise HTTPException(403, 'Không được thay đổi thành viên này')
            if payload.role and payload.role not in self.grantable(actor.role):
                raise HTTPException(403, 'Không được cấp vai trò này')
            if member.revision != payload.expected_revision:
                raise HTTPException(409, 'Thành viên đã thay đổi. Làm mới trước khi thao tác')
            if member.status == 'removed':
                raise HTTPException(409, 'Thành viên đã gỡ; cần tạo lời mời mới')
            if payload.status == 'active' and not session.get(User, member.user_id).is_active:
                raise HTTPException(409, 'Tài khoản đã bị vô hiệu hóa ngoài workspace')
            before = {'role':member.role, 'status':member.status}
            if member.role in ('owner','admin') and (payload.role and payload.role not in ('owner','admin') or payload.status in ('suspended','removed')):
                remaining = session.scalar(select(func.count()).select_from(Membership).join(User, User.id == Membership.user_id).where(
                    Membership.workspace_id == actor.workspace.id, Membership.status == 'active', User.is_active.is_(True),
                    Membership.role.in_(('owner','admin')), Membership.user_id != member.user_id))
                if not remaining:
                    raise HTTPException(409, 'Không được mất quản trị viên cuối cùng')
            if payload.role:
                member.role = payload.role
            if payload.status:
                member.status = payload.status
            member.revision += 1
            if member.status != 'active':
                for auth in session.scalars(select(AuthSession).where(AuthSession.workspace_id == actor.workspace.id,
                    AuthSession.user_id == member.user_id, AuthSession.revoked_at.is_(None))).all():
                    auth.revoked_at = utc_now()
            self.record(session, actor.user.id, 'member_updated', member.user_id, before, {'role':member.role,'status':member.status})

    def create_invitation(self, actor, payload):
        secret = None
        with self.management_write(actor) as (session, actor):
            if self.receipt(session, actor, payload, 'invitation.create'):
                if payload.role not in self.grantable(actor.role):
                    raise HTTPException(403, 'Không được mời với vai trò này')
                existing = session.execute(select(User, Membership).outerjoin(Membership,
                    and_(Membership.user_id == User.id, Membership.workspace_id == actor.workspace.id)).where(User.email == payload.email)).first()
                if existing and (not existing[0].is_active or existing[0].password_hash == '!' or existing[1] and existing[1].status != 'removed'):
                    raise HTTPException(409, 'Tài khoản không thể nhận lời mời này; kiểm tra thành viên hiện có')
                pending = list(session.scalars(select(TeamInvitation).where(TeamInvitation.workspace_id == actor.workspace.id,
                    TeamInvitation.accepted_at.is_(None), TeamInvitation.revoked_at.is_(None), TeamInvitation.expires_at > utc_now())).all())
                if len(pending) >= 100 or any(row.email == payload.email for row in pending):
                    raise HTTPException(409, 'Đã có lời mời chờ cho email này hoặc đã đạt giới hạn 100 lời mời')
                secret = secrets.token_urlsafe(32)
                session.add(TeamInvitation(id=str(payload.request_id), workspace_id=actor.workspace.id,
                    email=payload.email, role=payload.role, token_hash=hash_session_token(secret), created_by=actor.user.id,
                    expires_at=utc_now()+timedelta(days=payload.expires_in_days)))
                self.record(session, actor.user.id, 'invitation_created', payload.request_id,
                    after={'email':payload.email,'role':payload.role})
        return {'id':str(payload.request_id), 'secret':secret}

    def revoke_invitation(self, actor, identity, payload):
        with self.management_write(actor) as (session, actor):
            row = self.get(session, TeamInvitation, actor, identity)
            if not self.receipt(session, actor, payload, 'invitation.revoke:'+row.id):
                return
            if row.role not in self.grantable(actor.role):
                raise HTTPException(403, 'Không được thu hồi lời mời này')
            if row.accepted_at:
                raise HTTPException(409, 'Lời mời đã được chấp nhận; cần quản lý thành viên')
            if not row.revoked_at:
                row.revoked_at = utc_now()
                self.record(session, actor.user.id, 'invitation_revoked', row.id)

    def invitations(self, actor, cursor=None):
        with self.database.session() as session:
            self.manager(session, actor)
            query = select(TeamInvitation).where(TeamInvitation.workspace_id == actor.workspace.id)
            if cursor:
                query = query.where(TeamInvitation.id > str(cursor))
            rows = session.scalars(query.order_by(TeamInvitation.id).limit(51)).all()
            return {'api_version':'1','workspace_id':actor.workspace.id,
                'invitations':[{'id':r.id,'email':r.email,'role':r.role,'status':invite_status(r),'created_by':r.created_by,
                    'created_at':stamp(r.created_at),'expires_at':stamp(r.expires_at)} for r in rows[:50]],
                'next_cursor':rows[49].id if len(rows)>50 else None}

    def budget(self, address):
        window = int(time.time())//60
        # Commit attempts separately so invalid tokens/passwords still consume budget.
        with self.write(self.scope) as session:
            session.execute(delete(TeamRateBucket).where(TeamRateBucket.workspace_id == self.settings.workspace_id,
                TeamRateBucket.window < window-1))
            rows = []
            for key, limit in (('public',120),('ip:'+hash_session_token(address),20)):
                row = session.get(TeamRateBucket,(self.settings.workspace_id,key,window))
                if row and row.count >= limit:
                    raise HTTPException(429, 'Thử lời mời quá nhiều lần', headers={'Retry-After':str(max(1,60-int(time.time())%60))})
                rows.append((key,row))
            for key,row in rows:
                if row:
                    row.count += 1
                else:
                    session.add(TeamRateBucket(workspace_id=self.settings.workspace_id,bucket=key,window=window,count=1))

    def token_row(self, session, token):
        row = session.scalar(select(TeamInvitation).where(TeamInvitation.workspace_id == self.settings.workspace_id,
            TeamInvitation.token_hash == hash_session_token(token)))
        if not row:
            raise HTTPException(404, 'Lời mời không hợp lệ')
        if row.revoked_at or aware(row.expires_at) <= utc_now():
            raise HTTPException(410, 'Lời mời đã hết hạn hoặc bị thu hồi')
        return row

    def issuer_valid(self, session, row):
        issuer = session.execute(select(User, Membership).join(Membership, Membership.user_id == User.id).where(
            User.id == row.created_by, User.is_active.is_(True), Membership.workspace_id == row.workspace_id,
            Membership.status == 'active')).first()
        if not issuer or issuer[1].role not in ('owner','admin','system_admin') or row.role not in self.grantable(issuer[1].role):
            raise HTTPException(409, 'Người mời không còn quyền cấp vai trò này; cần lời mời mới')

    def inspect(self, payload, address):
        self.budget(address)
        with self.database.session() as session:
            row = self.token_row(session, payload.token)
            if row.accepted_at:
                raise HTTPException(409, 'Lời mời đã được sử dụng')
            self.issuer_valid(session, row)
            return {'api_version':'1','workspace_id':row.workspace_id, 'workspace_name':session.get(Workspace,row.workspace_id).name,
                'email':row.email,'role':row.role,'expires_at':stamp(row.expires_at),
                'existing_account':bool(session.scalar(select(User.id).where(User.email == row.email))),
                'auth_mode':'local_admin' if self.settings.local_admin_enabled else 'session'}

    def accept(self, payload, address):
        self.budget(address)
        with self.database.session() as session:
            row = self.token_row(session, payload.token)
            user = session.scalar(select(User).where(User.email == row.email))
            old_hash = user.password_hash if user else None
            identity = user.id if user else str(uuid4())
        if old_hash:
            if not verify_password(self.hasher, old_hash, payload.password):
                raise HTTPException(403, 'Mật khẩu tài khoản không đúng')
            encoded = old_hash
        else:
            if len(payload.password) < 12 or not payload.display_name.strip():
                raise HTTPException(422, 'Tài khoản mới cần tên và mật khẩu ít nhất 12 ký tự')
            encoded = self.hasher.hash(payload.password)
        with self.write(self.scope) as session:
            row = self.token_row(session, payload.token)
            user = session.scalar(select(User).where(User.email == row.email))
            if (old_hash is not None and (not user or user.password_hash != old_hash)) or (old_hash is None and user):
                raise HTTPException(409, 'Tài khoản đã thay đổi; kiểm tra lại lời mời')
            if user and (not user.is_active or user.password_hash == '!'):
                raise HTTPException(403, 'Tài khoản không khả dụng')
            if row.accepted_at:
                if row.accept_request_id == str(payload.request_id) and row.accepted_by == identity:
                    return {'api_version':'1','workspace_id':row.workspace_id,'accepted':True}
                raise HTTPException(409, 'Lời mời đã được sử dụng')
            self.issuer_valid(session, row)
            member = session.scalar(select(Membership).where(Membership.workspace_id == row.workspace_id, Membership.user_id == identity))
            if member and (member.status != 'removed' or member.role in ('owner','model_admin','system_admin')):
                raise HTTPException(409, 'Thành viên hiện có cần được quản lý trong workspace')
            if not user:
                session.add(User(id=identity,email=row.email,display_name=payload.display_name.strip(),password_hash=encoded))
                session.flush()
            if not member:
                session.add(Membership(workspace_id=row.workspace_id,user_id=identity,role=row.role))
            else:
                member.status,member.role = 'active',row.role
                member.revision += 1
            row.accepted_at,row.accepted_by,row.accept_request_id = utc_now(),identity,str(payload.request_id)
            self.record(session,identity,'invitation_accepted',row.id,after={'member_id':identity,'role':row.role})
        return {'api_version':'1','workspace_id':self.settings.workspace_id,'accepted':True}

    def history(self, actor, cursor=None, member_id=None, action=None, from_at=None, to_at=None):
        from_at = aware(from_at) if from_at else None
        to_at = aware(to_at) if to_at else None
        if from_at and to_at and from_at > to_at:
            raise HTTPException(422, 'Khoảng thời gian không hợp lệ')
        query = select(AuditEvent).where(AuditEvent.workspace_id == actor.workspace.id,
            AuditEvent.event_type.in_((*TEAM_PRIVATE_EVENTS,'permission.denied')))
        if cursor:
            try:
                at, identity = json.loads(cursor)
                when = datetime.fromisoformat(at)
                UUID(identity)
                if when.tzinfo is None:
                    raise ValueError
            except (ValueError, TypeError, json.JSONDecodeError):
                raise HTTPException(422, 'Cursor không hợp lệ') from None
            query = query.where(or_(AuditEvent.occurred_at < when, and_(AuditEvent.occurred_at == when, AuditEvent.id < identity)))
        if member_id:
            query = query.where(or_(AuditEvent.resource_id == str(member_id), AuditEvent.actor_id == str(member_id),
                AuditEvent.metadata_json['after']['member_id'].as_string() == str(member_id)))
        if action:
            if action not in (*TEAM_PRIVATE_EVENTS,'permission.denied'):
                raise HTTPException(422, 'Loại thao tác không hợp lệ')
            query = query.where(AuditEvent.event_type == action)
        if from_at:
            query = query.where(AuditEvent.occurred_at >= from_at)
        if to_at:
            query = query.where(AuditEvent.occurred_at <= to_at)
        with self.database.session() as session:
            self.manager(session, actor)
            rows = session.scalars(query.order_by(AuditEvent.occurred_at.desc(),AuditEvent.id.desc()).limit(51)).all()
            return {'api_version':'1','workspace_id':actor.workspace.id,'events':[{
                'id':r.id,'action':r.event_type,'actor_id':r.actor_id,'member_id':r.resource_id if r.resource_type == 'membership' else (r.metadata_json.get('after') or {}).get('member_id'),
                'resource_id':r.resource_id,'outcome':r.outcome,'created_at':stamp(r.occurred_at),
                'before':r.metadata_json.get('before'),'after':r.metadata_json.get('after')} for r in rows[:50]],
                'next_cursor':json.dumps([stamp(rows[49].occurred_at),rows[49].id],separators=(',',':')) if len(rows)>50 else None}
