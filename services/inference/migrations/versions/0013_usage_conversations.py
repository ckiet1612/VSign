"""Usage reports: one aggregated row per counter conversation, no media or free text."""
from alembic import op
import sqlalchemy as sa

revision = '0013_usage_conversations'
down_revision = '0012_display_devices'
branch_labels = depends_on = None


def upgrade():
    op.create_table('usage_conversations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('workspace_id', sa.String(64), sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('display_id', sa.String(36), sa.ForeignKey('display_devices.id')),
        sa.Column('channel', sa.String(16), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('words', sa.Integer(), nullable=False),
        sa.Column('uncertain', sa.Integer(), nullable=False),
        sa.Column('failed', sa.Integer(), nullable=False),
        sa.Column('staff_undos', sa.Integer(), nullable=False),
        sa.Column('customer_undos', sa.Integer(), nullable=False),
        sa.Column('replies', sa.Integer(), nullable=False),
        sa.Column('voice_replies', sa.Integer(), nullable=False),
        sa.Column('labels_json', sa.JSON(), nullable=False),
        sa.Column('undone_labels_json', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_usage_conversations_workspace_started', 'usage_conversations', ['workspace_id', 'started_at'])


def downgrade():
    op.drop_index('ix_usage_conversations_workspace_started', 'usage_conversations')
    op.drop_table('usage_conversations')
