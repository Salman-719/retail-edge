"""Parse OpenCV XML calibration files (intr_*.xml and extr_*.xml).

All functions are pure (no DB / network I/O).
"""
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np


# ── XML helpers ───────────────────────────────────────────────────────────────

def _text_to_floats(text: str) -> List[float]:
    """Parse whitespace-separated floats from an XML text node."""
    return [float(v) for v in text.split()]


def _find_matrix_data(root: ET.Element, *node_names: str) -> Optional[List[float]]:
    """Search for a matrix data node under any of the given names."""
    for name in node_names:
        node = root.find(f"{name}/data")
        if node is not None and node.text:
            return _text_to_floats(node.text.strip())
    return None


# ── Public API ─────────────────────────────────────────────────────────────────

def parse_intrinsic_xml(content: bytes) -> Dict[str, Any]:
    """Parse intr_*.xml and return intrinsic data.

    Returns dict with keys:
      intrinsic_matrix  – 3×3 list-of-lists (K)
      dist_coeffs       – list of floats [k1, k2, p1, p2, k3, ...]
    """
    root = ET.fromstring(content)

    # Support both 'camera_matrix' and 'M' node names used by different calibration tools
    k_flat = _find_matrix_data(root, "camera_matrix", "M", "intrinsic_matrix")
    if k_flat is None or len(k_flat) < 9:
        raise ValueError("Intrinsic XML: could not find 3×3 camera matrix (expected <camera_matrix> or <M>)")

    K = [
        [k_flat[0], k_flat[1], k_flat[2]],
        [k_flat[3], k_flat[4], k_flat[5]],
        [k_flat[6], k_flat[7], k_flat[8]],
    ]

    # Support 'distortion_coefficients', 'D', or 'dist_coeffs'
    dist_flat = _find_matrix_data(root, "distortion_coefficients", "D", "dist_coeffs")
    dist_coeffs: List[float] = dist_flat if dist_flat else []

    return {"intrinsic_matrix": K, "dist_coeffs": dist_coeffs}


def parse_extrinsic_xml(content: bytes, scale_factor: float = 1.0) -> Dict[str, Any]:
    """Parse extr_*.xml and return extrinsic data.

    Args:
        content:      Raw bytes of the XML file.
        scale_factor: Multiply tvec by this value before storing.
                      Use 0.001 when tvec is in mm and you want metres.
                      Default 1.0 (no scaling) — user provides the correct value.

    Returns dict with keys:
      rotation_matrix   – 3×3 list-of-lists (R, derived via cv2.Rodrigues)
      translation_vector – 3-element list [tx, ty, tz] (scaled)
    """
    root = ET.fromstring(content)

    # rvec (Rodrigues rotation vector)
    rvec_node = root.find("rvec")
    if rvec_node is None or not rvec_node.text:
        raise ValueError("Extrinsic XML: missing <rvec> node")
    rvec = np.array(_text_to_floats(rvec_node.text.strip()), dtype=np.float64)
    if rvec.shape[0] < 3:
        raise ValueError("Extrinsic XML: <rvec> must have 3 elements")

    # tvec (translation vector)
    tvec_node = root.find("tvec")
    if tvec_node is None or not tvec_node.text:
        raise ValueError("Extrinsic XML: missing <tvec> node")
    tvec_raw = np.array(_text_to_floats(tvec_node.text.strip()), dtype=np.float64)
    if tvec_raw.shape[0] < 3:
        raise ValueError("Extrinsic XML: <tvec> must have 3 elements")

    # Convert Rodrigues vector to rotation matrix
    R_mat, _ = cv2.Rodrigues(rvec.reshape(3, 1))

    tvec_scaled = tvec_raw[:3] * scale_factor

    return {
        "rotation_matrix": R_mat.tolist(),
        "translation_vector": tvec_scaled.tolist(),
    }


def compute_camera_center(R: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Compute camera world position C = -R^T @ t (OpenCV convention)."""
    return -R.T @ t


def validate_calibration(
    K: List[List[float]],
    dist_coeffs: List[float],
    R: List[List[float]],
    t: List[float],
) -> List[Dict[str, str]]:
    """Validate calibration data. Returns list of {level, message} dicts.

    Levels: 'error' (unusable) | 'warning' (suspect but may work).
    """
    issues: List[Dict[str, str]] = []
    K_np = np.array(K, dtype=np.float64)
    R_np = np.array(R, dtype=np.float64)
    t_np = np.array(t, dtype=np.float64)

    # ── Intrinsic checks ─────────────────────────────────────────────────────
    fx, fy = K_np[0, 0], K_np[1, 1]
    if fx <= 0 or fy <= 0:
        issues.append({"level": "error", "message": f"Focal lengths must be positive (fx={fx:.2f}, fy={fy:.2f})"})

    # ── Rotation matrix checks ────────────────────────────────────────────────
    det = float(np.linalg.det(R_np))
    if abs(det - 1.0) > 0.01:
        issues.append({"level": "error", "message": f"Rotation matrix determinant is {det:.4f} (expected ~1.0) — matrix may not be orthogonal"})

    ortho_err = float(np.linalg.norm(R_np @ R_np.T - np.eye(3)))
    if ortho_err > 0.05:
        issues.append({"level": "error", "message": f"Rotation matrix is not orthogonal (||R·R^T - I|| = {ortho_err:.4f})"})

    # ── Camera height check ───────────────────────────────────────────────────
    C = compute_camera_center(R_np, t_np)
    if C[2] <= 0.0:
        issues.append({
            "level": "error",
            "message": (
                f"Camera Z = {C[2]:.3f} — camera appears to be at or below the ground plane. "
                "Check that the translation vector uses OpenCV convention (t = -R @ C_world), "
                "not the camera world position."
            ),
        })

    # ── Scale warning (tvec not in metres?) ──────────────────────────────────
    t_norm = float(np.linalg.norm(t_np))
    if t_norm > 100.0:
        issues.append({
            "level": "warning",
            "message": (
                f"Translation vector norm is {t_norm:.1f} — this looks like centimetres or millimetres, not metres. "
                "Set tvec unit to 'cm → m (×0.01)' if your dataset uses centimetres, "
                "or 'mm → m (×0.001)' for millimetres."
            ),
        })
    elif t_norm > 5.0:
        issues.append({
            "level": "warning",
            "message": (
                f"Translation vector norm is {t_norm:.2f} — if this is larger than your scene in metres, "
                "the tvec may not have been converted to metres yet. Check the selected unit scale."
            ),
        })

    return issues
