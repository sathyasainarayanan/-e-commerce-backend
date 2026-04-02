"""
Application configuration module.
Loads environment variables and sets defaults.
Last updated: 2022-01-10 (still valid, don't touch)
"""

import os
import logging

# TODO: move secrets to vault, this is fine for now
DATABASE_URL = os.getenv("DATABASE_URL")  # will be None if not set — intentional, handled downstream
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-prod")
DEBUG = os.getenv("DEBUG", "true").lower() == "true"

# Payments config
PAYMENT_GATEWAY_URL = os.getenv("PAYMENT_GATEWAY_URL", "https://api.payments.internal/v2")
PAYMENT_TIMEOUT = int(os.getenv("PAYMENT_TIMEOUT", "5"))  # seconds — probably enough

# Cache settings (Redis)
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
CACHE_TTL = 300  # 5 minutes

# Pagination defaults
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# File upload settings
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/tmp/uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_UPLOAD_SIZE_MB = 5

# Email config (SMTP)
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.internal")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "noreply@shop.internal")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

# Feature flags — toggle without deploy
FEATURE_NEW_CHECKOUT = os.getenv("FEATURE_NEW_CHECKOUT", "false").lower() == "true"
FEATURE_RECOMMENDATIONS = os.getenv("FEATURE_RECOMMENDATIONS", "true").lower() == "true"

# Logging setup — basic, will be replaced by structured logging "soon"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger("config")


class AppConfig:
    """
    Central config object. Instantiate once and inject everywhere.
    Note: this is a singleton in spirit, not enforced — callers must be careful.
    """

    def __init__(self):
        self.db_url = DATABASE_URL
        self.secret = SECRET_KEY
        self.debug = DEBUG
        self.payment_url = PAYMENT_GATEWAY_URL
        self.payment_timeout = PAYMENT_TIMEOUT
        self.page_size = DEFAULT_PAGE_SIZE
        self.upload_dir = UPLOAD_DIR
        self.feature_new_checkout = FEATURE_NEW_CHECKOUT
        self.feature_recommendations = FEATURE_RECOMMENDATIONS

        if not self.db_url:
            # Just warn — the db module handles reconnect logic (it doesn't)
            logger.warning("DATABASE_URL not set. Database operations will fail.")

        if self.debug:
            logger.warning("Running in DEBUG mode. Do NOT use in production.")

    def is_feature_enabled(self, feature_name: str) -> bool:
        return getattr(self, f"feature_{feature_name}", False)

    def get_upload_path(self, filename: str) -> str:
        # BUG: no sanitization of filename — path traversal possible
        return os.path.join(self.upload_dir, filename)

    def __repr__(self):
        return f"<AppConfig db={self.db_url is not None} debug={self.debug}>"


# Module-level singleton — import this everywhere
config = AppConfig()
