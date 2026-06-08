"""Camera intrinsics computation from user-supplied FOV (M7-S1).

Intrinsics are always derived from the camera's horizontal/vertical field of
view and the live stream resolution — never hardcoded per camera model. This
keeps the pipeline brand-agnostic.
"""
import math

# Allowed lens focal lengths (mm) for the UI dropdown. Stored as FLOAT so future
# non-standard lenses are not blocked at the schema level.
ALLOWED_LENS_FOCAL_LENGTHS_MM = (2.8, 4.0, 6.0, 8.0, 12.0, 16.0)

# 5-element distortion model [k1, k2, p1, p2, k3]. Estimated intrinsics assume a
# rectilinear lens with zero distortion.
ESTIMATED_DIST_COEFFS = [0.0, 0.0, 0.0, 0.0, 0.0]


def compute_intrinsics(
    h_fov_deg: float | None,
    v_fov_deg: float | None,
    stream_width: int | None,
    stream_height: int | None,
) -> dict | None:
    """Compute pinhole intrinsics from FOV and stream resolution.

    Returns a dict of {fx, fy, cx, cy, dist_coeffs, intrinsics_source}, or None
    if any required input is missing (computation is skipped silently in that
    case, per spec).
    """
    if h_fov_deg is None or v_fov_deg is None:
        return None
    if not stream_width or not stream_height:
        return None

    fx = (stream_width / 2) / math.tan(math.radians(h_fov_deg) / 2)
    fy = (stream_height / 2) / math.tan(math.radians(v_fov_deg) / 2)
    cx = stream_width / 2
    cy = stream_height / 2

    return {
        "fx": fx,
        "fy": fy,
        "cx": cx,
        "cy": cy,
        "dist_coeffs": list(ESTIMATED_DIST_COEFFS),
        "intrinsics_source": "estimated",
    }


def apply_intrinsics(camera) -> bool:
    """Recompute and write intrinsics onto a PhysicalCamera ORM instance.

    Returns True if intrinsics were (re)computed and applied, False if skipped
    due to missing inputs. Does not commit — the caller owns the transaction.
    """
    result = compute_intrinsics(
        camera.h_fov_deg,
        camera.v_fov_deg,
        camera.stream_width,
        camera.stream_height,
    )
    if result is None:
        return False
    camera.fx = result["fx"]
    camera.fy = result["fy"]
    camera.cx = result["cx"]
    camera.cy = result["cy"]
    camera.dist_coeffs = result["dist_coeffs"]
    camera.intrinsics_source = result["intrinsics_source"]
    return True
