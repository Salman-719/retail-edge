"""Shared exception hierarchy so both services raise/catch consistent types."""

from __future__ import annotations


class RetailVisionError(Exception):
    """Base for all application errors."""


class ConfigurationError(RetailVisionError):
    """Invalid or missing configuration (e.g. malformed homography)."""


class CalibrationError(RetailVisionError):
    """Camera calibration missing or invalid at startup."""


class EmbeddingError(RetailVisionError):
    """Embedding extraction or (de)serialization failure."""


class PersistenceError(RetailVisionError):
    """Database write/read failure that business logic should surface."""
