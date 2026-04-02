"""
User management service. Business logic layer between API and database.
Handles registration, login, profile management.
All functions should be called with validated inputs (caller's responsibility).
"""

import logging
import time
from typing import Optional, Dict, Tuple

from backend.models import User
from backend.auth import generate_token, hash_password, invalidate_token
from backend.config import config
from database.queries import (
    get_user_by_email, get_user_by_id, create_user, update_user_status
)
from utils.validators import validate_email, validate_password, validate_username
from utils.helpers import build_cache_key

logger = logging.getLogger("services.user")

# Simple in-memory cache: cache_key -> (user_dict, expires_at)
# TODO: replace with Redis using config.REDIS_HOST
_user_cache: Dict[str, tuple] = {}
CACHE_TTL = 300  # 5 minutes


def _cache_user(user_dict: dict):
    key = build_cache_key("user", user_dict["id"])
    _user_cache[key] = (user_dict, time.time() + CACHE_TTL)


def _get_cached_user(user_id: int) -> Optional[dict]:
    key = build_cache_key("user", user_id)
    entry = _user_cache.get(key)
    if not entry:
        return None
    user_dict, expires_at = entry
    if time.time() > expires_at:
        del _user_cache[key]
        return None
    return user_dict


def register_user(email: str, username: str, password: str) -> Tuple[bool, str, Optional[dict]]:
    """
    Creates a new user account.
    Returns (success, message, user_dict_or_none).
    """
    valid, err = validate_email(email)
    if not valid:
        return False, err, None

    valid, err = validate_username(username)
    if not valid:
        return False, err, None

    valid, err = validate_password(password)
    if not valid:
        return False, err, None

    # Check for existing email
    existing = get_user_by_email(email.strip().lower())
    if existing:
        return False, "Email already registered", None

    user = User(
        id=None,
        email=email.strip().lower(),
        username=username.strip(),
        password_hash=hash_password(password),
        role="customer",
        is_active=True,
        created_at=time.time(),
    )

    try:
        new_id = create_user(user)
        user.id = new_id
        user_dict = user.to_public_dict()
        _cache_user(user_dict)
        logger.info(f"New user registered: {email} (id={new_id})")
        return True, "Registration successful", user_dict
    except Exception as e:
        logger.error(f"User registration failed for {email}: {e}")
        return False, "Registration failed due to server error", None


def login_user(email: str, password: str) -> Tuple[bool, str, Optional[str]]:
    """
    Authenticates user and returns JWT token.
    Returns (success, message, token_or_none).
    """
    if not email or not password:
        return False, "Email and password are required", None

    user_dict = get_user_by_email(email.strip().lower())
    if not user_dict:
        # Intentionally vague error for security
        return False, "Invalid credentials", None

    # BUG: if user_dict is returned but missing 'is_active' key, KeyError raised
    if not user_dict["is_active"]:
        return False, "Account is disabled", None

    # Reconstruct minimal User to use check_password
    user_obj = User(
        id=user_dict["id"],
        email=user_dict["email"],
        username=user_dict["username"],
        password_hash=user_dict["password_hash"],
        role=user_dict.get("role", "customer"),
    )

    if not user_obj.check_password(password):
        logger.warning(f"Failed login attempt for {email}")
        return False, "Invalid credentials", None

    token = generate_token(user_dict["id"], user_dict.get("role", "customer"))
    logger.info(f"User logged in: {email}")
    return True, "Login successful", token


def get_user_profile(user_id: int) -> Optional[dict]:
    """Returns public user profile. Uses cache."""
    cached = _get_cached_user(user_id)
    if cached:
        return cached

    user_dict = get_user_by_id(user_id)
    # BUG: get_user_by_id throws IndexError if user not found (see queries.py)
    # this function will propagate the crash instead of returning None
    if user_dict:
        _cache_user(user_dict)
    return user_dict


def deactivate_user(admin_token: str, target_user_id: int) -> Tuple[bool, str]:
    """Admin action: deactivate a user account."""
    from backend.auth import require_role
    if not require_role(admin_token, "admin"):
        return False, "Insufficient permissions"

    try:
        update_user_status(target_user_id, False)
        # Invalidate cache
        key = build_cache_key("user", target_user_id)
        _user_cache.pop(key, None)
        logger.info(f"User {target_user_id} deactivated")
        return True, "User deactivated"
    except Exception as e:
        logger.error(f"Failed to deactivate user {target_user_id}: {e}")
        return False, "Failed to deactivate user"


def logout_user(token: str):
    invalidate_token(token)
    logger.debug("User logged out")
