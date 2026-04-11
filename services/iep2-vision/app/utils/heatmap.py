"""Heatmap generation — zone-coloured overlay on floor plan image."""
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
    origin_px: Optional[Dict] = None,
) -> bytes:
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

        cx = int(np.mean([p[0] for p in pts_px]))
        cy = int(np.mean([p[1] for p in pts_px]))
        label = f"{zname}: {percent:.1f}%"
        cv2.putText(result, label, (cx - 40, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (40, 40, 40), 1, cv2.LINE_AA)

    _, buf = cv2.imencode(".png", result)
    return buf.tobytes()


def generate_virtual_heatmap_bytes(
    trajectory_meters: List[Dict],
    zones: List[Dict],
    zone_occupancy: Dict,
    world_bounds: Dict,
    canvas_px: int = 800,
) -> bytes:
    """Generate a heatmap on a synthetic white canvas (no floor plan image).

    Used by Method 2 (calibration-files) where no floor plan image exists.
    World coordinates map directly to canvas pixels via a uniform scale.

    Args:
        trajectory_meters: List of {x, y, ...} dicts in world metres.
        zones:             Zone dicts with 'name', 'points' (world metres).
        zone_occupancy:    {zone_name: {percent, seconds}} dict.
        world_bounds:      {x_min, x_max, y_min, y_max} in world metres.
        canvas_px:         Canvas size in pixels (square).
    """
    x_min = float(world_bounds.get("x_min", 0))
    x_max = float(world_bounds.get("x_max", 10))
    y_min = float(world_bounds.get("y_min", 0))
    y_max = float(world_bounds.get("y_max", 10))

    world_w = max(x_max - x_min, 0.01)
    world_h = max(y_max - y_min, 0.01)
    scale = min(canvas_px / world_w, canvas_px / world_h)

    canvas_w = int(world_w * scale)
    canvas_h = int(world_h * scale)
    canvas_w = max(canvas_w, 1)
    canvas_h = max(canvas_h, 1)

    def world_to_px(wx: float, wy: float):
        """World metres → canvas pixel (x right, y up → pixel y down)."""
        px = int((wx - x_min) * scale)
        py = int(canvas_h - (wy - y_min) * scale)
        return (max(0, min(canvas_w - 1, px)), max(0, min(canvas_h - 1, py)))

    # White background
    canvas = np.full((canvas_h, canvas_w, 3), 245, dtype=np.uint8)

    # Draw light grid lines every 1 m
    grid_color = (210, 210, 210)
    x_start = int(np.ceil(x_min))
    y_start = int(np.ceil(y_min))
    for gx in range(x_start, int(np.floor(x_max)) + 1):
        px, _ = world_to_px(gx, y_min)
        cv2.line(canvas, (px, 0), (px, canvas_h - 1), grid_color, 1)
    for gy in range(y_start, int(np.floor(y_max)) + 1):
        _, py = world_to_px(x_min, gy)
        cv2.line(canvas, (0, py), (canvas_w - 1, py), grid_color, 1)

    # Draw zones (colour-filled by occupancy)
    for zone in zones:
        zname = zone.get("name", "")
        percent = zone_occupancy.get(zname, {}).get("percent", 0.0)
        pts_px = [world_to_px(p["x"], p["y"]) for p in zone.get("points", [])]
        if len(pts_px) < 3:
            continue
        pts_arr = np.array(pts_px, dtype=np.int32)
        fill_color = _zone_color_bgr(percent)
        overlay = canvas.copy()
        cv2.fillPoly(overlay, [pts_arr], fill_color)
        cv2.addWeighted(overlay, 0.38, canvas, 0.62, 0, canvas)
        cv2.polylines(canvas, [pts_arr], isClosed=True, color=fill_color, thickness=2)

        cx = int(np.mean([p[0] for p in pts_px]))
        cy = int(np.mean([p[1] for p in pts_px]))
        label = f"{zname}: {percent:.1f}%"
        cv2.putText(canvas, label, (cx - 40, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (40, 40, 40), 1, cv2.LINE_AA)

    # Draw trajectory as a heat overlay
    if trajectory_meters:
        heat = np.zeros((canvas_h, canvas_w), dtype=np.float32)
        for pt in trajectory_meters:
            px, py = world_to_px(float(pt.get("x", 0)), float(pt.get("y", 0)))
            if 0 <= px < canvas_w and 0 <= py < canvas_h:
                heat[py, px] += 1.0

        if heat.max() > 0:
            heat /= heat.max()
            kernel_size = max(3, int(scale * 0.5) | 1)  # odd kernel
            heat_blur = cv2.GaussianBlur(heat, (kernel_size, kernel_size), 0)
            heat_blur /= max(heat_blur.max(), 1e-6)

            # Apply colourmap and blend
            heat_8 = (heat_blur * 255).astype(np.uint8)
            heat_color = cv2.applyColorMap(heat_8, cv2.COLORMAP_JET)
            mask = heat_blur > 0.01
            canvas[mask] = (canvas[mask].astype(np.float32) * 0.5 + heat_color[mask].astype(np.float32) * 0.5).astype(np.uint8)

    _, buf = cv2.imencode(".png", canvas)
    return buf.tobytes()
