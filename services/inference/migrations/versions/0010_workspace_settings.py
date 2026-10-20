"""Versioned workspace settings and personal preferences; no data deletion."""
from alembic import op
import sqlalchemy as sa

revision = '0010_workspace_settings'
down_revision = '0009_workspace_team'
branch_labels = depends_on = None


def upgrade():
    op.create_table('workspace_preferences',
        sa.Column('workspace_id', sa.String(64), sa.ForeignKey('workspaces.id'), primary_key=True),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('collection_revision', sa.Integer(), nullable=False),
        sa.Column('configuration', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_by', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.CheckConstraint('revision >= 0 AND collection_revision >= 0', name='ck_workspace_preferences_revision'))
    op.create_table('user_notification_preferences',
        sa.Column('workspace_id', sa.String(64), sa.ForeignKey('workspaces.id'), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('preferences', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('revision >= 0', name='ck_notification_preferences_revision'))
    op.create_table('settings_mutations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('workspace_id', sa.String(64), sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('result_revision', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_settings_mutations_workspace_id', 'settings_mutations', ['workspace_id'])
    with op.batch_alter_table('data_sessions') as batch:
        batch.add_column(sa.Column('consented_at', sa.DateTime(timezone=True)))
        batch.add_column(sa.Column('policy_revision', sa.Integer()))


def downgrade():
    bind = op.get_bind()
    for table in ('workspace_preferences', 'user_notification_preferences', 'settings_mutations'):
        if bind.execute(sa.text('SELECT count(*) FROM ' + table)).scalar():
            raise RuntimeError('Export settings and preference history before downgrade')
    if bind.execute(sa.text('SELECT count(*) FROM data_sessions WHERE consented_at IS NOT NULL')).scalar():
        raise RuntimeError('Export collection consent before downgrade')
    with op.batch_alter_table('data_sessions') as batch:
        batch.drop_column('policy_revision')
        batch.drop_column('consented_at')
    for table in ('settings_mutations', 'user_notification_preferences', 'workspace_preferences'):
        op.drop_table(table)
