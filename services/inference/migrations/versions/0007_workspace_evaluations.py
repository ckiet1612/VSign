"""Durable workspace evaluation queue and trusted validation linkage."""
from alembic import op
import sqlalchemy as sa

revision = '0007_workspace_evaluations'
down_revision = '0006_workspace_data'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('evaluation_runs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('workspace_id', sa.String(64), sa.ForeignKey('workspaces.id'), nullable=False),
        sa.Column('model_id', sa.String(36), sa.ForeignKey('registered_models.id'), nullable=False),
        sa.Column('baseline_model_id', sa.String(36), sa.ForeignKey('registered_models.id'), nullable=False),
        sa.Column('snapshot_id', sa.String(36), sa.ForeignKey('data_snapshots.id'), nullable=False),
        sa.Column('requested_by', sa.String(36), nullable=False),
        sa.Column('status', sa.String(12), nullable=False),
        sa.Column('frozen_json', sa.JSON(), nullable=False),
        sa.Column('report_json', sa.JSON(), nullable=True), sa.Column('gate_json', sa.JSON(), nullable=True),
        sa.Column('report_sha256', sa.String(64)), sa.Column('worker_id', sa.String(36)),
        sa.Column('heartbeat_at', sa.DateTime(timezone=True)), sa.Column('progress', sa.Integer(), nullable=False),
        sa.Column('error', sa.String(256)), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True)), sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('queued','running','completed','failed','cancelled')", name='ck_evaluation_status'))
    op.create_index('ix_evaluation_runs_workspace_id', 'evaluation_runs', ['workspace_id'])
    op.create_table('evaluation_workers',
        sa.Column('workspace_id', sa.String(64), sa.ForeignKey('workspaces.id'), primary_key=True),
        sa.Column('backend', sa.String(20), primary_key=True),
        sa.Column('worker_id', sa.String(36), nullable=False),
        sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=False))
    op.add_column('model_validations', sa.Column('evaluation_run_id', sa.String(36), nullable=True))


def downgrade():
    if op.get_bind().execute(sa.text('SELECT count(*) FROM evaluation_runs')).scalar():
        raise RuntimeError('Export evaluation history before downgrade')
    op.drop_column('model_validations', 'evaluation_run_id')
    op.drop_table('evaluation_workers')
    op.drop_table('evaluation_runs')
