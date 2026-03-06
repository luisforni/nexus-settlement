import json
import logging
import logging.config
import sys
from typing import Any, Dict, Optional

from app.core.config import settings

_REDACTED_FIELDS = frozenset(
    {
        "password",
        "token",
        "secret",
        "authorization",
        "card_number",
        "account_number",
        "private_key",
        "api_key",
    }
)

_REDACTED_VALUE = "[REDACTED]"

def _redact(obj: Any, depth: int = 0) -> Any:

    if depth > 8:
        return obj

    if isinstance(obj, dict):
        return {
            k: _REDACTED_VALUE if k.lower() in _REDACTED_FIELDS else _redact(v, depth + 1)
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [_redact(item, depth + 1) for item in obj]
    return obj

class JsonFormatter(logging.Formatter):

    def format(self, record: logging.LogRecord) -> str:
        log_data: Dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.%03dZ"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": "settlement-service",
            "environment": settings.ENVIRONMENT,
        }

        for key, value in record.__dict__.items():
            if key not in {
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "taskName",
            }:
                log_data[key] = _redact(value)

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, default=str)

def _configure_logging() -> None:

    level = getattr(logging, settings.SETTLEMENT_LOG_LEVEL.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers = [handler]

    if settings.ENVIRONMENT == "production":
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

_configure_logging()

def get_logger(name: Optional[str] = None) -> logging.Logger:

    return logging.getLogger(name)
