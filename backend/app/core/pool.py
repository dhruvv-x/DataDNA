"""
PostgreSQL connection pool (S3). Created on first use, not at import time.

Size: 2 to 10 connections. One request borrows one connection (see api/deps.py get_db).
"""
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.core.pg import database_url

OPEN_TIMEOUT = 10  # seconds to wait for the first connections before giving up

_pool: ConnectionPool | None = None
_pool_url: str | None = None


def get_pool() -> ConnectionPool:
    global _pool, _pool_url
    url = database_url()
    if _pool is not None and _pool_url != url:
        close_pool()
    if _pool is None:
        pool = ConnectionPool(
            conninfo=url,
            min_size=2,
            max_size=10,
            kwargs={"row_factory": dict_row},
            open=False,
        )
        try:
            pool.open(wait=True, timeout=OPEN_TIMEOUT)
        except Exception:
            pool.close()
            raise
        _pool, _pool_url = pool, url
    return _pool


def close_pool() -> None:
    global _pool, _pool_url
    if _pool is not None:
        _pool.close()
    _pool = None
    _pool_url = None
