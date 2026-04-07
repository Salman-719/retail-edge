"""Backward-compat re-export shim.

All schemas now live in app.schemas.*
Existing code that does `from app.models.schemas import X` continues to work.
"""
from app.schemas import *  # noqa: F401, F403
from app.schemas import __all__  # noqa: F401
