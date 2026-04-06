import numpy as np
import cv2
from pathlib import Path
from typing import List, Dict, Optional


def _interp_color(t: float, stops: list) -> tuple:
    """Linear-interpolate between RGB color stops. t in [0, 1]."""
    for i in range(len(stops) - 1):
        t0, c0 = stops[i]
        t1, c1 = stops[i + 1]
        if t <= t1:
            if t1 == t0:
                return c0
            alpha = (t - t0) / (t1 - t0)
            r = int(round(c0[0] + alpha * (c1[0] - c0[0])))
            g = int(round(c0[1] + alpha * (c1[1] - c0[1])))
            b = int(round(c0[2] + alpha * (c1[2] - c0[2])))
            return (r, g, b)
    return stops[-1][1]


# Soft sequential palette: very-light-blue → cyan → soft-yellow → light-orange → soft-red
# Intentionally low-saturation to look like a polished analytics dashboard.
_COLOR_STOPS = [
    (0.00, (215, 237, 255)),  # #D7EDFF  very pale blue
    (0.25, (100, 195, 235)),  # #64C3EB  light sky-cyan
    (0.50, (255, 235, 120)),  # #FFEB78  soft yellow
    (0.75, (255, 165,  75)),  # #FFA54B  warm light orange
    (1.00, (245, 100,  95)),  # #F5645F  soft red
]


def _zone_color_bgr(percent: float) -> tuple:
    """Map occupancy % → BGR tuple using the soft sequential palette."""
    t = min(max(percent, 0.0), 100.0) / 100.0
    r, g, b = _interp_color(t, _COLOR_STOPS)
    return (b, g, r)   # OpenCV uses BGR


def _draw_zone_label(img: np.ndarray, cx: int, cy: int, name: str, percent: float) -> None:
    """
    Draw a two-line label (name / percentage) centered at (cx, cy).
    Uses a very subtle semi-transparent white backing rather than a hard black box.
    """
    font = cv2.FONT_HERSHEY_SIMPLEX
    fs = 0.38          # small, clean font scale
    fw = 1             # thin weight

    line1 = name
    line2 = f"{percent:.1f}%"

    (w1, h1), _ = cv2.getTextSize(line1, font, fs, fw)
    (w2, h2), _ = cv2.getTextSize(line2, font, fs, fw)

    max_w = max(w1, w2)
    line_gap = 4
    total_h = h1 + line_gap + h2
    pad = 5

    # Background rectangle (semi-transparent white)
    bx1 = cx - max_w // 2 - pad
    by1 = cy - total_h // 2 - pad
    bx2 = cx + max_w // 2 + pad
    by2 = cy + total_h // 2 + pad

    # Clamp to image bounds
    H_img, W_img = img.shape[:2]
    bx1 = max(0, bx1); by1 = max(0, by1)
    bx2 = min(W_img - 1, bx2); by2 = min(H_img - 1, by2)

    bg = img.copy()
    cv2.rectangle(bg, (bx1, by1), (bx2, by2), (255, 255, 255), -1)
    cv2.addWeighted(bg, 0.55, img, 0.45, 0, img)

    # Text color: dark charcoal, easy to read on light background
    text_color = (40, 40, 40)

    # Draw line 1 (name)
    y1 = cy - total_h // 2 + h1
    cv2.putText(img, line1, (cx - w1 // 2, y1), font, fs, text_color, fw, cv2.LINE_AA)

    # Draw line 2 (percentage)
    y2 = y1 + line_gap + h2
    cv2.putText(img, line2, (cx - w2 // 2, y2), font, fs, text_color, fw, cv2.LINE_AA)


def generate_heatmap(
    camera_id: str,
    trajectory_meters: List[Dict],
    floor_plan_path: Path,
    pixels_per_meter: float,
    origin_px: Dict,          # {'x': px, 'y': py}
    output_path: Path,
    sigma_meters: float = 0.5,
    zones: Optional[List[Dict]] = None,
    zone_occupancy: Optional[Dict] = None,
) -> str:
    """
    Generate a polished heatmap overlaid on the floor plan.
    Each zone is filled with a soft colour keyed to its occupancy percentage
    (very light blue → cyan → yellow → orange → soft red).
    Returns the path of the saved PNG.
    """
    floor = cv2.imread(str(floor_plan_path))
    if floor is None:
        raise ValueError(f'Could not read floor plan: {floor_plan_path}')

    result = floor.copy()

    if not zones or not zone_occupancy:
        cv2.imwrite(str(output_path), result)
        return str(output_path)

    for zone in zones:
        zname = zone['name']
        occ = zone_occupancy.get(zname, {})
        percent = occ.get('percent', 0.0)

        # Convert zone points (meters) → floor-plan pixel coords
        pts_px = []
        for p in zone['points']:
            px = int(origin_px['x'] + p['x'] * pixels_per_meter)
            py = int(origin_px['y'] - p['y'] * pixels_per_meter)
            pts_px.append([px, py])
        pts_arr = np.array(pts_px, dtype=np.int32)

        fill_color = _zone_color_bgr(percent)

        # Semi-transparent fill at low opacity so the floor plan shows through
        overlay = result.copy()
        cv2.fillPoly(overlay, [pts_arr], fill_color)
        cv2.addWeighted(overlay, 0.38, result, 0.62, 0, result)

        # Thin clean border
        cv2.polylines(result, [pts_arr], isClosed=True, color=fill_color, thickness=2)

        # Centered label
        cx = int(np.mean([p[0] for p in pts_px]))
        cy = int(np.mean([p[1] for p in pts_px]))
        _draw_zone_label(result, cx, cy, zname, percent)

    cv2.imwrite(str(output_path), result)
    return str(output_path)
