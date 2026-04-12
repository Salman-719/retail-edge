"""Homography computation utilities."""
import cv2
import numpy as np
from typing import List, Dict, Tuple

REPROJECTION_ERROR_THRESHOLD = 5.0  # meters; reject if mean error exceeds this


def compute_homography(correspondences: List[Dict]) -> Dict:
    """
    Compute the homography matrix from a list of correspondence dicts.
    Each dict: {"camPx": {"x": float, "y": float}, "floorM": {"x": float, "y": float}}
    Returns a dict compatible with CalibrationResponse fields.
    """
    if len(correspondences) < 4:
        return {"status": "failed", "error": "Minimum 4 point pairs required"}

    src = np.array([[c["camPx"]["x"], c["camPx"]["y"]] for c in correspondences], dtype=np.float32)
    dst = np.array([[c["floorM"]["x"], c["floorM"]["y"]] for c in correspondences], dtype=np.float32)

    method = cv2.RANSAC if len(correspondences) >= 6 else 0
    H, mask = cv2.findHomography(src, dst, method=method, ransacReprojThreshold=3.0)

    if H is None:
        return {
            "status": "failed",
            "error": "cv2.findHomography returned None — points may be collinear.",
        }

    # Reprojection error
    src_h = np.hstack([src, np.ones((len(src), 1))])
    projected = (H @ src_h.T).T
    projected /= projected[:, 2:3]
    errors = np.linalg.norm(projected[:, :2] - dst, axis=1)
    mean_error = float(np.mean(errors))
    status = "ok" if mean_error <= REPROJECTION_ERROR_THRESHOLD else "rejected"

    return {
        "status": status,
        "homography_matrix": H.tolist(),
        "mean_error": mean_error,
        "max_error": float(np.max(errors)),
        "per_point_errors": errors.tolist(),
        "inlier_mask": mask.ravel().tolist() if mask is not None else None,
    }


def project_point(H: np.ndarray, cam_px: float, cam_py: float) -> Tuple[float, float]:
    """Apply homography to a single camera pixel → floor meters."""
    pt = np.array([[[cam_px, cam_py]]], dtype=np.float32)
    result = cv2.perspectiveTransform(pt, H)
    return float(result[0][0][0]), float(result[0][0][1])
