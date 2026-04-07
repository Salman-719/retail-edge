"""Shared schema primitives."""
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str = "1.0.0"


class Point(BaseModel):
    x: float
    y: float
