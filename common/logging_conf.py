"""Structured logging setup. JSON in production (Grafana/Loki), plain in dev.

Configured once at service startup.
"""

from __future__ import annotations

import logging
import sys

from common.config import get_settings


def configure_logging(service_name: str) -> None:
    s = get_settings()
    handler = logging.StreamHandler(sys.stdout)
    if s.log_json:
        fmt = (
            '{"ts":"%(asctime)s","level":"%(levelname)s",'
            f'"service":"{service_name}",'
            '"logger":"%(name)s","msg":"%(message)s"}'
        )
    else:
        fmt = f"%(asctime)s [%(levelname)s] {service_name} %(name)s: %(message)s"
    handler.setFormatter(logging.Formatter(fmt))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(s.log_level)
