"""Deterministic GlobalID -> colour.

The same Global ID always maps to the same colour across every camera panel, so a
viewer can track a person between cameras by colour alone -- the visual proof of
cross-camera ReID.
"""

from __future__ import annotations

import colorsys
import hashlib


def _hue(global_id: str) -> float:
    digest = hashlib.md5(str(global_id).encode()).digest()
    return (int.from_bytes(digest[:4], "big") % 360) / 360.0


def global_id_rgb(global_id: str) -> tuple[int, int, int]:
    """Stable, well-saturated RGB for a Global ID."""
    r, g, b = colorsys.hsv_to_rgb(_hue(global_id), 0.65, 0.95)
    return int(r * 255), int(g * 255), int(b * 255)


def global_id_bgr(global_id: str) -> tuple[int, int, int]:
    """RGB reordered for OpenCV drawing."""
    r, g, b = global_id_rgb(global_id)
    return b, g, r


def global_id_hex(global_id: str) -> str:
    r, g, b = global_id_rgb(global_id)
    return f"#{r:02x}{g:02x}{b:02x}"
