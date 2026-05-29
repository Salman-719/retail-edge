"""Typed data contracts (pure dataclasses, not ORM rows).

The in-memory and over-the-wire vocabulary shared between modules and services.
Kept separate from ORM models so vision logic never imports SQLAlchemy.
"""
