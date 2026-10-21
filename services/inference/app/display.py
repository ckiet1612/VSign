"""Counter displays: one-time enrollment codes, permanent device tokens and revocation."""
from datetime import timedelta, timezone
import secrets
import time
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, func, select

from app.platform_db import AuditEvent, User, Workspace, hash_session_token, utc_now
from app.display_db import DisplayDevice, DisplayEnrollment
from app.team_db import TeamRateBucket
from app.workspace_data import WorkspaceData

ENROLLMENT_TTL = timedelta(minutes=10)
MAX_PENDING_ENROLLMENTS = 10
MAX_DISPLAYS = 50
# Wrong codes count against every open code: a 6-digit code survives at most this many guesses in total.
MAX_FAILED_ATTEMPTS = 10
CLAIMS_PER_ADDRESS_PER_MINUTE = 5
CLAIMS_PER_MINUTE = 30
VERIFICATION_ALPHABET = 'ACDEFHJKMNPRTUVWXY34679'


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


def stamp(value):
    return aware(value).isoformat() if value else None


def expired(row):
    return aware(row.expires_at) <= utc_now()


class CounterDisplays(WorkspaceData):
    def __init__(self, database, settings):
        super().__init__(database, settings)
        self.scope = SimpleNamespace(workspace=SimpleNamespace(id=settings.workspace_id))

    def record(self, session, actor_id, action, resource_id, outcome='success', **metadata):
        session.add(AuditEvent(id=str(uuid4()), workspace_id=self.settings.workspace_id, event_type='display.'+action,
            actor_type='user' if actor_id else 'system', actor_id=actor_id, resource_type='display',
            resource_id=str(resource_id) if resource_id else None, outcome=outcome,
            metadata_json={'source':'server', **metadata}))

    def settle(self, session):
        """Open codes past their deadline stop counting as pending."""
        for row in session.scalars(select(DisplayEnrollment).where(DisplayEnrollment.workspace_id == self.settings.workspace_id,
                DisplayEnrollment.status.in_(('pending', 'awaiting_confirmation')))).all():
            if expired(row):
                row.status = 'expired'

    # Staff side

    def overview(self, actor, presence, manage):
        with self.database.session() as session:
            displays = session.scalars(select(DisplayDevice).where(DisplayDevice.workspace_id == actor.workspace.id,
                DisplayDevice.revoked_at.is_(None)).order_by(DisplayDevice.name, DisplayDevice.id)).all()
            enrollments = session.scalars(select(DisplayEnrollment).where(DisplayEnrollment.workspace_id == actor.workspace.id,
                DisplayEnrollment.status.in_(('pending', 'awaiting_confirmation')),
                DisplayEnrollment.expires_at > utc_now()).order_by(DisplayEnrollment.created_at)).all() if manage else []
            rows = []
            for row in displays:
                online, staff = presence(row.id)
                rows.append({'id':row.id, 'name':row.name, 'online':online, 'staff':staff,
                    'last_seen_at':stamp(row.last_seen_at), 'created_at':stamp(row.created_at)})
            return {'api_version':'1', 'workspace_id':actor.workspace.id, 'permissions':{'manage':manage}, 'displays':rows,
                'enrollments':[{'id':row.id, 'name':row.name, 'status':row.status, 'expires_at':stamp(row.expires_at),
                    'verification':row.verification if row.status == 'awaiting_confirmation' else None} for row in enrollments]}

    def staff_display(self, actor, display_id):
        with self.database.session() as session:
            row = session.scalar(select(DisplayDevice).where(DisplayDevice.workspace_id == actor.workspace.id,
                DisplayDevice.id == display_id, DisplayDevice.revoked_at.is_(None)))
            return {'id':row.id, 'name':row.name} if row else None

    def create_enrollment(self, actor, payload):
        code = link_token = None
        with self.write(actor) as session:
            self.settle(session)
            pending = session.scalar(select(func.count()).select_from(DisplayEnrollment).where(
                DisplayEnrollment.workspace_id == actor.workspace.id,
                DisplayEnrollment.status.in_(('pending', 'awaiting_confirmation'))))
            if pending >= MAX_PENDING_ENROLLMENTS:
                raise HTTPException(409, 'Đang có quá nhiều mã chờ; hãy huỷ bớt hoặc chờ mã hết hạn')
            active = session.scalar(select(func.count()).select_from(DisplayDevice).where(
                DisplayDevice.workspace_id == actor.workspace.id, DisplayDevice.revoked_at.is_(None)))
            if active >= MAX_DISPLAYS:
                raise HTTPException(409, f'Workspace đã có {MAX_DISPLAYS} màn hình quầy')
            open_codes = set(session.scalars(select(DisplayEnrollment.code_hash).where(
                DisplayEnrollment.workspace_id == actor.workspace.id, DisplayEnrollment.status == 'pending')).all())
            while code is None or hash_session_token(code) in open_codes:
                code = f'{secrets.randbelow(1_000_000):06d}'
            link_token = secrets.token_urlsafe(32)
            identity = str(uuid4())
            session.add(DisplayEnrollment(id=identity, workspace_id=actor.workspace.id, name=payload.name,
                created_by=actor.user.id, expires_at=utc_now()+ENROLLMENT_TTL, code_hash=hash_session_token(code),
                link_token_hash=hash_session_token(link_token), failed_attempts=0, status='pending'))
            self.record(session, actor.user.id, 'enrollment_created', identity, name=payload.name)
        return {'id':identity, 'name':payload.name, 'code':code, 'link_token':link_token,
            'expires_at':stamp(utc_now()+ENROLLMENT_TTL)}

    def decide(self, actor, identity, accept):
        with self.write(actor) as session:
            self.settle(session)
            row = self.get(session, DisplayEnrollment, actor, identity)
            if not accept and row.status in ('pending', 'awaiting_confirmation'):
                row.status, row.decided_at, row.decided_by = 'rejected', utc_now(), actor.user.id
                self.record(session, actor.user.id, 'enrollment_rejected', row.id, name=row.name)
                return
            if row.status != 'awaiting_confirmation':
                raise HTTPException(409, 'Mã đã hết hạn hoặc chưa có máy khách nhập mã')
            active = session.scalar(select(func.count()).select_from(DisplayDevice).where(
                DisplayDevice.workspace_id == actor.workspace.id, DisplayDevice.revoked_at.is_(None)))
            if active >= MAX_DISPLAYS:
                raise HTTPException(409, f'Workspace đã có {MAX_DISPLAYS} màn hình quầy')
            display = DisplayDevice(id=str(uuid4()), workspace_id=actor.workspace.id, name=row.name,
                token_hash=row.device_token_hash, created_by=actor.user.id, last_seen_at=row.claimed_at)
            session.add(display)
            session.flush()
            row.status, row.decided_at, row.decided_by, row.display_id = 'confirmed', utc_now(), actor.user.id, display.id
            self.record(session, actor.user.id, 'enrollment_confirmed', display.id, name=row.name)

    def rename(self, actor, identity, name):
        with self.write(actor) as session:
            row = self.get(session, DisplayDevice, actor, identity)
            if row.revoked_at:
                raise HTTPException(404, 'Không tìm thấy màn hình quầy')
            if row.name != name:
                self.record(session, actor.user.id, 'renamed', row.id, before=row.name, after=name)
                row.name = name

    def revoke(self, actor, identity):
        with self.write(actor) as session:
            row = self.get(session, DisplayDevice, actor, identity)
            if not row.revoked_at:
                row.revoked_at, row.revoked_by = utc_now(), actor.user.id
                self.record(session, actor.user.id, 'revoked', row.id, name=row.name)

    # Device side (no login: a hashed one-time code, then a hashed device token)

    def budget(self, address):
        window = int(time.time())//60
        with self.write(self.scope) as session:
            session.execute(delete(TeamRateBucket).where(TeamRateBucket.workspace_id == self.settings.workspace_id,
                TeamRateBucket.bucket.startswith('display:'), TeamRateBucket.window < window-1))
            rows = []
            for key, limit in (('display:public', CLAIMS_PER_MINUTE),
                               ('display:ip:'+hash_session_token(address), CLAIMS_PER_ADDRESS_PER_MINUTE)):
                row = session.get(TeamRateBucket, (self.settings.workspace_id, key, window))
                if row and row.count >= limit:
                    raise HTTPException(429, 'Nhập mã quá nhiều lần. Hãy chờ một phút rồi thử lại',
                        headers={'Retry-After':str(max(1, 60-int(time.time())%60))})
                rows.append((key, row))
            for key, row in rows:
                if row:
                    row.count += 1
                else:
                    session.add(TeamRateBucket(workspace_id=self.settings.workspace_id, bucket=key, window=window, count=1))

    def claim(self, payload, address):
        self.budget(address)
        with self.write(self.scope) as session:
            self.settle(session)
            open_rows = select(DisplayEnrollment).where(DisplayEnrollment.workspace_id == self.settings.workspace_id,
                DisplayEnrollment.status == 'pending')
            row = session.scalar(open_rows.where(DisplayEnrollment.code_hash == hash_session_token(payload.code))
                if payload.code else open_rows.where(DisplayEnrollment.link_token_hash == hash_session_token(payload.link_token)))
            failed = row is None or not self.issuer_valid(session, row)
            if failed:
                for other in session.scalars(open_rows).all():
                    other.failed_attempts += 1
                    if other.failed_attempts >= MAX_FAILED_ATTEMPTS:
                        other.status = 'expired'
                        self.record(session, None, 'claim_failed', other.id, outcome='failure', reason='too_many_attempts')
        if failed:
            raise HTTPException(404, 'Mã không đúng hoặc đã hết hạn')
        token = secrets.token_urlsafe(32)
        with self.write(self.scope) as session:
            row = session.get(DisplayEnrollment, row.id)
            if row.status != 'pending' or expired(row):
                raise HTTPException(404, 'Mã không đúng hoặc đã hết hạn')
            row.status, row.claimed_at = 'awaiting_confirmation', utc_now()
            row.expires_at = utc_now()+ENROLLMENT_TTL
            row.device_token_hash = hash_session_token(token)
            row.verification = ''.join(secrets.choice(VERIFICATION_ALPHABET) for _ in range(2))
            state = self.enrollment_state(session, row)
        return token, state

    def issuer_valid(self, session, row):
        from app.platform_db import Membership
        issuer = session.execute(select(User, Membership).join(Membership, Membership.user_id == User.id).where(
            User.id == row.created_by, User.is_active.is_(True), Membership.workspace_id == row.workspace_id,
            Membership.status == 'active')).first()
        return bool(issuer) and issuer[1].role in ('owner', 'admin', 'system_admin')

    def workspace_name(self, session):
        workspace = session.get(Workspace, self.settings.workspace_id)
        return workspace.name if workspace else ''

    def enrollment_state(self, session, row):
        return {'api_version':'1', 'state':'awaiting_confirmation', 'workspace_name':self.workspace_name(session),
            'name':row.name, 'verification':row.verification, 'expires_at':stamp(row.expires_at)}

    def device(self, token, touch=False):
        """The enrolled display behind a device token, or None. Revocation is the only expiry."""
        if not token or len(token) > 128:
            return None
        with self.database.session() as session:
            row = session.scalar(select(DisplayDevice).where(DisplayDevice.workspace_id == self.settings.workspace_id,
                DisplayDevice.token_hash == hash_session_token(token), DisplayDevice.revoked_at.is_(None)))
            if row is None:
                return None
            if touch:
                row.last_seen_at = utc_now()
                session.commit()
            return {'id':row.id, 'name':row.name}

    def me(self, token):
        display = self.device(token)
        with self.database.session() as session:
            if display:
                return {'api_version':'1', 'state':'paired', 'workspace_name':self.workspace_name(session), 'display':display}
            reason = None
            if token and len(token) <= 128:
                row = session.scalar(select(DisplayEnrollment).where(DisplayEnrollment.workspace_id == self.settings.workspace_id,
                    DisplayEnrollment.device_token_hash == hash_session_token(token)))
                if row and row.status == 'awaiting_confirmation' and not expired(row):
                    return self.enrollment_state(session, row)
                if row:
                    reason = 'revoked' if row.status == 'confirmed' else 'rejected' if row.status == 'rejected' else 'expired'
            return {'api_version':'1', 'state':'unpaired', 'reason':reason}
