import logging
import os
import sys
from contextvars import ContextVar

# Id of the request being served (set by the request id middleware); "-" outside a request.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def _level() -> int:
    """Log level from the ``LOG_LEVEL`` setting (default INFO); unknown names mean INFO."""
    try:
        from src.config import get_settings

        name = get_settings().LOG_LEVEL
    except Exception:  # noqa: BLE001  (logging must work even when the settings are invalid)
        name = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
    level = logging.getLevelName(name)
    return level if isinstance(level, int) else logging.INFO


def get_logger(name: str) -> logging.Logger:
    """
    Returns a logger configured with a consistent format.

    Usage:
        from src.utils.logger import get_logger
        logger = get_logger(__name__)
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.DEBUG)
        handler.addFilter(_RequestIdFilter())
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] [%(request_id)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    logger.setLevel(_level())
    logger.propagate = False
    return logger
