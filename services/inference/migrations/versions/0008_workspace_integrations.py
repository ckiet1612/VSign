"""Scoped integration keys, durable webhook deliveries and shared limits."""
from alembic import op
import sqlalchemy as sa

revision = '0008_workspace_integrations'
down_revision = '0007_workspace_evaluations'
branch_labels = depends_on = None


def scoped():
    return [sa.Column('id',sa.String(36),primary_key=True),
            sa.Column('workspace_id',sa.String(64),sa.ForeignKey('workspaces.id'),nullable=False),
            sa.Column('created_at',sa.DateTime(timezone=True),nullable=False)]


def upgrade():
    op.create_table('integration_keys', *scoped(), sa.Column('name',sa.String(120),nullable=False),
        sa.Column('prefix',sa.String(24),nullable=False), sa.Column('token_hash',sa.String(64),unique=True,nullable=False),
        sa.Column('scopes',sa.JSON(),nullable=False),sa.Column('requests_per_minute',sa.Integer(),nullable=False),
        sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('revoked_at',sa.DateTime(timezone=True)),sa.Column('last_used_at',sa.DateTime(timezone=True)))
    op.create_table('integration_webhooks', *scoped(), sa.Column('name',sa.String(120),nullable=False),
        sa.Column('url',sa.String(2048),nullable=False),sa.Column('events',sa.JSON(),nullable=False),
        sa.Column('enabled',sa.Boolean(),nullable=False),sa.Column('secret_ciphertext',sa.String(512),nullable=False),
        sa.Column('secret_version',sa.Integer(),nullable=False),sa.UniqueConstraint('workspace_id','id'))
    op.create_table('integration_deliveries', *scoped(), sa.Column('webhook_id',sa.String(36),nullable=False),
        sa.Column('event_id',sa.String(36),nullable=False),sa.Column('event_type',sa.String(120),nullable=False),
        sa.Column('payload',sa.JSON(),nullable=False),sa.Column('status',sa.String(12),nullable=False),
        sa.Column('attempts',sa.Integer(),nullable=False),sa.Column('available_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('claim_token',sa.String(36)),sa.Column('lease_until',sa.DateTime(timezone=True)),
        sa.Column('status_code',sa.Integer()),sa.Column('error',sa.String(64)),
        sa.UniqueConstraint('webhook_id','event_id'),
        sa.ForeignKeyConstraint(['workspace_id','webhook_id'],['integration_webhooks.workspace_id','integration_webhooks.id']),
        sa.CheckConstraint("status IN ('pending','sending','delivered','failed','cancelled')",name='ck_integration_delivery_status'))
    op.create_table('integration_logs', *scoped(),sa.Column('kind',sa.String(12),nullable=False),
        sa.Column('resource_id',sa.String(36),nullable=False),sa.Column('action',sa.String(120),nullable=False),
        sa.Column('status_code',sa.Integer(),nullable=False),sa.Column('duration_ms',sa.Integer(),nullable=False),
        sa.Column('attempt',sa.Integer(),nullable=False),sa.Column('error',sa.String(64)))
    op.create_table('integration_rate_buckets',
        sa.Column('workspace_id',sa.String(64),sa.ForeignKey('workspaces.id'),primary_key=True),
        sa.Column('bucket',sa.String(120),primary_key=True),sa.Column('window',sa.Integer(),primary_key=True),
        sa.Column('count',sa.Integer(),nullable=False))
    op.create_table('integration_mutations',*scoped(),sa.Column('request_hash',sa.String(64),nullable=False))
    op.create_table('integration_workers',sa.Column('workspace_id',sa.String(64),sa.ForeignKey('workspaces.id'),primary_key=True),
        sa.Column('heartbeat_at',sa.DateTime(timezone=True),nullable=False))
    for name in ('keys','webhooks','deliveries','logs','mutations'):
        table='integration_'+name
        op.create_index('ix_'+table+'_workspace_id',table,['workspace_id'])


def downgrade():
    for name in ('keys','webhooks','deliveries','logs','mutations'):
        if op.get_bind().execute(sa.text('SELECT count(*) FROM integration_'+name)).scalar():
            raise RuntimeError('Export integration history before downgrade')
    for name in ('workers','mutations','rate_buckets','logs','deliveries','webhooks','keys'):
        op.drop_table('integration_'+name)
