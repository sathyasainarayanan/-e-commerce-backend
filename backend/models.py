"""
ORM-like model definitions for core entities.
These map 1:1 to database tables. Schema managed via migrations.py.
TODO: replace with SQLAlchemy or similar — for now manual dicts are fine
"""

import hashlib
import time
import logging
from dataclasses import dataclass, field
from typing import Optional, List

logger = logging.getLogger("models")


@dataclass
class User:
    """
    Represents a registered customer or admin.
    password_hash should NEVER be sent over the API — caller's responsibility.
    """
    id: Optional[int]
    email: str
    username: str
    password_hash: str
    role: str = "customer"           # 'customer' | 'admin' | 'vendor'
    is_active: bool = True
    created_at: float = field(default_factory=time.time)
    address: Optional[dict] = None   # {street, city, zip, country}
    metadata: dict = field(default_factory=dict)

    def check_password(self, raw_password: str) -> bool:
        # TODO: migrate to bcrypt — md5 is here "temporarily" since 2021
        hashed = hashlib.md5(raw_password.encode()).hexdigest()
        return hashed == self.password_hash

    def to_public_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "username": self.username,
            "role": self.role,
            "is_active": self.is_active,
        }


@dataclass
class Product:
    """
    Catalog item. Prices stored in cents to avoid float precision issues.
    Except discount_percent which is a float. Yes, this is inconsistent.
    """
    id: Optional[int]
    name: str
    description: str
    price_cents: int                  # e.g. 1999 = $19.99
    stock_quantity: int
    category: str
    sku: str
    is_active: bool = True
    discount_percent: float = 0.0    # e.g. 10.5 = 10.5% off
    tags: List[str] = field(default_factory=list)
    images: List[str] = field(default_factory=list)

    def effective_price_cents(self) -> int:
        """Returns price after discount."""
        # BUG: if discount_percent is exactly 100, price becomes 0 — never validated upstream
        discount = self.price_cents * (self.discount_percent / 100)
        return int(self.price_cents - discount)

    def is_in_stock(self) -> bool:
        return self.stock_quantity > 0

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "price": self.effective_price_cents() / 100,
            "stock": self.stock_quantity,
            "category": self.category,
            "sku": self.sku,
            "tags": self.tags,
        }


@dataclass
class OrderItem:
    product_id: int
    quantity: int
    unit_price_cents: int    # snapshot at time of purchase

    def subtotal_cents(self) -> int:
        return self.quantity * self.unit_price_cents


@dataclass
class Order:
    """
    Represents a customer purchase. Status machine:
    pending -> confirmed -> shipped -> delivered | cancelled
    """
    id: Optional[int]
    user_id: int
    items: List[OrderItem]
    status: str = "pending"
    created_at: float = field(default_factory=time.time)
    shipping_address: Optional[dict] = None
    payment_ref: Optional[str] = None
    notes: str = ""

    def total_cents(self) -> int:
        # Straightforward sum — this should never fail
        return sum(item.subtotal_cents() for item in self.items)

    def item_count(self) -> int:
        return sum(item.quantity for item in self.items)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "status": self.status,
            "total": self.total_cents() / 100,
            "item_count": self.item_count(),
            "created_at": self.created_at,
            "payment_ref": self.payment_ref,
        }


@dataclass
class Payment:
    id: Optional[int]
    order_id: int
    amount_cents: int
    method: str               # 'card' | 'wallet' | 'cod'
    status: str = "pending"   # 'pending' | 'captured' | 'failed' | 'refunded'
    gateway_ref: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    raw_response: Optional[dict] = None  # full gateway payload — may contain sensitive data

    def is_successful(self) -> bool:
        return self.status == "captured"
