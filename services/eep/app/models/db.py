"""Declarative base — shared by all ORM models in this service."""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


__all__ = ["Base"]
