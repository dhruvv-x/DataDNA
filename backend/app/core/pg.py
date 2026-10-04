"""
PostgreSQL connection helper (S2).

The address comes from the DATABASE_URL environment variable. The default matches
docker-compose.yml, so it works on your laptop with no setup.
"""
import os
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

DEFAULT_DATABASE_URL = "postgresql://compliance:compliance_dev@localhost:5432/compliance"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def connect(url: str | None = None) -> psycopg.Connection:
    """Open a new connection. Rows come back as dicts. Caller must close it."""
    return psycopg.connect(url or database_url(), row_factory=dict_row)


@contextmanager
def transaction(url: str | None = None):
    """
    One connection, one transaction. Commits when the block ends normally,
    rolls everything back if an exception escapes, always closes the connection.
    """
    conn = connect(url)
    try:
        with conn:
            yield conn
    finally:
        conn.close()
