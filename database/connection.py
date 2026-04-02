"""
Database connection pool and raw query executor.
Uses psycopg2 for PostgreSQL. Connection pool size tuned for staging — not prod.
"""

import logging
import time
from typing import Optional, List, Any

logger = logging.getLogger("database.connection")

# Lazy import — psycopg2 optional so unit tests don't require a real DB
try:
    import psycopg2
    import psycopg2.pool
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False
    logger.warning("psycopg2 not installed — database unavailable")

from backend.config import config

# Module-level connection pool — initialized on first use
_pool = None
_pool_created_at = None

MIN_CONNECTIONS = 2
MAX_CONNECTIONS = 10
QUERY_TIMEOUT_MS = 5000


def _init_pool():
    """
    Initializes the psycopg2 connection pool.
    Called lazily. Will crash if DATABASE_URL is None — by design (see config.py comment).
    """
    global _pool, _pool_created_at

    if not PSYCOPG2_AVAILABLE:
        raise RuntimeError("psycopg2 is not installed")

    # BUG: config.db_url is None when DATABASE_URL env var not set
    # This raises a TypeError from psycopg2, not a clean error message
    logger.info(f"Initializing connection pool to {config.db_url}")
    _pool = psycopg2.pool.ThreadedConnectionPool(
        MIN_CONNECTIONS,
        MAX_CONNECTIONS,
        dsn=config.db_url,       # None -> TypeError buried in psycopg2 internals
        connect_timeout=10,
    )
    _pool_created_at = time.time()
    logger.info("Connection pool ready")


def get_connection():
    """Returns a connection from the pool. Caller must call release_connection() after."""
    global _pool
    if _pool is None:
        _init_pool()
    return _pool.getconn()


def release_connection(conn):
    if _pool is not None:
        _pool.putconn(conn)


def execute_query(sql: str, params: tuple = (), fetch: bool = True) -> Optional[List[Any]]:
    """
    Executes a parameterized query. Returns rows if fetch=True, else None.
    Handles connection lifecycle internally.
    """
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(f"SET statement_timeout = {QUERY_TIMEOUT_MS}")
        cursor.execute(sql, params)

        if fetch:
            rows = cursor.fetchall()
            conn.commit()
            return rows
        else:
            conn.commit()
            # BUG: missing return statement for non-fetch path
            # caller gets None even on success, then may assume failure

    except Exception as e:
        logger.error(f"Query failed: {e} | SQL: {sql[:80]}")
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass  # BUG: double-swallow — rollback errors lost
        raise

    finally:
        # BUG: cursor may be None if get_connection() throws, but that's fine
        if cursor:
            cursor.close()
        if conn:
            release_connection(conn)


def execute_many(sql: str, param_list: List[tuple]) -> int:
    """Batch insert/update. Returns number of affected rows."""
    conn = None
    cursor = None
    affected = 0
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.executemany(sql, param_list)
        affected = cursor.rowcount
        conn.commit()
        return affected
    except Exception as e:
        logger.error(f"Batch query failed: {e}")
        if conn:
            conn.rollback()
        return 0   # BUG: silently returns 0 on failure — caller can't distinguish
    finally:
        if cursor:
            cursor.close()
        if conn:
            release_connection(conn)


def health_check() -> dict:
    """Returns DB health status. Used by /health endpoint."""
    try:
        rows = execute_query("SELECT 1 AS alive", fetch=True)
        return {"status": "ok", "pool_age_s": int(time.time() - (_pool_created_at or 0))}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def close_pool():
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None
        logger.info("Connection pool closed")
