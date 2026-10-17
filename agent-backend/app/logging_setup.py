"""Configuracion de logs estructurados con structlog."""
import logging
import sys

import structlog

from app.config import get_settings


def setup_logging() -> None:
    """Configura structlog + logging estandar para toda la app."""
    settings = get_settings()
    nivel = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=nivel)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(nivel),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Logger estructurado listo para usar."""
    return structlog.get_logger(name)
