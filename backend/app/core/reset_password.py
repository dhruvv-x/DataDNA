"""
Server-side password reset (S3). For the case nobody can log in to use the Dean's reset button,
for example the only Dean forgot their password.

Run:   cd ~/datadna/backend && source venv/bin/activate
       python -m app.core.reset_password --email dean@ppsu.ac.in
It asks for the new password (typing is hidden). It also unlocks the account, ends all its sessions
and writes an audit entry. It does NOT reactivate a deactivated account.
Anyone who can run this already controls the server and database, so it needs no login.
"""
import argparse
import getpass
import sys
import uuid

import psycopg

from app.core import auditlog, security
from app.core.pg import connect


class ResetError(Exception):
    pass


def reset_user_password(conn, *, email: str, password: str) -> uuid.UUID:
    """Sets the new password. The caller commits."""
    email = email.strip().lower()
    try:
        security.validate_new_password(password, email=email)
    except security.PasswordPolicyError as exc:
        raise ResetError(str(exc))
    if "\x00" in email:
        raise ResetError("No user with this email.")
    user = conn.execute("SELECT id, role, is_active FROM users WHERE email = %s FOR UPDATE", (email,)).fetchone()
    if user is None:
        raise ResetError("No user with this email.")
    conn.execute(
        """
        UPDATE users
        SET password_hash = %s, password_changed_at = clock_timestamp(), must_change_password = false,
            failed_login_count = 0, locked_until = NULL
        WHERE id = %s
        """,
        (security.hash_password(password), user["id"]),
    )
    conn.execute(
        "UPDATE refresh_tokens SET revoked_at = clock_timestamp() WHERE user_id = %s AND revoked_at IS NULL", (user["id"],)
    )
    auditlog.write(
        conn, actor_id=None, actor_role=None, action="PASSWORD_RESET", entity_type="user",
        entity_id=user["id"], payload={"via": "server_cli", "target_role": user["role"]},
    )
    return user["id"]


def main(argv=None, getpass_fn=getpass.getpass, connect_fn=connect) -> int:
    parser = argparse.ArgumentParser(description="Set a new password for an existing user (server-side).")
    parser.add_argument("--email", required=True)
    args = parser.parse_args(argv)

    password = getpass_fn("New password: ")
    if password != getpass_fn("Repeat new password: "):
        print("ERROR: the two passwords do not match.", file=sys.stderr)
        return 1
    try:
        conn = connect_fn()
    except psycopg.Error as exc:
        print(f"ERROR: cannot reach PostgreSQL: {exc}", file=sys.stderr)
        return 1
    try:
        reset_user_password(conn, email=args.email, password=password)
        conn.commit()
    except ResetError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except psycopg.Error as exc:
        print(f"ERROR: database problem: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    print(f"Password updated for {args.email.strip().lower()}. All their sessions were ended.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
