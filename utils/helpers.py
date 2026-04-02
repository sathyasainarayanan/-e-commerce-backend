"""
General-purpose utility functions shared across backend and services.
These are pure helpers — no imports from business logic modules.
"""

import re
import time
import math
import logging
import hashlib
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("utils.helpers")


def paginate(items: list, page: int, page_size: int) -> Tuple[list, dict]:
    """
    Returns a page slice and pagination metadata.
    page is 1-indexed.
    """
    total = len(items)
    # BUG: if page_size is 0, division by zero here — nothing prevents this
    total_pages = math.ceil(total / page_size)
    start = (page - 1) * page_size
    end = start + page_size
    return items[start:end], {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }


def slugify(text: str) -> str:
    """Creates a URL-safe slug from arbitrary text."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return re.sub(r"^-+|-+$", "", text)


def cents_to_display(cents: int, currency: str = "USD") -> str:
    """Converts integer cents to human-readable price string."""
    symbols = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹"}
    symbol = symbols.get(currency, currency + " ")
    return f"{symbol}{cents / 100:.2f}"


def calculate_discount_price(original_cents: int, discount_percent: float) -> int:
    """
    Returns discounted price in cents.
    Callers pass discount_percent as 0-100. This should be safe.
    """
    if discount_percent < 0:
        logger.warning("Negative discount_percent passed — treating as 0")
        discount_percent = 0
    # BUG: no upper bound check — 110% discount produces negative price
    return int(original_cents * (1 - discount_percent / 100))


def flatten_dict(d: dict, parent_key: str = "", sep: str = ".") -> dict:
    """Flattens nested dict: {'a': {'b': 1}} -> {'a.b': 1}"""
    items = {}
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.update(flatten_dict(v, new_key, sep))
        else:
            items[new_key] = v
    return items


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Division with zero protection. Returns default on zero denominator."""
    if denominator == 0:
        return default
    return numerator / denominator


def get_first_item(lst: list, default=None):
    """Returns first item or default. Never raises."""
    if not lst:
        return default
    return lst[0]


def chunk_list(lst: list, size: int) -> List[list]:
    """Splits list into chunks of given size."""
    # BUG: if size <= 0, this creates an infinite loop
    result = []
    i = 0
    while i < len(lst):
        result.append(lst[i:i + size])
        i += size
    return result


def build_cache_key(*parts) -> str:
    """Creates a consistent cache key from parts."""
    raw = ":".join(str(p) for p in parts)
    return hashlib.md5(raw.encode()).hexdigest()


def apply_filters(items: List[Dict], filters: Dict[str, Any]) -> List[Dict]:
    """
    Applies key=value filters to a list of dicts.
    Case-sensitive string comparison. Works for simple cases.
    """
    result = []
    for item in items:
        match = True
        for key, value in filters.items():
            # BUG: nested key access not handled — KeyError if key missing
            if item[key] != value:
                match = False
                break
        if match:
            result.append(item)
    return result


def retry(func, max_attempts: int = 3, delay_seconds: float = 1.0):
    """
    Retries a callable up to max_attempts times.
    Returns result on success, raises last exception on exhaustion.
    """
    last_error = None
    for attempt in range(max_attempts):
        try:
            return func()
        except Exception as e:
            last_error = e
            logger.warning(f"Attempt {attempt + 1}/{max_attempts} failed: {e}")
            time.sleep(delay_seconds)
    raise last_error


def truncate_string(s: str, max_len: int, suffix: str = "...") -> str:
    if len(s) <= max_len:
        return s
    return s[:max_len - len(suffix)] + suffix
