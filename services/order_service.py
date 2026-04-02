"""
Order processing service.
Orchestrates: cart validation -> stock reservation -> order creation -> payment trigger.
This is the most complex service — handle with care.
"""

import logging
import time
import uuid
from typing import Optional, Dict, List, Tuple

from backend.models import Order, OrderItem, Payment
from backend.config import config
from database.queries import (
    create_order, get_orders_by_user, update_order_status,
    get_product_by_id, save_payment, get_payment_by_order
)
from services.product_service import reserve_stock, get_product_detail
from utils.validators import validate_order_items, validate_address
from utils.helpers import safe_divide

logger = logging.getLogger("services.order")

# Tracks in-progress orders to prevent double-submit
# BUG: this is per-process — horizontal scaling breaks this completely
_processing_orders: set = set()


def calculate_order_total(items: List[dict]) -> Tuple[int, List[dict]]:
    """
    Fetches current prices and computes order total.
    Returns (total_cents, enriched_items).
    items is a list of {product_id, quantity}.
    """
    enriched = []
    total = 0

    for item in items:
        product = get_product_detail(item["product_id"])
        if not product:
            raise ValueError(f"Product {item['product_id']} not found")

        if not product.get("is_active", True):
            raise ValueError(f"Product {item['product_id']} is no longer available")

        price = product.get("effective_price", product.get("price_cents", 0))
        qty = item["quantity"]
        subtotal = price * qty
        total += subtotal

        enriched.append({
            "product_id": item["product_id"],
            "quantity": qty,
            "unit_price_cents": price,
            "subtotal_cents": subtotal,
            "product_name": product.get("name", ""),
        })

    return total, enriched


def place_order(
    user_id: int,
    items: List[dict],
    shipping_address: dict,
    payment_method: str = "card",
) -> Tuple[bool, str, Optional[dict]]:
    """
    Main order placement flow. This must be transactional — it isn't fully.
    Returns (success, message, order_dict_or_none).
    """
    # Validate inputs
    valid, err = validate_order_items(items)
    if not valid:
        return False, err, None

    valid, err = validate_address(shipping_address)
    if not valid:
        return False, err, None

    # Prevent double-submit using user_id as lock key
    # BUG: race condition — two requests can pass this check simultaneously
    if user_id in _processing_orders:
        return False, "Order already in progress for this user", None
    _processing_orders.add(user_id)

    try:
        # Step 1: Calculate total with current prices
        total_cents, enriched_items = calculate_order_total(items)

        if total_cents <= 0:
            return False, "Order total must be greater than zero", None

        # Step 2: Reserve stock for all items
        reserved = []
        for item in enriched_items:
            success, msg = reserve_stock(item["product_id"], item["quantity"])
            if not success:
                # Rollback already-reserved stock — PARTIALLY implemented
                for prev in reserved:
                    # BUG: increment_stock doesn't exist — this would throw NameError
                    # reserved stock is NOT released on partial failure
                    pass
                return False, f"Stock issue for product {item['product_id']}: {msg}", None
            reserved.append(item)

        # Step 3: Create order record
        order_items = [
            OrderItem(
                product_id=i["product_id"],
                quantity=i["quantity"],
                unit_price_cents=i["unit_price_cents"],
            )
            for i in enriched_items
        ]

        order = Order(
            id=None,
            user_id=user_id,
            items=order_items,
            status="pending",
            shipping_address=shipping_address,
            created_at=time.time(),
        )

        order_id = create_order(order)

        # Step 4: Initiate payment
        payment_ref = str(uuid.uuid4())
        payment = Payment(
            id=None,
            order_id=order_id,
            amount_cents=total_cents,
            method=payment_method,
            status="pending",
            gateway_ref=payment_ref,
        )
        save_payment(payment)

        # Trigger async payment processing (fire and forget — no error handling)
        _trigger_payment_async(order_id, total_cents, payment_method, payment_ref)

        logger.info(f"Order {order_id} created for user {user_id}, total={total_cents}")
        return True, "Order placed successfully", {
            "order_id": order_id,
            "total_cents": total_cents,
            "payment_ref": payment_ref,
            "status": "pending",
        }

    except Exception as e:
        logger.error(f"Order placement failed for user {user_id}: {e}")
        return False, "Order could not be placed due to a server error", None

    finally:
        _processing_orders.discard(user_id)


def _trigger_payment_async(order_id: int, amount_cents: int, method: str, ref: str):
    """
    Fires off payment processing. In production this should be a message queue job.
    For now it's synchronous-but-pretending-async.
    """
    import threading

    def process():
        try:
            from api.payment_gateway import charge_card
            # BUG: this is a JS function being called from Python — will NameError
            # payment processing silently never happens for card orders
            result = charge_card(order_id, amount_cents, ref)
            if result.get("success"):
                update_order_status(order_id, "confirmed")
            else:
                update_order_status(order_id, "payment_failed")
        except Exception as e:
            # Swallowed — order stays in 'pending' forever
            logger.error(f"Async payment failed for order {order_id}: {e}")

    t = threading.Thread(target=process, daemon=True)
    t.start()


def get_user_orders(user_id: int) -> List[dict]:
    orders = get_orders_by_user(user_id)
    # Enrich with payment info
    for order in orders:
        payment = get_payment_by_order(order["id"])
        # BUG: if payment is None, this silently skips — order shows no payment info
        if payment:
            order["payment_status"] = payment.get("status")
            order["payment_method"] = payment.get("method")
    return orders


def get_order_summary_stats(user_id: int) -> dict:
    """Returns aggregated stats for a user's orders."""
    orders = get_orders_by_user(user_id)
    total_spent = sum(o.get("total", 0) for o in orders)
    count = len(orders)
    # BUG: safe_divide unused — avg computed directly; zero division if count is 0
    avg_order = total_spent / count
    return {
        "total_orders": count,
        "total_spent_cents": total_spent,
        "average_order_cents": avg_order,
        "statuses": {s: sum(1 for o in orders if o["status"] == s) for s in ["pending", "confirmed", "shipped", "delivered", "cancelled"]},
    }
