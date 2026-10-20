"""Explicit, one-time account provisioning; never resets or promotes an existing user."""

from __future__ import annotations

import argparse
import getpass
import re
from uuid import uuid4

from argon2 import PasswordHasher
from sqlalchemy import select

from app.config import Settings
from app.platform_auth import login_email
from app.platform_db import AuditEvent, Database, Membership, User, Workspace, create_database


def provision_admin(database: Database, settings: Settings, username: str, password: str,
                    *, allow_short_password: bool = False) -> None:
    username = username.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,63}", username):
        raise ValueError("Username must be 3-64 letters, digits, dots, underscores or hyphens")
    if not 1 <= len(password) <= 256 or (len(password) < 12 and not allow_short_password):
        raise ValueError("Password must be 12-256 characters; short temporary passwords require explicit opt-in")
    password_hash = PasswordHasher().hash(password)
    with database.session() as session:
        email = login_email(username)
        if session.scalar(select(User).where(User.email == email)) is not None:
            raise ValueError("Account already exists; no password or role has been changed")
        workspace = session.get(Workspace, settings.workspace_id)
        if workspace is None:
            workspace = Workspace(id=settings.workspace_id, name=settings.workspace_name,
                                  environment=settings.app_environment)
            session.add(workspace)
            session.flush()
        user = User(id=str(uuid4()), email=email, display_name=username, password_hash=password_hash)
        session.add(user)
        session.flush()
        session.add(Membership(workspace_id=workspace.id, user_id=user.id, role="system_admin"))
        session.add(AuditEvent(id=str(uuid4()), workspace_id=workspace.id,
                               event_type="auth.admin_provisioned", actor_type="system",
                               outcome="success", metadata_json={"user_id": user.id}))
        session.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--initialize", action="store_true", help="Initialize a new database schema")
    parser.add_argument("--allow-short-password", action="store_true", help="Explicit temporary-password exception")
    args = parser.parse_args()
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Confirm password: "):
        parser.error("Passwords do not match")
    if args.allow_short_password:
        print("Warning: temporary short password enabled; change it before real public use.")
    database = create_database(args.database_url)
    try:
        database.ensure_schema(auto_create=args.initialize)
        provision_admin(database, Settings(auth_required=True), args.username, password,
                        allow_short_password=args.allow_short_password)
    except ValueError as error:
        parser.error(str(error))
    finally:
        database.dispose()
    print("Account created; no existing account was modified.")


if __name__ == "__main__":
    main()
