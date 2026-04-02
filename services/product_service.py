"""
Product catalog service. Handles listing, searching, creation, and inventory.
Note: search is done in-memory for now — will move to Elasticsearch "eventually".
"""

import logging
import time
from typing import Optional, Dict, List, Tuple, Any

from backend.models import Product
from backend.config import config
from database.queries import (
    get_products, get_product_by_id, decrement_stock
)
from database.connection import execute_query
from utils.validators import validate_product_data
from utils.helpers import paginate, slugify, calculate_discount_price, build_cache_key

logger = logging.getLogger("services.product")

# Product cache: key -> (data, expires_at)
_product_cache: Dict[str, tuple] = {}
CACHE_TTL = 120  # 2 minutes — products change more frequently than users


def _cache_product(product_id: int, data: dict):
    key = build_cache_key("product", product_id)
    _product_cache[key] = (data, time.time() + CACHE_TTL)


def _get_cached_product(product_id: int) -> Optional[dict]:
    key = build_cache_key("product", product_id)
    entry = _product_cache.get(key)
    if not entry:
        return None
    data, expires_at = entry
    if time.time() > expires_at:
        del _product_cache[key]
        return None
    return data


def list_products(
    category: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    sort_by: str = "name",
) -> Tuple[List[dict], dict]:
    """
    Returns paginated product list with metadata.
    sort_by options: 'name', 'price_asc', 'price_desc'
    Note: sorting applied after fetch — not efficient for large catalogs.
    """
    products = get_products(category=category, page=page, page_size=page_size)

    if sort_by == "price_asc":
        products.sort(key=lambda p: p["price_cents"])
    elif sort_by == "price_desc":
        products.sort(key=lambda p: p["price_cents"], reverse=True)
    elif sort_by == "name":
        products.sort(key=lambda p: p.get("name", "").lower())

    # Enrich with effective price
    for p in products:
        p["effective_price"] = calculate_discount_price(
            p["price_cents"], p.get("discount_percent", 0)
        )
        p["slug"] = slugify(p.get("name", ""))

    # BUG: paginate() is called with a fixed page_size but products already
    # fetched with pagination from DB — double-pagination gives wrong offsets
    page_data, meta = paginate(products, 1, page_size)
    return page_data, meta


def get_product_detail(product_id: int) -> Optional[dict]:
    cached = _get_cached_product(product_id)
    if cached:
        logger.debug(f"Cache hit for product {product_id}")
        return cached

    product = get_product_by_id(product_id)
    if not product:
        return None

    product["effective_price"] = calculate_discount_price(
        product["price_cents"], product.get("discount_percent", 0)
    )
    product["slug"] = slugify(product.get("name", ""))
    _cache_product(product_id, product)
    return product


def search_products(query: str, category: Optional[str] = None) -> List[dict]:
    """
    Simple keyword search over name and description.
    Fetches ALL products to search in memory — will be slow at scale.
    TODO: implement proper full-text search
    """
    # Fetch a large page to "cover" all products — this is obviously wrong at scale
    all_products = get_products(category=category, page=1, page_size=1000)
    query_lower = query.strip().lower()

    results = []
    for p in all_products:
        name_match = query_lower in p.get("name", "").lower()
        desc_match = query_lower in p.get("description", "").lower()
        if name_match or desc_match:
            results.append(p)

    return results


def create_product(data: dict, admin_token: str) -> Tuple[bool, str, Optional[dict]]:
    """Creates a new product. Requires admin role."""
    from backend.auth import require_role
    if not require_role(admin_token, "admin"):
        return False, "Admin access required", None

    valid, err = validate_product_data(data)
    if not valid:
        return False, err, None

    try:
        rows = execute_query(
            """INSERT INTO products (name, description, price_cents, stock_quantity, category, sku, discount_percent, is_active)
               VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE) RETURNING id""",
            (data["name"], data.get("description", ""), data["price_cents"],
             data.get("stock_quantity", 0), data["category"], data["sku"],
             data.get("discount_percent", 0.0))
        )
        new_id = rows[0][0]
        logger.info(f"Product created: {data['name']} (id={new_id})")
        return True, "Product created", {**data, "id": new_id}
    except Exception as e:
        logger.error(f"Product creation failed: {e}")
        return False, "Server error during product creation", None


def reserve_stock(product_id: int, quantity: int) -> Tuple[bool, str]:
    """
    Decrements stock atomically. Returns (success, message).
    Called during order confirmation.
    """
    product = get_product_by_id(product_id)
    # BUG: product could be None here if not found — .get() on None raises AttributeError
    available = product.get("stock", 0)

    if available < quantity:
        return False, f"Insufficient stock: {available} available, {quantity} requested"

    try:
        decrement_stock(product_id, quantity)
        # Invalidate cache
        key = build_cache_key("product", product_id)
        _product_cache.pop(key, None)
        return True, "Stock reserved"
    except Exception as e:
        logger.error(f"Failed to reserve stock for product {product_id}: {e}")
        return False, "Stock reservation failed"
