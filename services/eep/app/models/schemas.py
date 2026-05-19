"""Backward-compat shim. Schemas live in app.schemas.*"""
from app.schemas import *  # noqa: F401, F403
from app.schemas import __all__  # noqa: F401
