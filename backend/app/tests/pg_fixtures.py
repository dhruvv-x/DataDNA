"""
Shared fixtures for tests that need a real PostgreSQL.

Safety: these fixtures DROP the whole public schema, so they only ever touch a database
whose name ends in "_test". By default that is <your database name>_test, created on demand.
"""
import os

import psycopg
from psycopg import sql
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from app.core.migrate import migrate
from app.core.pg import database_url

HELP = (
    "PostgreSQL is not reachable. Start it with:\n"
    "    cd ~/datadna && docker compose up -d db\n"
    "and wait about 10 seconds. Original error: {err}"
)


def test_database_url() -> str:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        url = explicit
    else:
        info = conninfo_to_dict(database_url())
        name = info.get("dbname") or "compliance"
        info["dbname"] = name if name.endswith("_test") else name + "_test"
        url = make_conninfo(**info)
    dbname = conninfo_to_dict(url).get("dbname", "")
    if not dbname.endswith("_test"):
        raise RuntimeError(f"Refusing to run tests on database '{dbname}': name must end with _test")
    return url


def _ensure_database_exists(url: str) -> None:
    info = conninfo_to_dict(url)
    name = info["dbname"]
    admin = make_conninfo(**{**info, "dbname": "postgres"})
    with psycopg.connect(admin, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
        if not exists:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


@pytest.fixture(scope="session")
def pg_url():
    url = test_database_url()
    try:
        _ensure_database_exists(url)
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("DROP SCHEMA public CASCADE")
            conn.execute("CREATE SCHEMA public")
    except psycopg.OperationalError as exc:
        pytest.fail(HELP.format(err=exc), pytrace=False)
    migrate(url)
    return url


@pytest.fixture
def pg(pg_url):
    """A connection whose work is rolled back after every test."""
    conn = psycopg.connect(pg_url, row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
