"""OpenCV homography computation with quality metrics."""
import math

import cv2
import numpy as np


def compute_homography(correspondences: list[dict]) -> dict:
    """
    Compute a homography matrix from pixel→world point pairs.

    Args:
        correspondences: list of {"pixel": [x, y], "world": [X, Y]}

    Returns:
        dict with homography_matrix, rms_reprojection_error,
        max_reprojection_error, point_count, coverage_score, condition_number
    """
    src = np.array([[c["pixel"][0], c["pixel"][1]] for c in correspondences], dtype=np.float64)
    dst = np.array([[c["world"][0], c["world"][1]] for c in correspondences], dtype=np.float64)

    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, ransacReprojThreshold=5.0)

    if H is None:
        raise ValueError("homography computation failed — points may be collinear or degenerate")

    # Reprojection errors
    src_h = np.column_stack([src, np.ones(len(src))])
    projected = (H @ src_h.T).T
    projected_2d = projected[:, :2] / projected[:, 2:3]
    errors = np.linalg.norm(projected_2d - dst, axis=1)

    rms = float(np.sqrt(np.mean(errors ** 2)))
    max_err = float(np.max(errors))

    # Condition number of H (low = well-conditioned transform)
    condition = float(np.linalg.cond(H))

    # Coverage score: ratio of convex hull area to bounding box area of src points
    hull = cv2.convexHull(src.astype(np.float32))
    hull_area = float(cv2.contourArea(hull))
    x_range = float(src[:, 0].max() - src[:, 0].min())
    y_range = float(src[:, 1].max() - src[:, 1].min())
    bbox_area = x_range * y_range
    coverage = hull_area / bbox_area if bbox_area > 0 else 0.0

    return {
        "homography_matrix": H.tolist(),
        "rms_reprojection_error": rms,
        "max_reprojection_error": max_err,
        "point_count": len(correspondences),
        "coverage_score": coverage,
        "condition_number": condition,
    }
