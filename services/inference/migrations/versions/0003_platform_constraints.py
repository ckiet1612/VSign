"""Constrain workspace values used by RBAC and audit responses."""

from alembic import op

revision = "0003_platform_constraints"
down_revision = "0002_session_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workspaces") as batch:
        batch.create_check_constraint("ck_workspace_environment", "environment IN ('development', 'production')")
    with op.batch_alter_table("memberships") as batch:
        batch.create_check_constraint("ck_membership_role", "role IN ('owner', 'admin', 'operator', 'reviewer', 'viewer')")
    with op.batch_alter_table("audit_events") as batch:
        batch.create_check_constraint("ck_audit_actor_type", "actor_type IN ('system', 'user', 'service')")
        batch.create_check_constraint("ck_audit_outcome", "outcome IN ('success', 'failure')")


def downgrade() -> None:
    with op.batch_alter_table("audit_events") as batch:
        batch.drop_constraint("ck_audit_outcome", type_="check")
        batch.drop_constraint("ck_audit_actor_type", type_="check")
    with op.batch_alter_table("memberships") as batch:
        batch.drop_constraint("ck_membership_role", type_="check")
    with op.batch_alter_table("workspaces") as batch:
        batch.drop_constraint("ck_workspace_environment", type_="check")
