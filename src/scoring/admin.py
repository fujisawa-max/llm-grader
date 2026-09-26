"""Administrative bootstrap CLI.

Usage::

    python -m scoring.admin create-admin --email admin@example.com

The password is read from ``--password`` or ``ADMIN_INITIAL_PASSWORD`` and is
never printed.  Existing accounts are not replaced; an existing email exits
without creating a duplicate.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

from sqlalchemy import select

from .auth import hash_password, normalize_email, validate_password
from .db import create_session_factory, init_database
from .db.models import DomainEvent, User


def create_admin(email: str, password: str, display_name: str = "Administrator", db_url: str | None = None):
    email = normalize_email(email)
    validate_password(password)
    # This is intentionally non-destructive for local bootstrap and test DBs.
    engine, factory = create_session_factory(db_url or os.getenv("LLM_GRADER_DATABASE_URL", "sqlite:///llm_grader_api.db"))
    init_database(engine)
    with factory() as session:
        existing = session.scalars(select(User).where(User.email == email).limit(1)).first()
        if existing:
            if existing.role != "admin":
                raise SystemExit("an account with this email already exists and is not an admin")
            return existing.id, False
        user = User(display_name=display_name, email=email, role="admin",
                    password_hash=hash_password(password), is_active=True,
                    must_change_password=False)
        session.add(user)
        session.flush()
        session.add(DomainEvent(entity_type="user", entity_id=user.id,
                                event_type="admin_bootstrapped", payload={"email": email}))
        session.commit()
        return user.id, True


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m scoring.admin")
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("create-admin")
    command.add_argument("--email", default=os.getenv("ADMIN_EMAIL"))
    command.add_argument("--display-name", default="Administrator")
    command.add_argument("--password", default=os.getenv("ADMIN_INITIAL_PASSWORD"))
    command.add_argument("--database-url", default=os.getenv("LLM_GRADER_DATABASE_URL", "sqlite:///llm_grader_api.db"))
    args = parser.parse_args(argv)
    if not args.email:
        parser.error("--email or ADMIN_EMAIL is required")
    password = args.password or getpass.getpass("Initial admin password: ")
    try:
        user_id, created = create_admin(args.email, password, args.display_name, args.database_url)
    except (ValueError, SystemExit) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print("admin already exists" if not created else "admin created")
    print(f"user_id={user_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
