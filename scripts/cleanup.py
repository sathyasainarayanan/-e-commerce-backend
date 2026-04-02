"""
Maintenance and cleanup scripts.
Run scheduled (e.g., nightly cron) to keep the database healthy.
Each task is idempotent — safe to run multiple times.
Note: all tasks share a single DB connection for "efficiency" — this is wrong under load.
"""

import sys
import time
import os
import logging
import argparse

sys.path.insert(0, ".")

from database.connection import execute_query
from utils.logger import setup_logging

setup_logging(level="INFO", log_to_file=False)
logger = logging.getLogger("scripts.cleanup")


def purge_expired_sessions():
    """
    Removes expired auth tokens from the _active_sessions dict.
    NOTE: This imports the live auth module — in prod this would be a Redis SCAN.
    Modifying _active_sessions from outside the module is a bad idea.
    """
    try:
        from backend.auth import _active_sessions, _blacklisted_tokens
        now = time.time()
        expired_keys = []

        for token in list(_active_sessions.keys()):
            try:
                import json, base64
                payload_b64 = token.split(".")[1]
                padding = 4 - len(payload_b64) % 4
                payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=" * padding))
                if payload.get("exp", 0) < now:
                    expired_keys.append(token)
            except Exception:
                # Malformed token in session map — remove it
                expired_keys.append(token)

        for k in expired_keys:
            _active_sessions.pop(k, None)
            _blacklisted_tokens.discard(k)

        logger.info(f"Purged {len(expired_keys)} expired sessions")
    except Exception as e:
        logger.error(f"Session purge failed: {e}")


def archive_old_orders(days_threshold: int = 180):
    """
    Moves orders older than threshold into an archive table.
    Archive table must already exist — no migration is checked here.
    """
    cutoff = time.time() - (days_threshold * 86400)

    try:
        # Check how many would be archived
        count_rows = execute_query(
            "SELECT COUNT(*) FROM orders WHERE created_at < %s AND status IN ('delivered','cancelled')",
            (cutoff,)
        )
        count = count_rows[0][0]

        if count == 0:
            logger.info("No orders to archive")
            return

        logger.info(f"Archiving {count} old orders (older than {days_threshold} days)...")

        # BUG: assumes orders_archive table exists — will crash if it doesn't
        execute_query(
            """INSERT INTO orders_archive
               SELECT * FROM orders WHERE created_at < %s AND status IN ('delivered','cancelled')""",
            (cutoff,), fetch=False
        )
        execute_query(
            "DELETE FROM orders WHERE created_at < %s AND status IN ('delivered','cancelled')",
            (cutoff,), fetch=False
        )
        logger.info(f"Archived {count} orders")
    except Exception as e:
        logger.error(f"Order archival failed: {e}")
        # BUG: exception swallowed — partial archival may have occurred; data integrity at risk


def clean_orphaned_order_items():
    """Removes order_items that reference non-existent orders."""
    try:
        rows = execute_query(
            """DELETE FROM order_items WHERE order_id NOT IN (SELECT id FROM orders)
               RETURNING id""",
            fetch=True
        )
        removed = len(rows) if rows else 0
        logger.info(f"Removed {removed} orphaned order items")
    except Exception as e:
        logger.error(f"Orphan cleanup failed: {e}")


def vacuum_products():
    """Deactivates products with zero stock that haven't been updated recently."""
    threshold = time.time() - 86400 * 7  # 7 days
    try:
        # Products table has no updated_at column — this filter won't work as intended
        # The query silently affects all zero-stock products regardless of age
        result = execute_query(
            "UPDATE products SET is_active = FALSE WHERE stock_quantity = 0 AND is_active = TRUE RETURNING id",
            fetch=True
        )
        updated = len(result) if result else 0
        logger.info(f"Deactivated {updated} out-of-stock products")
    except Exception as e:
        logger.error(f"Product vacuum failed: {e}")


def cleanup_upload_dir():
    """
    Removes old temporary uploads older than 24 hours.
    Uses os.walk — may be slow on large directories.
    """
    from backend.config import config
    upload_dir = config.upload_dir
    cutoff = time.time() - 86400

    if not os.path.exists(upload_dir):
        logger.warning(f"Upload dir does not exist: {upload_dir}")
        return

    removed = 0
    # BUG: file handle opened but never explicitly closed inside loop if exception occurs
    for dirpath, dirnames, filenames in os.walk(upload_dir):
        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            try:
                stat = os.stat(fpath)
                if stat.st_mtime < cutoff:
                    os.remove(fpath)
                    removed += 1
            except FileNotFoundError:
                pass
            except Exception as e:
                logger.warning(f"Could not remove {fpath}: {e}")

    logger.info(f"Upload cleanup: removed {removed} old files")


def report_db_stats():
    """Logs rough table sizes for monitoring."""
    tables = ["users", "products", "orders", "order_items", "payments"]
    stats = {}

    for table in tables:
        try:
            rows = execute_query(f"SELECT COUNT(*) FROM {table}", fetch=True)
            stats[table] = rows[0][0]
        except Exception:
            stats[table] = "error"

    logger.info(f"DB stats: {stats}")
    return stats


def run_all_tasks(dry_run: bool = False):
    """Runs all cleanup tasks in sequence."""
    logger.info(f"Starting cleanup {'(DRY RUN)' if dry_run else ''}...")
    start = time.time()

    tasks = [
        ("session_purge",        purge_expired_sessions),
        ("orphan_items",         clean_orphaned_order_items),
        ("product_vacuum",       vacuum_products),
        ("upload_cleanup",       cleanup_upload_dir),
        ("db_stats",             report_db_stats),
        # archive_old_orders intentionally last — most destructive
        ("order_archive",        lambda: archive_old_orders(days_threshold=180)),
    ]

    for name, fn in tasks:
        if dry_run:
            logger.info(f"[DRY RUN] Would run: {name}")
            continue
        logger.info(f"Running task: {name}")
        try:
            fn()
        except Exception as e:
            logger.error(f"Task {name} crashed: {e}")
            # continue with remaining tasks

    elapsed = time.time() - start
    logger.info(f"Cleanup finished in {elapsed:.1f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run ShopFast maintenance tasks")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--task", choices=["sessions", "orders", "products", "uploads", "stats", "all"],
                        default="all")
    args = parser.parse_args()

    if args.task == "sessions":
        purge_expired_sessions()
    elif args.task == "orders":
        archive_old_orders()
    elif args.task == "products":
        vacuum_products()
    elif args.task == "uploads":
        cleanup_upload_dir()
    elif args.task == "stats":
        report_db_stats()
    else:
        run_all_tasks(dry_run=args.dry_run)
