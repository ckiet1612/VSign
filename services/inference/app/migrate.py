from __future__ import annotations

import os
import argparse
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, inspect

from app.platform_db import Base, Database, create_database
from app import model_registry_db  # Register registry metadata for schema checks.
from app import workspace_data_db  # Register workspace data metadata.
from app import evaluation_db  # Register evaluation queue metadata.
from app import integration_db  # Register integration metadata.
from app import team_db  # Register invitations and team metadata.
from app import workspace_settings_db  # Register workspace and personal preferences.
from app import display_db  # Register counter displays.
from app import usage_db  # Register usage report summaries.


CURRENT_SCHEMA_REVISION = "0013_usage_conversations"


def migration_config() -> Config:
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.attributes["configure_logging"] = False
    return config


def upgrade_database(database: Database, adopt_legacy: bool = False) -> None:
    config = migration_config()
    with database.engine.connect() as connection:
        is_sqlite = connection.dialect.name == "sqlite"
        if is_sqlite:
            # Alembic rebuilds SQLite tables. Disable cascades only for the migration transaction.
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            connection.begin()
        try:
            _upgrade_connection(connection, config, adopt_legacy)
            if is_sqlite and connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("Migration tạo khóa ngoại không hợp lệ; đã rollback")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            if is_sqlite:
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                connection.commit()


def _upgrade_connection(connection, config: Config, adopt_legacy: bool) -> None:
        config.attributes["connection"] = connection
        inspector = inspect(connection)
        existing = set(inspector.get_table_names()) - {"alembic_version"}
        revision = MigrationContext.configure(connection).get_current_revision()
        if existing and revision is None:
            if not adopt_legacy:
                raise RuntimeError("Schema chưa có version. Sao lưu database rồi chạy app.migrate --adopt-legacy")
            # Adopt only the exact pre-migration schema; never stamp unknown tables.
            legacy = MetaData()
            for table in Base.metadata.sorted_tables:
                if table.name in {"workspaces", "users", "audit_events"}:
                    table.to_metadata(legacy)
            from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Table, UniqueConstraint
            Table('memberships', legacy,
                  Column('id', Integer, primary_key=True, autoincrement=True),
                  Column('workspace_id', ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
                  Column('user_id', ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
                  Column('role', String(24), nullable=False),
                  Column('created_at', DateTime(timezone=True), nullable=False),
                  UniqueConstraint('workspace_id', 'user_id', name='uq_membership_workspace_user'),
                  CheckConstraint("role IN ('owner', 'admin', 'operator', 'reviewer', 'viewer')", name='ck_membership_role'))
            Table("sessions", legacy,
                  Column("id", String(36), primary_key=True),
                  Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
                  Column("token_hash", String(64), unique=True, index=True, nullable=False),
                  Column("created_at", DateTime(timezone=True), nullable=False),
                  Column("expires_at", DateTime(timezone=True), nullable=False, index=True),
                  Column("revoked_at", DateTime(timezone=True), nullable=True))
            differences = compare_metadata(MigrationContext.configure(connection), legacy)
            if differences:
                raise RuntimeError("Schema legacy không khớp; không tự động thay đổi database")
            command.stamp(config, "0001_workspace_foundation")
        command.upgrade(config, "head")


def verify_schema(database: Database) -> None:
    with database.engine.connect() as connection:
        if MigrationContext.configure(connection).get_current_revision() != CURRENT_SCHEMA_REVISION:
            raise RuntimeError("Database chưa được migrate; chạy python -m app.migrate")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adopt-legacy", action="store_true")
    args = parser.parse_args()
    database_url = os.getenv("DATABASE_URL", "sqlite:///./data/vsign-platform.db")
    database = create_database(database_url)
    try:
        upgrade_database(database, adopt_legacy=args.adopt_legacy)
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
