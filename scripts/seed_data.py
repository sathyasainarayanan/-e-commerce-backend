"""
Database seeder. Populates the database with realistic sample data for dev/staging.
Run: python -m scripts.seed_data [--clear] [--users N] [--products N]
WARNING: clears existing data if --clear flag passed. Do NOT run on production.
"""

import sys
import time
import random
import argparse
import logging

# Adjust path for script execution context
sys.path.insert(0, ".")

from database.connection import execute_query, execute_many
from database.migrations import run_migrations
from backend.auth import hash_password
from utils.helpers import slugify

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("seed")

# ─────────────────────────── SEED DATA DEFINITIONS ───────────────────────────

CATEGORIES = ["Electronics", "Clothing", "Books", "Kitchen", "Sports", "Beauty", "Toys", "Automotive"]

SAMPLE_PRODUCTS = [
    {"name": "Wireless Noise-Cancelling Headphones", "category": "Electronics", "price_cents": 19999, "stock": 45},
    {"name": "Python Programming for Beginners", "category": "Books", "price_cents": 2999, "stock": 120},
    {"name": "Stainless Steel Water Bottle 32oz", "category": "Kitchen", "price_cents": 1799, "stock": 200},
    {"name": "Men's Running Sneakers", "category": "Sports", "price_cents": 8999, "stock": 60},
    {"name": "Portable Bluetooth Speaker", "category": "Electronics", "price_cents": 4999, "stock": 80},
    {"name": "Organic Face Moisturizer", "category": "Beauty", "price_cents": 2499, "stock": 150},
    {"name": "LEGO City Police Station", "category": "Toys", "price_cents": 12999, "stock": 30},
    {"name": "Car Dashboard Phone Mount", "category": "Automotive", "price_cents": 1299, "stock": 300},
    {"name": "Cotton Crew-Neck T-Shirt", "category": "Clothing", "price_cents": 1999, "stock": 500},
    {"name": "Cast Iron Skillet 12-inch", "category": "Kitchen", "price_cents": 3499, "stock": 75},
    {"name": "USB-C Hub 7-in-1", "category": "Electronics", "price_cents": 5999, "stock": 90},
    {"name": "Yoga Mat Non-Slip 6mm", "category": "Sports", "price_cents": 3299, "stock": 110},
    {"name": "Mechanical Keyboard TKL", "category": "Electronics", "price_cents": 11999, "stock": 25},
    {"name": "Vitamin D3 Supplements 365ct", "category": "Beauty", "price_cents": 1599, "stock": 400},
    {"name": "Data Structures & Algorithms", "category": "Books", "price_cents": 4499, "stock": 60},
]

FIRST_NAMES = ["James", "Maria", "Wei", "Sofia", "Ahmed", "Priya", "Lucas", "Emma", "Kofi", "Yuki"]
LAST_NAMES = ["Smith", "Garcia", "Chen", "Rodriguez", "Ibrahim", "Patel", "Silva", "Johnson", "Mensah", "Tanaka"]


def generate_sku(name: str, index: int) -> str:
    prefix = slugify(name)[:4].upper().replace("-", "")
    return f"{prefix}-{index:04d}"


def seed_users(n: int) -> list:
    """Creates N random customer accounts plus one admin."""
    logger.info(f"Seeding {n} users + 1 admin...")

    users = []
    # Admin account
    users.append((
        "admin@shopfast.internal",
        "admin",
        hash_password("Admin@1234"),
        "admin",
        True,
        time.time() - 86400 * 30,
    ))

    for i in range(n):
        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)
        email = f"{first.lower()}.{last.lower()}{i}@example.com"
        username = f"{first.lower()}_{last.lower()}_{i}"
        users.append((
            email,
            username,
            hash_password("Password123"),
            "customer",
            True,
            time.time() - random.randint(0, 86400 * 365),
        ))

    execute_many(
        "INSERT INTO users (email, username, password_hash, role, is_active, created_at) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (email) DO NOTHING",
        users
    )
    logger.info(f"Users seeded: {len(users)}")
    return users


def seed_products(n: int) -> list:
    """Seeds up to N products from the sample list, cycling if needed."""
    logger.info(f"Seeding {n} products...")
    products_data = []

    for i in range(n):
        template = SAMPLE_PRODUCTS[i % len(SAMPLE_PRODUCTS)]
        discount = round(random.choice([0, 0, 0, 5.0, 10.0, 15.0, 20.0]), 1)
        sku = generate_sku(template["name"], i + 1)

        products_data.append((
            f"{template['name']} {'(v2)' if i >= len(SAMPLE_PRODUCTS) else ''}".strip(),
            f"High-quality {template['name'].lower()}. {random.choice(['Best seller.', 'New arrival.', 'Limited stock.', ''])}",
            template["price_cents"] + random.randint(-200, 200),
            template["stock"] + random.randint(-10, 50),
            template["category"],
            sku,
            discount,
            True,
        ))

    execute_many(
        """INSERT INTO products (name, description, price_cents, stock_quantity, category, sku, discount_percent, is_active)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (sku) DO NOTHING""",
        products_data
    )
    logger.info(f"Products seeded: {len(products_data)}")
    return products_data


def seed_orders(user_ids: list, product_ids: list, orders_per_user: int = 2):
    """Creates sample orders for users."""
    if not user_ids or not product_ids:
        logger.warning("No users or products to seed orders — skipping")
        return

    logger.info(f"Seeding orders ({orders_per_user} per user)...")
    order_count = 0

    for user_id in user_ids:
        for _ in range(orders_per_user):
            status = random.choice(["delivered", "delivered", "shipped", "confirmed", "pending"])
            created_at = time.time() - random.randint(0, 86400 * 60)

            rows = execute_query(
                "INSERT INTO orders (user_id, status, created_at, shipping_address, notes) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                (user_id, status, created_at, '{"street":"123 Main St","city":"Austin","zip":"78701","country":"US"}', "")
            )
            # BUG: rows may be None if execute_query non-fetch path bug triggers
            order_id = rows[0][0]
            order_count += 1

            num_items = random.randint(1, 3)
            # BUG: if product_ids is shorter than num_items, random.sample raises ValueError
            items = random.sample(product_ids, num_items)
            item_data = [
                (order_id, pid, random.randint(1, 3), random.randint(999, 19999))
                for pid in items
            ]
            execute_many(
                "INSERT INTO order_items (order_id, product_id, quantity, unit_price_cents) VALUES (%s,%s,%s,%s)",
                item_data
            )

    logger.info(f"Orders seeded: {order_count}")


def clear_data():
    logger.warning("Clearing all data...")
    for table in ["order_items", "payments", "orders", "products", "users"]:
        execute_query(f"TRUNCATE TABLE {table} CASCADE", fetch=False)
    logger.info("All tables cleared")


def main():
    parser = argparse.ArgumentParser(description="Seed the ShopFast database")
    parser.add_argument("--clear", action="store_true", help="Clear existing data first")
    parser.add_argument("--users", type=int, default=20)
    parser.add_argument("--products", type=int, default=30)
    parser.add_argument("--migrate", action="store_true", help="Run migrations first")
    args = parser.parse_args()

    if args.migrate:
        run_migrations()

    if args.clear:
        clear_data()

    seed_users(args.users)
    seed_products(args.products)

    user_rows = execute_query("SELECT id FROM users WHERE role = 'customer' LIMIT 50", fetch=True)
    product_rows = execute_query("SELECT id FROM products LIMIT 50", fetch=True)

    user_ids = [r[0] for r in (user_rows or [])]
    product_ids = [r[0] for r in (product_rows or [])]

    seed_orders(user_ids, product_ids)
    logger.info("Seeding complete!")


if __name__ == "__main__":
    main()
