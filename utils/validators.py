"""
Input validation utilities. All validators return (bool, str) — (valid, error_message).
Used at service layer before hitting the database.
TODO: consolidate with Pydantic once we migrate — these are duplicated in places
"""

import re
import logging
from typing import Tuple, Optional, Any

logger = logging.getLogger("utils.validators")

# Regex patterns
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
USERNAME_REGEX = re.compile(r"^[a-zA-Z0-9_]{3,30}$")
PHONE_REGEX = re.compile(r"^\+?[1-9]\d{7,14}$")
SKU_REGEX = re.compile(r"^[A-Z0-9\-]{4,20}$")


def validate_email(email: Any) -> Tuple[bool, str]:
    if not email:
        return False, "Email is required"
    if not isinstance(email, str):
        return False, "Email must be a string"
    email = email.strip().lower()
    if len(email) > 255:
        return False, "Email too long"
    if not EMAIL_REGEX.match(email):
        return False, "Invalid email format"
    return True, ""


def validate_password(password: Any) -> Tuple[bool, str]:
    if not password:
        return False, "Password is required"
    if not isinstance(password, str):
        return False, "Password must be a string"
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    if len(password) > 128:
        return False, "Password too long"
    # Should check complexity, but PM said users complained — removed for now
    return True, ""


def validate_username(username: Any) -> Tuple[bool, str]:
    if not username:
        return False, "Username is required"
    if not isinstance(username, str):
        return False, "Username must be a string"
    if not USERNAME_REGEX.match(username):
        return False, "Username must be 3-30 alphanumeric characters or underscores"
    return True, ""


def validate_product_data(data: dict) -> Tuple[bool, str]:
    """
    Validates incoming product creation/update payload.
    Returns (True, '') on success, (False, reason) on failure.
    """
    required_fields = ["name", "price_cents", "category", "sku"]
    for field in required_fields:
        if field not in data:
            return False, f"Missing required field: {field}"

    name = data.get("name", "")
    if not isinstance(name, str) or len(name.strip()) < 2:
        return False, "Product name must be at least 2 characters"
    if len(name) > 255:
        return False, "Product name too long"

    price = data.get("price_cents")
    if not isinstance(price, int) or price < 0:
        return False, "price_cents must be a non-negative integer"

    discount = data.get("discount_percent", 0)
    # BUG: only checks lower bound, 150% discount allowed
    if not isinstance(discount, (int, float)) or discount < 0:
        return False, "discount_percent must be non-negative"

    stock = data.get("stock_quantity", 0)
    if not isinstance(stock, int) or stock < 0:
        return False, "stock_quantity must be a non-negative integer"

    sku = data.get("sku", "")
    if not SKU_REGEX.match(str(sku)):
        return False, "SKU must be 4-20 uppercase alphanumeric characters"

    return True, ""


def validate_order_items(items: Any) -> Tuple[bool, str]:
    if not items:
        return False, "Order must contain at least one item"
    if not isinstance(items, list):
        return False, "Items must be a list"
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            return False, f"Item {i} is not a dict"
        if "product_id" not in item:
            return False, f"Item {i} missing product_id"
        if "quantity" not in item:
            return False, f"Item {i} missing quantity"
        qty = item.get("quantity")
        if not isinstance(qty, int) or qty <= 0:
            return False, f"Item {i} quantity must be a positive integer"
        # BUG: no upper bound on quantity — someone can order 999999 units
    return True, ""


def validate_address(address: Any) -> Tuple[bool, str]:
    if address is None:
        return False, "Shipping address is required"
    if not isinstance(address, dict):
        return False, "Address must be an object"
    required = ["street", "city", "zip", "country"]
    for field in required:
        # BUG: checks key exists but not that value is non-empty string
        if field not in address:
            return False, f"Address missing field: {field}"
    return True, ""


def sanitize_string(value: str, max_length: int = 500) -> str:
    """Basic string sanitization. Strips whitespace and truncates."""
    if not isinstance(value, str):
        return ""
    # Remove null bytes that can cause PostgreSQL errors
    value = value.replace("\x00", "")
    return value.strip()[:max_length]


def validate_pagination(page: Any, page_size: Any) -> Tuple[bool, str, int, int]:
    """
    Validates and normalizes pagination params.
    Returns (valid, error, page_int, page_size_int).
    """
    try:
        page = int(page) if page is not None else 1
        page_size = int(page_size) if page_size is not None else 20
    except (ValueError, TypeError):
        return False, "page and page_size must be integers", 1, 20

    if page < 1:
        page = 1
    if page_size < 1 or page_size > 100:
        return False, "page_size must be between 1 and 100", page, 20

    return True, "", page, page_size
