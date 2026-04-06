"""Heatmap generation — zone-coloured overlay on floor plan image."""
import io
import numpy as np
import cv2
from typing import List, Dict, Optional


_COLOR_STOPS = [
    (0.00, (215, 237, 255)),
    (0.25, (100, 195, 235)),
    (0.50, (255, 235, 120)),
    (0.75, (255, 165,  75)),
    (1.00, (245, 100,  95)),
]


def _interp_color(t: float) -> tuple:
    for i in range(len(_COLOR_STOPS) - 1):
        t0, c0 = _COLOR_STOPS[i]
        t1, c1 = _COLOR_STOPS[i + 1]
        if t <= t1:
            if t1 == t0:
                return c0
            alpha = (t - t0) / (t1 - t0)
            return tuple(int(round(c0[k] + alpha * (c1[k] - c0[k]))) for k in range(3))
    return _COLOR_STOPS[-1][1]


def _zone_color_bgr(percent: float) -> tuple:
    t = min(max(percent, 0.0), 100.0) / 100.0
    r, g, b = _interp_color(t)
    return (b, g, r)


def generate_heatmap_bytes(
    floor_plan_path: str,
    trajectory_meters: List[Dict],
    zones: List[Dict],
    zone_occupancy: Dict,
    pixels_per_meter: float,
    origin_px: Dict = None,
) -> bytes:
    """Generate heatmap and return PNG bytes."""
    if origin_px is None:
        origin_px = {"x": 0, "y": 0}

    floor = cv2.imread(floor_plan_path)
    if floor is None:
        raise ValueError(f"Could not read floor plan: {floor_plan_path}")

    result = floor.copy()

    for zone in zones:
        zname = zone["name"]
        percent = zone_occupancy.get(zname, {}).get("percent", 0.0)

        pts_px = []
        for p in zone["points"]:
            px = int(origin_px["x"] + p["x"] * pixels_per_meter)
            py = int(origin_px["y"] - p["y"] * pixels_per_meter)
            pts_px.append([px, py])
        pts_arr = np.array(pts_px, dtype=np.int32)

        fill_color = _zone_color_bgr(percent)

        overlay = result.copy()
        cv2.fillPoly(overlay, [pts_arr], fill_color)
        cv2.addWeighted(overlay, 0.38, result, 0.62, 0, result)
        cv2.polylines(result, [pts_arr], isClosed=True, color=fill_color, thickness=2)

        # Label
        cx = int(np.mean([p[0] for p in pts_px]))
        cy = int(np.mean([p[1] for p in pts_px]))
        label = f"{zname}: {percent:.1f}%"
        cv2.putText(result, label, (cx - 40, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (40, 40, 40), 1, cv2.LINE_AA)

    _, buf = cv2.imencode(".png", result)
    return buf.tobytes()
