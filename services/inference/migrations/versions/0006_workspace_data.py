"""Workspace-owned collection, label versions and immutable dataset snapshots."""
from alembic import op
import sqlalchemy as sa

revision = "0006_workspace_data"
down_revision = "0005_internal_model_role"
branch_labels = None
depends_on = None


def common():
    return [sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("workspace_id", sa.String(64), sa.ForeignKey("workspaces.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False)]


def parent(column, table):
    return sa.ForeignKeyConstraint(["workspace_id", column], [f"{table}.workspace_id", f"{table}.id"])


def upgrade():
    op.create_table("data_label_versions", *common(),
        sa.Column("name", sa.String(120), nullable=False), sa.Column("parent_id", sa.String(36)),
        sa.Column("entries_json", sa.JSON(), nullable=False), sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False), sa.UniqueConstraint("workspace_id", "id"),
        parent("parent_id", "data_label_versions"))
    op.create_table("data_versions", *common(),
        sa.Column("name", sa.String(120), nullable=False), sa.Column("label_version_id", sa.String(36), nullable=False),
        sa.Column("quota_per_label", sa.Integer(), nullable=False), sa.Column("status", sa.String(12), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False), sa.Column("created_by", sa.String(36), nullable=False),
        sa.UniqueConstraint("workspace_id", "id"), parent("label_version_id", "data_label_versions"),
        sa.CheckConstraint("status IN ('draft','sealed')", name="ck_data_status"),
        sa.CheckConstraint("quota_per_label >= 1 AND quota_per_label <= 10000", name="ck_data_quota"))
    op.create_table("data_sessions", *common(),
        sa.Column("dataset_version_id", sa.String(36), nullable=False), sa.Column("state", sa.String(12), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False), sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("workspace_id", "id"),
        parent("dataset_version_id", "data_versions"),
        sa.CheckConstraint("state IN ('running','paused','stopped','completed')", name="ck_data_session_state"))
    op.create_table("data_samples", *common(),
        sa.Column("dataset_version_id", sa.String(36), nullable=False), sa.Column("collection_session_id", sa.String(36), nullable=False),
        sa.Column("label_id", sa.String(36), nullable=False), sa.Column("expected_label", sa.String(80), nullable=False),
        sa.Column("hand", sa.String(8), nullable=False), sa.Column("relative_path", sa.String(256), nullable=False),
        sa.Column("video_sha256", sa.String(64), nullable=False), sa.Column("metadata_sha256", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False), parent("dataset_version_id", "data_versions"),
        parent("collection_session_id", "data_sessions"),
        sa.CheckConstraint("hand IN ('right','left')", name="ck_data_sample_hand"))
    op.create_table("data_snapshots", *common(),
        sa.Column("dataset_version_id", sa.String(36), nullable=False), sa.Column("label_version_id", sa.String(36), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False), sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False), sa.UniqueConstraint("workspace_id", "dataset_version_id"),
        parent("dataset_version_id", "data_versions"), parent("label_version_id", "data_label_versions"))
    for name in ("data_label_versions", "data_versions", "data_sessions", "data_samples", "data_snapshots"):
        op.create_index(f"ix_{name}_workspace_id", name, ["workspace_id"])
    op.create_index("ix_data_samples_collection_session_id", "data_samples", ["collection_session_id"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM data_samples")).scalar() or op.get_bind().execute(
        sa.text("SELECT count(*) FROM data_snapshots")).scalar():
        raise RuntimeError("Export and retain workspace media before downgrading data schema")
    for name in ("data_snapshots", "data_samples", "data_sessions", "data_versions", "data_label_versions"):
        op.drop_table(name)
