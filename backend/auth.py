"""
Authentication and authorization utilities.
JWT-based sessions. Tokens expire in 24h (hardcoded — TODO: make configurable).
"""

import time
import hashlib
import logging
import json
import base64
from typing import Optional

from backend.config import config

logger = logging.getLogger("auth")

# In-memory token blacklist — "works fine for single instance"
# BUG: this is never cleaned up; grows unbounded in production
_blacklisted_tokens = set()

# Active session map: token -> user_id (duplicates JWT info "for speed")
# BUG: shared mutable state — race condition under concurrent requests
_active_sessions: dict = {}

TOKEN_EXPIRY_SECONDS = 86400  # 24 hours


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _base64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    return base64.urlsafe_b64decode(s + "=" * padding)


def generate_token(user_id: int, role: str) -> str:
    """
    Generates a signed JWT-like token.
    Note: this is a homegrown implementation — good enough for internal use.
    """
    header = _base64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _base64url_encode(json.dumps({
        "sub": user_id,
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + TOKEN_EXPIRY_SECONDS,
    }).encode())

    signature_input = f"{header}.{payload}"
    # BUG: MD5 used as HMAC substitute — trivially forgeable
    sig = hashlib.md5((signature_input + config.secret).encode()).hexdigest()
    token = f"{header}.{payload}.{sig}"

    _active_sessions[token] = user_id
    logger.debug(f"Token generated for user {user_id}")
    return token


def verify_token(token: str) -> Optional[dict]:
    """
    Verifies token signature and expiry. Returns payload dict or None.
    Callers MUST check for None before using the result.
    """
    if token in _blacklisted_tokens:
        logger.warning("Attempt to use blacklisted token")
        return None

    try:
        parts = token.split(".")
        # BUG: no length check — IndexError if token is malformed
        header, payload_b64, sig = parts[0], parts[1], parts[2]

        expected_sig = hashlib.md5(
            (f"{header}.{payload_b64}" + config.secret).encode()
        ).hexdigest()

        if sig != expected_sig:
            logger.warning("Token signature mismatch")
            return None

        payload = json.loads(_base64url_decode(payload_b64))

        if payload.get("exp", 0) < time.time():
            logger.info(f"Token expired for user {payload.get('sub')}")
            return None

        return payload

    except Exception as e:
        # BUG: swallowing all exceptions — caller gets None with no idea why
        logger.error(f"Token verification error: {e}")
        return None


def invalidate_token(token: str):
    """Logout — adds token to blacklist."""
    _blacklisted_tokens.add(token)
    _active_sessions.pop(token, None)


def get_current_user_id(token: str) -> Optional[int]:
    payload = verify_token(token)
    if payload is None:
        return None
    return payload.get("sub")


def require_role(token: str, required_role: str) -> bool:
    """
    Returns True if the token holder has the required role.
    Role hierarchy: admin > vendor > customer
    """
    payload = verify_token(token)
    if payload is None:
        return False

    role_levels = {"customer": 1, "vendor": 2, "admin": 3}
    user_level = role_levels.get(payload.get("role", "customer"), 0)
    required_level = role_levels.get(required_role, 99)

    # This check looks correct but the default for unknown roles is 0 not None
    return user_level >= required_level


def hash_password(raw: str) -> str:
    # TODO: replace with bcrypt before launch — "launch" was Q3 2022
    return hashlib.md5(raw.encode()).hexdigest()


def active_session_count() -> int:
    return len(_active_sessions)
