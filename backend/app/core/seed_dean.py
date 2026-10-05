"""
Creates the first Dean from the command line (S3). The Dean is never created through the API.

Run:   cd ~/datadna/backend && source venv/bin/activate
       python -m app.core.seed_dean --email dean@ppsu.ac.in --name "Dean Name"
It asks for the password (typing is hidden). If an active Dean already exists it refuses,
unless you add --add-another (use that when a second Dean is really needed).
"""
import argparse
import getpass
import re
import sys
import uuid

import psycopg

from app.core import auditlog, security
from app.core.pg import connect

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SeedError(Exception):
    pass


def create_dean(conn, *, email: str, full_name: str, password: str, allow_additional: bool = False) -> uuid.UUID:
    """Inserts the Dean. The caller commits."""
    email = email.strip().lower()
    full_name = full_name.strip()
    if not _EMAIL_RE.match(email):
        raise SeedError("Enter a valid email address.")
    if not full_name:
        raise SeedError("Name cannot be empty.")
    try:
        security.validate_new_password(password, email=email)
    except security.PasswordPolicyError as exc:
        raise SeedError(str(exc))
    if not allow_additional:
        existing = conn.execute("SELECT 1 FROM users WHERE role = 'DEAN' AND is_active").fetchone()
        if existing:
            raise SeedError("An active Dean already exists. Use --add-another if you really need one more.")
    try:
        new_id = conn.execute(
            """
            INSERT INTO users (email, password_hash, full_name, role, department_id, must_change_password)
            VALUES (%s, %s, %s, 'DEAN', NULL, false)
            RETURNING id
            """,
            (email, security.hash_password(password), full_name),
        ).fetchone()["id"]
    except psycopg.errors.UniqueViolation:
        conn.rollback()
        raise SeedError("A user with this email already exists.")
    auditlog.write(
        conn, actor_id=None, actor_role=None, action="USER_CREATED", entity_type="user",
        entity_id=new_id, payload={"role": "DEAN", "via": "seed_dean"},
    )
    return new_id


def main(argv=None, getpass_fn=getpass.getpass, connect_fn=connect) -> int:
    parser = argparse.ArgumentParser(description="Create the first Dean account.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--add-another", action="store_true", help="allow a second active Dean")
    args = parser.parse_args(argv)

    password = getpass_fn("Password: ")
    if password != getpass_fn("Repeat password: "):
        print("ERROR: the two passwords do not match.", file=sys.stderr)
        return 1
    try:
        conn = connect_fn()
    except psycopg.Error as exc:
        print(f"ERROR: cannot reach PostgreSQL: {exc}", file=sys.stderr)
        return 1
    try:
        create_dean(conn, email=args.email, full_name=args.name, password=password,
                    allow_additional=args.add_another)
        conn.commit()
    except SeedError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except psycopg.Error as exc:
        print(f"ERROR: database problem (did you run python -m app.core.migrate?): {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    print(f"Dean created: {args.email.strip().lower()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
