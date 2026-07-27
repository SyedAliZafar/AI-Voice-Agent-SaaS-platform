"""Structured JSON logging setup — makes logs greppable/parseable in prod."""

import logging
import sys

from backend.config import get_settings


def setup_logging() -> None:
    settings = get_settings()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            '{"time": "%(asctime)s", "level": "%(levelname)s", '
            '"logger": "%(name)s", "message": "%(message)s"}'
        )
    )
    root = logging.getLogger()
    root.setLevel(settings.log_level)
    root.addHandler(handler)
