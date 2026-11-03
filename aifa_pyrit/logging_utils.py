from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path


def setup_logger(name: str, *, log_dir: str | None = None, level: str | None = None) -> logging.Logger:
    """Create a named logger that writes to stdout and optionally to a per-day file."""
    logger = logging.getLogger(name)
    logger.setLevel((level or os.getenv("LOG_LEVEL") or "INFO").upper())
    logger.propagate = False

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    target_dir = Path(log_dir or os.getenv("APP_LOG_DIR") or Path.cwd() / "logs")
    target_dir.mkdir(parents=True, exist_ok=True)
    file_path = target_dir / f"{name.replace('.', '_')}-{datetime.utcnow().strftime('%Y%m%d')}.log"
    file_handler = logging.FileHandler(file_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
