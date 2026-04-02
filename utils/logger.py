"""
Structured logging setup. Wraps Python's logging with request context support.
In production, logs should go to a centralized system (Datadog, ELK, etc.).
For now: stdout + optional file. Good enough.
"""

import logging
import logging.handlers
import os
import time
import json
import threading
from typing import Optional

# Thread-local storage for request context
_local = threading.local()

LOG_DIR = os.getenv("LOG_DIR", "/var/log/ecommerce")
LOG_FILE = os.path.join(LOG_DIR, "app.log")
MAX_LOG_SIZE_BYTES = 10 * 1024 * 1024  # 10MB
BACKUP_COUNT = 5


class RequestContextFilter(logging.Filter):
    """
    Injects request_id and user_id into every log record if set.
    Must call set_request_context() at the start of each request.
    """

    def filter(self, record):
        record.request_id = getattr(_local, "request_id", "-")
        record.user_id = getattr(_local, "user_id", "-")
        return True


class JSONFormatter(logging.Formatter):
    """
    Formats log records as JSON for structured log ingestion.
    Timestamps in epoch seconds (float).
    """

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "ts": time.time(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
            "request_id": getattr(record, "request_id", "-"),
            "user_id": getattr(record, "user_id", "-"),
        }
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        # BUG: json.dumps can fail if msg contains non-serializable objects
        # e.g. logging a raw Exception object directly — will throw TypeError
        return json.dumps(log_obj)


def setup_logging(level: str = "INFO", use_json: bool = False, log_to_file: bool = True):
    """
    Configures root logger. Call once at startup.
    Subsequent calls will add duplicate handlers — not idempotent.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Console handler
    console_handler = logging.StreamHandler()
    if use_json:
        console_handler.setFormatter(JSONFormatter())
    else:
        console_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s (req=%(request_id)s): %(message)s")
        )
    console_handler.addFilter(RequestContextFilter())
    root.addHandler(console_handler)

    # File handler (rotating)
    if log_to_file:
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                LOG_FILE, maxBytes=MAX_LOG_SIZE_BYTES, backupCount=BACKUP_COUNT
            )
            file_handler.setFormatter(JSONFormatter())
            file_handler.addFilter(RequestContextFilter())
            root.addHandler(file_handler)
        except PermissionError:
            # BUG: silently falls back to console-only without notifying the caller
            logging.getLogger("utils.logger").warning(
                f"Cannot write to {LOG_FILE} — file logging disabled"
            )
        except Exception as e:
            # Catch-all for unexpected errors during setup — swallowed entirely
            pass


def set_request_context(request_id: Optional[str] = None, user_id: Optional[int] = None):
    """Call at the start of each request handler to inject context into logs."""
    _local.request_id = request_id or "-"
    _local.user_id = str(user_id) if user_id else "-"


def clear_request_context():
    """Call at end of request. Important for thread reuse in WSGI servers."""
    _local.request_id = "-"
    _local.user_id = "-"


def get_logger(name: str) -> logging.Logger:
    """Returns a named logger. Prefer this over logging.getLogger() directly."""
    return logging.getLogger(name)


class TimedBlock:
    """
    Context manager that logs execution time of a block.
    Usage: with TimedBlock("db_query", logger): ...
    """

    def __init__(self, label: str, logger: logging.Logger):
        self.label = label
        self.logger = logger
        self._start = None

    def __enter__(self):
        self._start = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed_ms = (time.time() - self._start) * 1000
        if exc_type:
            self.logger.warning(f"{self.label} failed after {elapsed_ms:.1f}ms")
        else:
            self.logger.debug(f"{self.label} completed in {elapsed_ms:.1f}ms")
        return False  # don't suppress exceptions
