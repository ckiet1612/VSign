"""Add the local registry and explicit deployment queue."""
from alembic import op
import sqlalchemy as sa

revision = "0004_model_registry"
down_revision = "0003_platform_constraints"
branch_labels = None
depends_on = None


def workspace_column():
    return sa.Column("workspace_id", sa.String(64), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)


def upgrade():
    op.create_table("registered_models",
        sa.Column("id", sa.String(36), primary_key=True), workspace_column(),
        sa.Column("model_version", sa.String(160), nullable=False),
        sa.Column("artifact_path", sa.String(2048), nullable=False), sa.Column("labels_path", sa.String(2048), nullable=False),
        sa.Column("labels_count", sa.Integer(), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False), sa.Column("origin", sa.String(20), nullable=False),
        sa.Column("created_by", sa.String(36)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_validation_id", sa.String(36)), sa.Column("approved_by", sa.String(36)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("workspace_id", "model_version", name="uq_registry_version"),
        sa.CheckConstraint("origin IN ('baseline','candidate')", name="ck_model_origin"))
    op.create_table("model_validations",
        sa.Column("id", sa.String(36), primary_key=True), workspace_column(),
        sa.Column("model_id", sa.String(36), sa.ForeignKey("registered_models.id"), nullable=False),
        sa.Column("baseline_model_id", sa.String(36), sa.ForeignKey("registered_models.id"), nullable=False),
        sa.Column("report_sha256", sa.String(64), nullable=False), sa.Column("policy_version", sa.String(40), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False), sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("deployment_targets", workspace_column(),
        sa.Column("target_id", sa.String(64), nullable=False), sa.Column("runtime_url", sa.String(256), nullable=False),
        sa.Column("backend", sa.String(20), nullable=False),
        sa.Column("active_model_id", sa.String(36), sa.ForeignKey("registered_models.id"), nullable=False),
        sa.Column("previous_model_id", sa.String(36), sa.ForeignKey("registered_models.id")),
        sa.Column("revision", sa.Integer(), nullable=False), sa.Column("pending_job_id", sa.String(36)),
        sa.Column("worker_id", sa.String(36)), sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("observed_model_id", sa.String(36)), sa.PrimaryKeyConstraint("workspace_id", "target_id"))
    op.create_table("deployment_jobs", sa.Column("id", sa.String(36), primary_key=True), workspace_column(),
        sa.Column("target_id", sa.String(64), nullable=False), sa.Column("operation", sa.String(12), nullable=False),
        sa.Column("from_model_id", sa.String(36), sa.ForeignKey("registered_models.id"), nullable=False),
        sa.Column("to_model_id", sa.String(36), sa.ForeignKey("registered_models.id"), nullable=False),
        sa.Column("expected_revision", sa.Integer(), nullable=False), sa.Column("status", sa.String(12), nullable=False),
        sa.Column("requested_by", sa.String(36), nullable=False), sa.Column("worker_id", sa.String(36)),
        sa.Column("error", sa.String(256)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("operation IN ('deploy','rollback')", name="ck_deployment_operation"),
        sa.CheckConstraint("status IN ('queued','loading','succeeded','failed')", name="ck_deployment_status"))


def downgrade():
    for name in ("deployment_jobs", "deployment_targets", "model_validations", "registered_models"):
        op.drop_table(name)
