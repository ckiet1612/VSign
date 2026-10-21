"""Counter displays enrolled once with a one-time code and kept until revoked."""
from alembic import op
import sqlalchemy as sa

revision = '0012_display_devices'
down_revision = '0011_system_admin'
branch_labels = depends_on = None


def upgrade():
    op.create_table('display_devices',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('workspace_id', sa.String(64), sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('name', sa.String(60), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('created_by', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True)),
        sa.Column('revoked_at', sa.DateTime(timezone=True)),
        sa.Column('revoked_by', sa.String(36), sa.ForeignKey('users.id')))
    op.create_index('ix_display_devices_workspace_id', 'display_devices', ['workspace_id'])
    op.create_table('display_enrollments',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('workspace_id', sa.String(64), sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('name', sa.String(60), nullable=False),
        sa.Column('created_by', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('code_hash', sa.String(64), nullable=False),
        sa.Column('link_token_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('failed_attempts', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('verification', sa.String(4)),
        sa.Column('device_token_hash', sa.String(64), unique=True),
        sa.Column('claimed_at', sa.DateTime(timezone=True)),
        sa.Column('decided_at', sa.DateTime(timezone=True)),
        sa.Column('decided_by', sa.String(36), sa.ForeignKey('users.id')),
        sa.Column('display_id', sa.String(36), sa.ForeignKey('display_devices.id')),
        sa.CheckConstraint("status IN ('pending','awaiting_confirmation','confirmed','rejected','expired')",
                           name='ck_display_enrollment_status'))
    op.create_index('ix_display_enrollments_workspace_id', 'display_enrollments', ['workspace_id'])
    op.create_index('ix_display_enrollments_code_hash', 'display_enrollments', ['code_hash'])


def downgrade():
    if op.get_bind().execute(sa.text('SELECT count(*) FROM display_devices WHERE revoked_at IS NULL')).scalar():
        raise RuntimeError('Revoke counter displays explicitly before downgrading')
    op.drop_table('display_enrollments')
    op.drop_table('display_devices')
