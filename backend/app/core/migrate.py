"""
Tiny migration runner (S2).

Applies backend/migrations/NNNN_name.sql files in order, each inside one transaction,
and remembers them in the schema_migrations table together with a checksum.
If an already-applied file is edited later, it stops with an error instead of
silently drifting. To change the schema, add a new file.

Run:  python -m app.core.migrate
"""
import hashlib
import sys
from pathlib import Path

import psycopg

from app.core.pg import database_url

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
_LOCK_KEY = 727_001  # any fixed number; stops two runners migrating at the same time


class MigrationError(Exception):
    pass


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def migrate(url: str | None = None, migrations_dir: Path | None = None) -> list[str]:
    """Apply all pending migrations. Returns the list of versions applied now."""
    directory = Path(migrations_dir) if migrations_dir else MIGRATIONS_DIR
    files = sorted(directory.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    applied_now: list[str] = []

    with psycopg.connect(url or database_url(), autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (_LOCK_KEY,))
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version     text PRIMARY KEY,
                    checksum    text NOT NULL,
                    applied_at  timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            applied = dict(conn.execute("SELECT version, checksum FROM schema_migrations").fetchall())

            on_disk = {p.stem for p in files}
            missing = sorted(set(applied) - on_disk)
            if missing:
                raise MigrationError(
                    f"Migration file(s) missing from disk but already applied: {', '.join(missing)}"
                )

            for path in files:
                version = path.stem
                sql = path.read_text(encoding="utf-8")
                checksum = _checksum(sql)
                if version in applied:
                    if applied[version] != checksum:
                        raise MigrationError(
                            f"{version} was changed after it was applied. "
                            "Never edit an applied migration; add a new one instead."
                        )
                    continue
                with conn.transaction():
                    conn.execute(sql)
                    conn.execute(
                        "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                        (version, checksum),
                    )
                applied_now.append(version)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (_LOCK_KEY,))
    return applied_now


def main() -> int:
    try:
        done = migrate()
    except (MigrationError, psycopg.Error) as exc:
        print(f"MIGRATION FAILED: {exc}", file=sys.stderr)
        return 1
    if done:
        print("Applied: " + ", ".join(done))
    else:
        print("Database is up to date. Nothing to apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
