from __future__ import annotations

from datetime import datetime, timezone

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.exc import IntegrityError
from app.migrate import migration_config, upgrade_database
from app.platform_db import Base

from app.platform_db import (
    AuditEvent,
    Database,
    Membership,
    User,
    Workspace,
    create_database,
    hash_session_token,
)


def test_sqlite_platform_schema_persists_workspace_membership_and_audit_event() -> None:
    database = create_database("sqlite:///:memory:")
    database.create_schema()

    with database.session() as session:
        workspace = Workspace(id="local", name="VSign workspace", environment="production")
        user = User(
            id="user-1",
            email="admin@example.com",
            display_name="Admin",
            password_hash="hashed",
        )
        session.add_all([workspace, user])
        session.flush()
        session.add(Membership(workspace_id=workspace.id, user_id=user.id, role="owner"))
        session.add(
            AuditEvent(
                id="event-1",
                workspace_id=workspace.id,
                event_type="auth.login",
                actor_type="user",
                actor_id=user.id,
                occurred_at=datetime.now(timezone.utc),
                outcome="success",
                metadata_json={"source": "test"},
            )
        )
        session.commit()

    with database.session() as session:
        assert session.get(Workspace, "local").name == "VSign workspace"
        assert session.query(Membership).one().role == "owner"
        assert session.query(User).one().email == "admin@example.com"
        assert session.query(AuditEvent).one().event_type == "auth.login"


def test_session_token_hash_is_deterministic_but_does_not_expose_token() -> None:
    token = "secret-session-token"

    digest = hash_session_token(token)

    assert digest == hash_session_token(token)
    assert digest != token
    assert len(digest) == 64


def test_create_schema_records_latest_revision_and_enables_sqlite_foreign_keys() -> None:
    database = create_database("sqlite:///:memory:")

    database.create_schema()

    with database.engine.connect() as connection:
        revision = connection.exec_driver_sql("select version_num from alembic_version").scalar_one()
        foreign_keys = connection.exec_driver_sql("pragma foreign_keys").scalar_one()

    assert revision == "0012_display_devices"
    assert foreign_keys == 1


def test_platform_roles_and_environment_are_constrained() -> None:
    database = create_database("sqlite:///:memory:")
    database.create_schema()
    with database.session() as session:
        session.add(Workspace(id="local", name="VSign", environment="production"))
        session.commit()
        session.add(Workspace(id="bad", name="VSign", environment="staging"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        session.add(User(id="user-1", email="user@example.com", display_name="User", password_hash="hash"))
        session.flush()
        session.add(Membership(workspace_id="local", user_id="user-1", role="superuser"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_constraint_migration_keeps_all_existing_workspace_rows(tmp_path) -> None:
    database = create_database(f"sqlite:///{tmp_path / 'upgrade.db'}")
    config = migration_config()
    with database.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0002_session_scope")
        connection.exec_driver_sql("INSERT INTO workspaces VALUES ('local','VSign','production','2026-10-13')")
        connection.exec_driver_sql("INSERT INTO users VALUES ('u','u@example.com','User','hash',1,'2026-10-13')")
        connection.exec_driver_sql("INSERT INTO memberships (workspace_id,user_id,role,created_at) VALUES ('local','u','owner','2026-10-13')")
        connection.exec_driver_sql("INSERT INTO sessions VALUES ('s','u','hash','2026-10-13','2027-10-13',NULL,'local')")
        connection.exec_driver_sql("INSERT INTO audit_events VALUES ('e','local','auth.login','user','u','2026-10-13',NULL,NULL,'success','{}')")
    upgrade_database(database)
    with database.engine.connect() as connection:
        for table in ("workspaces", "users", "memberships", "sessions", "audit_events"):
            assert connection.exec_driver_sql(f"SELECT COUNT(*) FROM {table}").scalar_one() == 1
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        assert connection.exec_driver_sql("SELECT role FROM memberships").scalar_one() == "owner"
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []


def test_team_upgrade_preserves_sessions_and_membership_and_roundtrips_empty_schema(tmp_path):
    database = create_database(f"sqlite:///{tmp_path / 'team-upgrade.db'}")
    config = migration_config()
    with database.engine.begin() as connection:
        config.attributes['connection'] = connection
        command.upgrade(config, '0008_workspace_integrations')
        connection.exec_driver_sql("INSERT INTO workspaces VALUES ('local','VSign','production','2026-10-13')")
        connection.exec_driver_sql("INSERT INTO users VALUES ('u','u@example.com','User','hash',1,'2026-10-13')")
        connection.exec_driver_sql("INSERT INTO memberships (workspace_id,user_id,role,created_at) VALUES ('local','u','owner','2026-10-13')")
        connection.exec_driver_sql("INSERT INTO sessions VALUES ('s','u','hash','2026-10-13','2027-10-13',NULL,'local')")
    upgrade_database(database)
    with database.engine.connect() as connection:
        assert connection.exec_driver_sql('SELECT status, revision FROM memberships').one() == ('active',0)
        assert connection.exec_driver_sql('SELECT COUNT(*) FROM sessions').scalar_one() == 1
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    with database.engine.begin() as connection:
        config.attributes['connection'] = connection
        command.downgrade(config, '0008_workspace_integrations')
    upgrade_database(database)
    with database.engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
