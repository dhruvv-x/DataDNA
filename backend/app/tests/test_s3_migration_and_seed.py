"""S3: migration 0002 constraints and the seed_dean script."""
import hashlib
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from psycopg import errors

from app.core import security
from app.core.seed_dean import SeedError, create_dean, main as seed_main
from app.tests.api_fixtures import PASSWORD, make_department, make_user, uid
from app.tests.pg_fixtures import pg, pg_url  # noqa: F401

NOW = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)


def token_hash(text="t"):
    return hashlib.sha256(text.encode()).hexdigest()


# ---------------------------------------------------------------- migration 0002
def test_migration_0002_is_recorded(pg):
    row = pg.execute("SELECT 1 FROM schema_migrations WHERE version = '0002_auth'").fetchone()
    assert row is not None


def test_new_user_columns_exist_with_safe_defaults(pg):
    dep = make_department(pg)
    user = make_user(pg, "FACULTY", dep["id"])
    row = pg.execute("SELECT * FROM users WHERE id = %s", (user["id"],)).fetchone()
    assert row["failed_login_count"] == 0
    assert row["locked_until"] is None
    assert row["last_login_at"] is None
    assert row["must_change_password"] is False
    assert row["password_changed_at"] is not None


def test_failed_login_count_cannot_be_negative(pg):
    dep = make_department(pg)
    user = make_user(pg, "FACULTY", dep["id"])
    with pytest.raises(errors.CheckViolation):
        pg.execute("UPDATE users SET failed_login_count = -1 WHERE id = %s", (user["id"],))


def test_refresh_token_row_roundtrip(pg):
    dep = make_department(pg)
    user = make_user(pg, "FACULTY", dep["id"])
    pg.execute(
        "INSERT INTO refresh_tokens (user_id, token_hash, issued_at, expires_at) VALUES (%s, %s, %s, %s)",
        (user["id"], token_hash(), NOW, NOW + timedelta(days=7)),
    )
    row = pg.execute("SELECT * FROM refresh_tokens WHERE user_id = %s", (user["id"],)).fetchone()
    assert row["used_at"] is None and row["revoked_at"] is None


def test_refresh_token_hash_must_be_unique(pg):
    dep = make_department(pg)
    user = make_user(pg, "FACULTY", dep["id"])
    args = (user["id"], token_hash("same"), NOW, NOW + timedelta(days=7))
    sql = "INSERT INTO refresh_tokens (user_id, token_hash, issued_at, expires_at) VALUES (%s, %s, %s, %s)"
    pg.execute(sql, args)
    with pytest.raises(errors.UniqueViolation):
        pg.execute(sql, args)


def test_refresh_token_hash_must_look_like_sha256(pg):
    dep = make_department(pg)
    user = make_user(pg, "FACULTY", dep["id"])
    with pytest.raises(errors.CheckViolation):
        pg.execute(
            "INSERT INTO refresh_tokens (user_id, token_hash, issued_at, expires_at) VALUES (%s, %s, %s, %s)",
            (user["id"], "plain-token-text", NOW, NOW + timedelta(days=7)),
        )


def test_refresh_token_must_expire_after_it_was_issued(pg):
    dep = make_department(pg)
    user = make_user(pg, "FACULTY", dep["id"])
    with pytest.raises(errors.CheckViolation):
        pg.execute(
            "INSERT INTO refresh_tokens (user_id, token_hash, issued_at, expires_at) VALUES (%s, %s, %s, %s)",
            (user["id"], token_hash("b"), NOW, NOW - timedelta(days=1)),
        )


def test_refresh_token_needs_a_real_user(pg):
    with pytest.raises(errors.ForeignKeyViolation):
        pg.execute(
            "INSERT INTO refresh_tokens (user_id, token_hash, issued_at, expires_at) VALUES (gen_random_uuid(), %s, %s, %s)",
            (token_hash("c"), NOW, NOW + timedelta(days=7)),
        )


# ---------------------------------------------------------------- seed_dean
def test_create_dean_makes_active_dean_without_department(pg):
    new_id = create_dean(pg, email="  Dean.One@PPSU.example ", full_name=" Dean One ", password=PASSWORD)
    row = pg.execute("SELECT * FROM users WHERE id = %s", (new_id,)).fetchone()
    assert row["email"] == "dean.one@ppsu.example"
    assert row["full_name"] == "Dean One"
    assert row["role"] == "DEAN" and row["department_id"] is None
    assert row["is_active"] is True and row["must_change_password"] is False
    assert security.verify_password(PASSWORD, row["password_hash"])
    assert PASSWORD not in row["password_hash"]


def test_create_dean_writes_audit_entry(pg):
    new_id = create_dean(pg, email=f"d{uid()}@ppsu.example", full_name="Dean", password=PASSWORD)
    row = pg.execute(
        "SELECT * FROM audit_log WHERE entity_id = %s AND action = 'USER_CREATED'", (str(new_id),)
    ).fetchone()
    assert row["actor_id"] is None
    assert row["payload"]["via"] == "seed_dean"
    assert PASSWORD not in str(row["payload"])


def test_second_active_dean_refused_by_default(pg):
    create_dean(pg, email=f"d{uid()}@ppsu.example", full_name="Dean A", password=PASSWORD)
    with pytest.raises(SeedError, match="already exists"):
        create_dean(pg, email=f"d{uid()}@ppsu.example", full_name="Dean B", password=PASSWORD)


def test_second_dean_allowed_with_flag(pg):
    create_dean(pg, email=f"d{uid()}@ppsu.example", full_name="Dean A", password=PASSWORD)
    create_dean(pg, email=f"d{uid()}@ppsu.example", full_name="Dean B", password=PASSWORD, allow_additional=True)
    n = pg.execute("SELECT count(*) AS n FROM users WHERE role = 'DEAN' AND is_active").fetchone()["n"]
    assert n == 2


def test_inactive_dean_does_not_block_a_new_one(pg):
    make_user(pg, "DEAN", active=False)
    create_dean(pg, email=f"d{uid()}@ppsu.example", full_name="Dean", password=PASSWORD)


def test_weak_password_refused(pg):
    with pytest.raises(SeedError):
        create_dean(pg, email=f"d{uid()}@ppsu.example", full_name="Dean", password="short")


def test_bad_email_and_empty_name_refused(pg):
    with pytest.raises(SeedError):
        create_dean(pg, email="not-an-email", full_name="Dean", password=PASSWORD)
    with pytest.raises(SeedError):
        create_dean(pg, email=f"d{uid()}@ppsu.example", full_name="   ", password=PASSWORD)


def test_duplicate_email_refused(pg):
    email = f"d{uid()}@ppsu.example"
    make_user(pg, "DEAN", email=email, active=False)
    with pytest.raises(SeedError, match="email already exists"):
        create_dean(pg, email=email, full_name="Dean", password=PASSWORD)


class _FakeConn:
    """Stands in for a connection so the CLI test needs no commit on the shared test transaction."""

    def __init__(self, real):
        self.real, self.committed, self.closed = real, False, False

    def execute(self, *a, **k):
        return self.real.execute(*a, **k)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.real.rollback()

    def close(self):
        self.closed = True


def _answers(*values):
    it = iter(values)
    return lambda prompt: next(it)


def test_cli_creates_dean_and_commits(pg, capsys):
    fake = _FakeConn(pg)
    code = seed_main(
        ["--email", f"cli{uid()}@ppsu.example", "--name", "Dean Cli"],
        getpass_fn=_answers(PASSWORD, PASSWORD), connect_fn=lambda: fake,
    )
    assert code == 0 and fake.committed and fake.closed
    assert "Dean created" in capsys.readouterr().out


def test_cli_password_mismatch_does_nothing(pg, capsys):
    fake = _FakeConn(pg)
    code = seed_main(
        ["--email", f"cli{uid()}@ppsu.example", "--name", "Dean Cli"],
        getpass_fn=_answers(PASSWORD, PASSWORD + "x"), connect_fn=lambda: fake,
    )
    assert code == 1 and not fake.committed
    assert "do not match" in capsys.readouterr().err


def test_cli_refuses_when_dean_exists(pg, capsys):
    make_user(pg, "DEAN")
    fake = _FakeConn(pg)
    code = seed_main(
        ["--email", f"cli{uid()}@ppsu.example", "--name", "Dean Cli"],
        getpass_fn=_answers(PASSWORD, PASSWORD), connect_fn=lambda: fake,
    )
    assert code == 1 and not fake.committed
    assert "already exists" in capsys.readouterr().err


def test_cli_reports_unreachable_database(capsys):
    def boom():
        raise psycopg.OperationalError("connection refused")

    code = seed_main(
        ["--email", "x@ppsu.example", "--name", "X"], getpass_fn=_answers(PASSWORD, PASSWORD), connect_fn=boom
    )
    assert code == 1
    assert "cannot reach PostgreSQL" in capsys.readouterr().err
