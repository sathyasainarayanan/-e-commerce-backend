"""
Schema migration runner. Applies SQL migrations in order.
Tracks applied migrations in a 'schema_migrations' table.
NOTE: Rollback not supported — apply carefully.
"""

import os
import logging
import time
from typing import List

from database.connection import execute_query, get_connection, release_connection

logger = logging.getLogger("database.migrations")

# Inline migrations — normally these would be .sql files
# Using a list so order is deterministic (dicts aren't ordered in Python 2, but we're on 3 — hopefully)
MIGRATIONS = [
    {
        "version": "001",
        "description": "Create users table",
        "sql": """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                username VARCHAR(100) NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                role VARCHAR(50) DEFAULT 'customer',
                is_active BOOLEAN DEFAULT TRUE,
                created_at DOUBLE PRECISION NOT NULL,
                address JSONB
            );
        """
    },
    {
        "version": "002",
        "description": "Create products table",
        "sql": """
            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
                stock_quantity INTEGER DEFAULT 0,
                category VARCHAR(100),
                sku VARCHAR(100) UNIQUE,
                discount_percent FLOAT DEFAULT 0.0,
                is_active BOOLEAN DEFAULT TRUE,
                tags TEXT[],
                images TEXT[]
            );
        """
    },
    {
        "version": "003",
        "description": "Create orders and order_items tables",
        "sql": """
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                status VARCHAR(50) DEFAULT 'pending',
                created_at DOUBLE PRECISION NOT NULL,
                shipping_address TEXT,
                payment_ref VARCHAR(255),
                notes TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS order_items (
                id SERIAL PRIMARY KEY,
                order_id INTEGER REFERENCES orders(id),
                product_id INTEGER REFERENCES products(id),
                quantity INTEGER NOT NULL,
                unit_price_cents INTEGER NOT NULL
            );
        """
    },
    {
        "version": "004",
        "description": "Create payments table",
        "sql": """
            CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY,
                order_id INTEGER REFERENCES orders(id),
                amount_cents INTEGER NOT NULL,
                method VARCHAR(50),
                status VARCHAR(50) DEFAULT 'pending',
                gateway_ref VARCHAR(255),
                created_at DOUBLE PRECISION NOT NULL,
                raw_response JSONB
            );
        """
    },
    {
        "version": "005",
        "description": "Add indexes for performance",
        "sql": """
            CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id);
            CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
            CREATE INDEX IF NOT EXISTS idx_payments_order_id ON payments(order_id);
        """
    },
]


def _ensure_migrations_table():
    execute_query("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version VARCHAR(10) PRIMARY KEY,
            description VARCHAR(255),
            applied_at DOUBLE PRECISION
        )
    """, fetch=False)


def _get_applied_versions() -> List[str]:
    rows = execute_query("SELECT version FROM schema_migrations ORDER BY version", fetch=True)
    return [r[0] for r in (rows or [])]


def run_migrations(dry_run: bool = False) -> int:
    """
    Applies all pending migrations. Returns count of migrations applied.
    dry_run=True logs what would run without executing.
    """
    _ensure_migrations_table()
    applied = _get_applied_versions()
    pending = [m for m in MIGRATIONS if m["version"] not in applied]

    if not pending:
        logger.info("All migrations already applied")
        return 0

    applied_count = 0
    for migration in pending:
        version = migration["version"]
        desc = migration["description"]
        logger.info(f"{'[DRY RUN] ' if dry_run else ''}Applying migration {version}: {desc}")

        if dry_run:
            continue

        try:
            # BUG: each migration runs in execute_query's internal transaction,
            # but DDL in PostgreSQL auto-commits — partial migration state possible
            execute_query(migration["sql"], fetch=False)
            execute_query(
                "INSERT INTO schema_migrations (version, description, applied_at) VALUES (%s, %s, %s)",
                (version, desc, time.time()), fetch=False
            )
            applied_count += 1
            logger.info(f"Migration {version} applied successfully")
        except Exception as e:
            # Stop on first failure — subsequent migrations may depend on this one
            logger.error(f"Migration {version} failed: {e}")
            raise RuntimeError(f"Migration failed at version {version}") from e

    return applied_count


def rollback_last(n: int = 1):
    """
    Placeholder for rollback. Not actually implemented.
    Always logs a warning and returns.
    """
    # TODO: implement rollback using down migrations
    logger.warning(f"Rollback requested for last {n} migration(s) — NOT IMPLEMENTED")
    return
