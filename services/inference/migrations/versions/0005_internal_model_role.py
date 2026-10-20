"""Separate internal model management from customer workspace roles."""

from alembic import op
import sqlalchemy as sa

revision = "0005_internal_model_role"
down_revision = "0004_model_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("memberships") as batch:
        batch.drop_constraint("ck_membership_role", type_="check")
        batch.create_check_constraint("ck_membership_role",
            "role IN ('owner', 'admin', 'operator', 'reviewer', 'viewer', 'model_admin')")


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT count(*) FROM memberships WHERE role='model_admin'")).scalar():
        raise RuntimeError("Remove internal memberships explicitly before downgrading")
    with op.batch_alter_table("memberships") as batch:
        batch.drop_constraint("ck_membership_role", type_="check")
        batch.create_check_constraint("ck_membership_role",
            "role IN ('owner', 'admin', 'operator', 'reviewer', 'viewer')")
