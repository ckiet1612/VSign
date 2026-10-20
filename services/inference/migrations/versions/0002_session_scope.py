"""Bind new sessions to one workspace; invalidate unscoped legacy sessions."""

from alembic import op
import sqlalchemy as sa

revision = "0002_session_scope"
down_revision = "0001_workspace_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sessions") as batch:
        batch.add_column(sa.Column("workspace_id", sa.String(64), nullable=True))
        batch.create_foreign_key("fk_session_workspace", "workspaces", ["workspace_id"], ["id"], ondelete="CASCADE")
        batch.create_index("ix_sessions_workspace_id", ["workspace_id"])
    op.execute(sa.text("UPDATE sessions SET revoked_at = CURRENT_TIMESTAMP WHERE workspace_id IS NULL AND revoked_at IS NULL"))


def downgrade() -> None:
    with op.batch_alter_table("sessions") as batch:
        batch.drop_index("ix_sessions_workspace_id")
        batch.drop_constraint("fk_session_workspace", type_="foreignkey")
        batch.drop_column("workspace_id")
