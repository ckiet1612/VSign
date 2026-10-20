"""Add explicit system administration without promoting existing memberships."""

from alembic import op
import sqlalchemy as sa

revision = "0011_system_admin"
down_revision = "0010_workspace_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("memberships") as batch:
        batch.drop_constraint("ck_membership_role", type_="check")
        batch.create_check_constraint("ck_membership_role",
            "role IN ('owner', 'admin', 'operator', 'reviewer', 'viewer', 'model_admin', 'system_admin')")


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT count(*) FROM memberships WHERE role='system_admin'")).scalar():
        raise RuntimeError("Remove system memberships explicitly before downgrading")
    with op.batch_alter_table("memberships") as batch:
        batch.drop_constraint("ck_membership_role", type_="check")
        batch.create_check_constraint("ck_membership_role",
            "role IN ('owner', 'admin', 'operator', 'reviewer', 'viewer', 'model_admin')")
