import cv2
import numpy as np
from typing import List, Dict, Tuple

REPROJECTION_ERROR_THRESHOLD = 5.0  # pixels; reject if mean error exceeds this

def compute_homography(
    cam_points: List[Dict],   # [{'x': px, 'y': py}, ...] in camera pixels
    floor_points: List[Dict], # [{'x': mx, 'y': my}, ...] in real-world meters
) -> Dict:
    """
    Compute the homography matrix H such that:
    floor_homogeneous = H @ [cam_px, cam_py, 1]^T
    Uses RANSAC for robustness against outlier point pairs.
    Returns a dict with 'matrix', 'reprojectionError', 'status', 'inlierMask'.
    """
    if len(cam_points) < 4:
        raise ValueError('Minimum 4 point pairs required')

    src = np.array([[p['x'], p['y']] for p in cam_points], dtype=np.float32)
    dst = np.array([[p['x'], p['y']] for p in floor_points], dtype=np.float32)

    # RANSAC gives robustness; method=0 is least-squares (use for <8 points)
    method = cv2.RANSAC if len(cam_points) >= 6 else 0
    H, mask = cv2.findHomography(src, dst, method=method, ransacReprojThreshold=3.0)

    if H is None:
        return {
            'status': 'failed',
            'error': 'cv2.findHomography returned None — points may be collinear. Distribute them across the full frame.'
        }

    # Compute mean reprojection error on ALL points (not just inliers)
    src_h = np.hstack([src, np.ones((len(src), 1))])  # homogeneous
    projected = (H @ src_h.T).T
    projected /= projected[:, 2:3]  # normalize
    errors = np.linalg.norm(projected[:, :2] - dst, axis=1)
    mean_error = float(np.mean(errors))
    max_error = float(np.max(errors))
    per_point_errors = errors.tolist()

    status = 'ok' if mean_error <= REPROJECTION_ERROR_THRESHOLD else 'rejected'

    return {
        'status': status,
        'matrix': H.tolist(),  # 3x3 list-of-lists
        'reprojectionError': mean_error,
        'maxError': max_error,
        'perPointErrors': per_point_errors,
        'inlierMask': mask.ravel().tolist() if mask is not None else None,
        'threshold': REPROJECTION_ERROR_THRESHOLD,
    }


def project_point(H: np.ndarray, cam_px: float, cam_py: float) -> Tuple[float, float]:
    """Apply homography to a single camera pixel → floor meters."""
    pt = np.array([[[cam_px, cam_py]]], dtype=np.float32)
    result = cv2.perspectiveTransform(pt, H)
    return float(result[0][0][0]), float(result[0][0][1])
