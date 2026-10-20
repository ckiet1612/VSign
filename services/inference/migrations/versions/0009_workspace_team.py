"""Workspace-local membership state and one-time invitations."""
from alembic import op
import sqlalchemy as sa

revision = '0009_workspace_team'
down_revision = '0008_workspace_integrations'
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table('memberships') as batch:
        batch.add_column(sa.Column('status', sa.String(12), nullable=False, server_default='active'))
        batch.add_column(sa.Column('revision', sa.Integer(), nullable=False, server_default='0'))
        batch.create_check_constraint('ck_membership_status', "status IN ('active','suspended','removed')")
    op.create_table('team_invitations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('workspace_id', sa.String(64), sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('email', sa.String(320), nullable=False),
        sa.Column('role', sa.String(24), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('created_by', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True)),
        sa.Column('accepted_at', sa.DateTime(timezone=True)),
        sa.Column('accepted_by', sa.String(36), sa.ForeignKey('users.id')),
        sa.Column('accept_request_id', sa.String(36)))
    op.create_index('ix_team_invitations_workspace_id', 'team_invitations', ['workspace_id'])
    op.create_table('team_mutations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('workspace_id', sa.String(64), sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_team_mutations_workspace_id', 'team_mutations', ['workspace_id'])
    op.create_table('team_rate_buckets',
        sa.Column('workspace_id', sa.String(64), sa.ForeignKey('workspaces.id'), primary_key=True),
        sa.Column('bucket', sa.String(80), primary_key=True),
        sa.Column('window', sa.Integer(), primary_key=True),
        sa.Column('count', sa.Integer(), nullable=False))


def downgrade():
    bind = op.get_bind()
    if (bind.execute(sa.text('SELECT count(*) FROM team_invitations')).scalar()
            or bind.execute(sa.text('SELECT count(*) FROM team_mutations')).scalar()
            or bind.execute(sa.text("SELECT count(*) FROM memberships WHERE status != 'active' OR revision != 0")).scalar()):
        raise RuntimeError('Export team history before downgrade')
    for table in ('team_rate_buckets', 'team_mutations', 'team_invitations'):
        op.drop_table(table)
    with op.batch_alter_table('memberships') as batch:
        batch.drop_constraint('ck_membership_status', type_='check')
        batch.drop_column('revision')
        batch.drop_column('status')
