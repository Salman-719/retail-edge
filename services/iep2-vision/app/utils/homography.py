"""Homography computation and ray-ground projection utilities."""
import cv2
import numpy as np
from typing import List, Dict, Optional, Tuple

REPROJECTION_ERROR_THRESHOLD = 5.0  # metres


def compute_homography(correspondences: List[Dict]) -> Dict:
    if len(correspondences) < 4:
        return {"status": "failed", "error": "Minimum 4 point pairs required"}

    src = np.array([[c["camPx"]["x"], c["camPx"]["y"]] for c in correspondences], dtype=np.float32)
    dst = np.array([[c["floorM"]["x"], c["floorM"]["y"]] for c in correspondences], dtype=np.float32)

    method = cv2.RANSAC if len(correspondences) >= 6 else 0
    H, mask = cv2.findHomography(src, dst, method=method, ransacReprojThreshold=3.0)

    if H is None:
        return {"status": "failed", "error": "cv2.findHomography returned None — points may be collinear."}

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
    pt = np.array([[[cam_px, cam_py]]], dtype=np.float32)
    result = cv2.perspectiveTransform(pt, H)
    return float(result[0][0][0]), float(result[0][0][1])


def project_pixel_to_ground_ray(
    u: float,
    v: float,
    K: np.ndarray,
    R: np.ndarray,
    t: np.ndarray,
    dist_coeffs: Optional[np.ndarray] = None,
    ground_z: float = 0.0,
) -> Tuple[float, float]:
    """Project camera pixel (u, v) to world ground point via ray-ground intersection.

    Uses intrinsic/extrinsic calibration (Method 2).

    Math:
        Camera center:    C = -R^T @ t
        Ray direction:    d = normalize(R^T @ K_inv @ [u, v, 1]^T)
        Ground intersect: s = (ground_z - C[2]) / d[2]
        World point:      C + s * d → (world_x, world_y)

    Args:
        u, v:        Pixel coordinates (column, row).
        K:           3×3 intrinsic matrix (float64 numpy array).
        R:           3×3 rotation matrix (float64 numpy array).
        t:           Translation vector shape (3,) (float64 numpy array).
        dist_coeffs: Optional distortion coefficients [k1,k2,p1,p2,k3,...].
        ground_z:    Z value of the ground plane (default 0.0).

    Returns:
        (world_x, world_y) on the ground plane.
        Falls back to (camera_center_x, camera_center_y) for degenerate rays.
    """
    u_use, v_use = float(u), float(v)

    # Undistort the pixel if distortion coefficients are provided
    if dist_coeffs is not None and len(dist_coeffs) > 0 and np.any(dist_coeffs != 0):
        pt = np.array([[[u_use, v_use]]], dtype=np.float32)
        undistorted = cv2.undistortPoints(pt, K.astype(np.float32), dist_coeffs.astype(np.float32), P=K.astype(np.float32))
        u_use = float(undistorted[0][0][0])
        v_use = float(undistorted[0][0][1])

    # Camera center in world space: C = -R^T @ t
    C = -R.T @ t  # shape (3,)

    # Ray direction in world space
    K_inv = np.linalg.inv(K)
    ray_cam = K_inv @ np.array([u_use, v_use, 1.0], dtype=np.float64)
    ray_world = R.T @ ray_cam
    norm = np.linalg.norm(ray_world)
    if norm < 1e-10:
        return (float(C[0]), float(C[1]))
    d = ray_world / norm

    # Intersect ray with ground plane Z = ground_z
    d_z = d[2]
    if abs(d_z) < 1e-9:
        # Ray nearly parallel to ground — return camera XY position
        return (float(C[0]), float(C[1]))

    s = (ground_z - C[2]) / d_z
    if s <= 0:
        # Intersection is behind the camera — clamp to small positive
        s = abs(s) + 0.001

    world_pt = C + s * d
    return (float(world_pt[0]), float(world_pt[1]))
