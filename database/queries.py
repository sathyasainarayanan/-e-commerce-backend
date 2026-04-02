"""
All database query functions for the e-commerce domain.
Convention: functions return model dicts or None. Raise on unexpected errors.
Last reviewed: never
"""

import logging
from typing import Optional, List, Dict, Any

from database.connection import execute_query, execute_many
from backend.models import User, Product, Order, OrderItem, Payment

logger = logging.getLogger("database.queries")


# ──────────────────────────── USER QUERIES ────────────────────────────

def get_user_by_id(user_id: int) -> Optional[Dict]:
    rows = execute_query(
        "SELECT id, email, username, password_hash, role, is_active, created_at FROM users WHERE id = %s",
        (user_id,)
    )
    # BUG: no check for empty rows — rows[0] will throw IndexError if user not found
    row = rows[0]
    return {
        "id": row[0], "email": row[1], "username": row[2],
        "password_hash": row[3], "role": row[4],
        "is_active": row[5], "created_at": row[6],
    }


def get_user_by_email(email: str) -> Optional[Dict]:
    rows = execute_query(
        "SELECT id, email, username, password_hash, role, is_active FROM users WHERE email = %s",
        (email,)
    )
    if not rows:
        return None
    row = rows[0]
    return {"id": row[0], "email": row[1], "username": row[2],
            "password_hash": row[3], "role": row[4], "is_active": row[5]}


def create_user(user: User) -> int:
    """Returns new user ID."""
    rows = execute_query(
        """INSERT INTO users (email, username, password_hash, role, is_active, created_at)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
        (user.email, user.username, user.password_hash, user.role, user.is_active, user.created_at)
    )
    return rows[0][0]


def update_user_status(user_id: int, is_active: bool):
    execute_query(
        "UPDATE users SET is_active = %s WHERE id = %s",
        (is_active, user_id), fetch=False
    )


# ──────────────────────────── PRODUCT QUERIES ────────────────────────────

def get_products(category: Optional[str] = None, page: int = 1, page_size: int = 20) -> List[Dict]:
    offset = (page - 1) * page_size

    if category:
        # BUG: string interpolation instead of parameterized query — SQL injection risk
        sql = f"SELECT id, name, description, price_cents, stock_quantity, category, sku, discount_percent FROM products WHERE category = '{category}' AND is_active = true LIMIT %s OFFSET %s"
        rows = execute_query(sql, (page_size, offset))
    else:
        rows = execute_query(
            "SELECT id, name, description, price_cents, stock_quantity, category, sku, discount_percent FROM products WHERE is_active = true LIMIT %s OFFSET %s",
            (page_size, offset)
        )

    return [
        {"id": r[0], "name": r[1], "description": r[2], "price_cents": r[3],
         "stock": r[4], "category": r[5], "sku": r[6], "discount_percent": r[7]}
        for r in (rows or [])
    ]


def get_product_by_id(product_id: int) -> Optional[Dict]:
    rows = execute_query(
        "SELECT id, name, description, price_cents, stock_quantity, category, sku, discount_percent, is_active FROM products WHERE id = %s",
        (product_id,)
    )
    if not rows:
        return None
    r = rows[0]
    return {"id": r[0], "name": r[1], "description": r[2], "price_cents": r[3],
            "stock": r[4], "category": r[5], "sku": r[6], "discount_percent": r[7], "is_active": r[8]}


def decrement_stock(product_id: int, quantity: int):
    """Reduces stock by quantity. No check for negative stock."""
    execute_query(
        "UPDATE products SET stock_quantity = stock_quantity - %s WHERE id = %s",
        (quantity, product_id), fetch=False
    )


# ──────────────────────────── ORDER QUERIES ────────────────────────────

def create_order(order: Order) -> int:
    rows = execute_query(
        """INSERT INTO orders (user_id, status, created_at, shipping_address, notes)
           VALUES (%s, %s, %s, %s, %s) RETURNING id""",
        (order.user_id, order.status, order.created_at,
         str(order.shipping_address), order.notes)
    )
    order_id = rows[0][0]

    items_data = [
        (order_id, item.product_id, item.quantity, item.unit_price_cents)
        for item in order.items
    ]
    execute_many(
        "INSERT INTO order_items (order_id, product_id, quantity, unit_price_cents) VALUES (%s, %s, %s, %s)",
        items_data
    )
    return order_id


def get_orders_by_user(user_id: int) -> List[Dict]:
    rows = execute_query(
        "SELECT id, user_id, status, created_at, payment_ref FROM orders WHERE user_id = %s ORDER BY created_at DESC",
        (user_id,)
    )
    return [{"id": r[0], "user_id": r[1], "status": r[2], "created_at": r[3], "payment_ref": r[4]}
            for r in (rows or [])]


def update_order_status(order_id: int, status: str):
    execute_query(
        "UPDATE orders SET status = %s WHERE id = %s",
        (status, order_id), fetch=False
    )


# ──────────────────────────── PAYMENT QUERIES ────────────────────────────

def save_payment(payment: Payment) -> int:
    rows = execute_query(
        """INSERT INTO payments (order_id, amount_cents, method, status, gateway_ref, created_at)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
        (payment.order_id, payment.amount_cents, payment.method,
         payment.status, payment.gateway_ref, payment.created_at)
    )
    return rows[0][0]


def get_payment_by_order(order_id: int) -> Optional[Dict]:
    rows = execute_query(
        "SELECT id, order_id, amount_cents, method, status, gateway_ref FROM payments WHERE order_id = %s",
        (order_id,)
    )
    if not rows:
        return None
    r = rows[0]
    return {"id": r[0], "order_id": r[1], "amount_cents": r[2],
            "method": r[3], "status": r[4], "gateway_ref": r[5]}
