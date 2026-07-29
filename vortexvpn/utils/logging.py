"""
Logging helpers - structured JSON logs to file + stderr.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
import time
from pathlib import Path
from typing import Any


class JsonFormatter(logging.Formatter):
    """One-line JSON per record, easy to ingest with jq / ELK."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for k, v in record.__dict__.items():
            if k not in ("args", "msg", "levelname", "name", "created",
                         "msecs", "relativeCreated", "exc_info", "exc_text",
                         "filename", "module", "funcName", "lineno",
                         "processName", "process", "threadName", "thread",
                         "pathname", "stack_info", "taskName"):
                payload.setdefault(k, str(v))
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO",
                  log_file: str = "/var/log/vortexvpn/vortexvpn.log",
                  component: str = "vortex") -> logging.Logger:
    """Configure root logger with JSON formatter (file + stderr)."""
    logger = logging.getLogger(component)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    if not logger.handlers:
        # stderr
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(JsonFormatter())
        logger.addHandler(sh)
        # file
        try:
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)
            fh = logging.handlers.RotatingFileHandler(
                log_file, maxBytes=10 * 1024 * 1024, backupCount=5,
            )
            fh.setFormatter(JsonFormatter())
            logger.addHandler(fh)
        except (PermissionError, OSError):
            # Can't write to /var/log - fall back to stderr only
            pass

    return logger
