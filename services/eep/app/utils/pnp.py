"""PnP extrinsic calibration via cv2.solvePnP (M7-S2).

Unlike homography (which assumes a top-down camera), solvePnP recovers the full
6-DoF camera pose from 2D-3D correspondences and the camera intrinsics, so it
works for cameras mounted at any angle.
"""
import cv2
import numpy as np


def compute_pnp(
    correspondences: list[dict],
    camera_matrix: list[list[float]],
    dist_coeffs: list[float],
) -> dict:
    """Run solvePnP on 2D-3D correspondences.

    correspondences: list of {frame_px, frame_py, world_x, world_y, world_z}.
    camera_matrix: 3x3 intrinsic matrix (nested list).
    dist_coeffs: 5-element distortion vector.

    Returns a dict with rotation_vector, translation_vector (nested lists),
    camera_world_x/y/z, rms_reprojection_error, max_reprojection_error,
    point_count.

    Raises ValueError if solvePnP fails.
    """
    object_points = np.array(
        [[c["world_x"], c["world_y"], c.get("world_z", 0.0)] for c in correspondences],
        dtype=np.float64,
    )
    image_points = np.array(
        [[c["frame_px"], c["frame_py"]] for c in correspondences],
        dtype=np.float64,
    )

    cam_mtx = np.array(camera_matrix, dtype=np.float64).reshape(3, 3)
    dist = np.array(dist_coeffs, dtype=np.float64).reshape(-1, 1)

    success, rvec, tvec = cv2.solvePnP(
        object_points,
        image_points,
        cam_mtx,
        dist,
        flags=cv2.SOLVEPNP_ITERATIVE,
    )
    if not success:
        raise ValueError("solvePnP failed. Check correspondence points.")

    # Reprojection error.
    projected, _ = cv2.projectPoints(object_points, rvec, tvec, cam_mtx, dist)
    projected = projected.reshape(-1, 2)
    errors = np.linalg.norm(image_points - projected, axis=1)
    rms = float(np.sqrt(np.mean(errors ** 2)))
    max_error = float(np.max(errors))

    # Camera position in world coordinates: C = -R^T @ t.
    R, _ = cv2.Rodrigues(rvec)
    camera_world_pos = -R.T @ tvec  # shape (3, 1)

    return {
        "rotation_vector": rvec.tolist(),
        "translation_vector": tvec.tolist(),
        "camera_world_x": float(camera_world_pos[0][0]),
        "camera_world_y": float(camera_world_pos[1][0]),
        "camera_world_z": float(camera_world_pos[2][0]),
        "rms_reprojection_error": rms,
        "max_reprojection_error": max_error,
        "point_count": len(correspondences),
    }


def project_pixel_to_world(
    method: str,
    u: float,
    v: float,
    *,
    homography_matrix=None,
    intrinsic_matrix=None,
    dist_coeffs=None,
    rotation_vector=None,
    translation_vector=None,
) -> tuple[float, float] | None:
    """Project a frame pixel (u, v) to floor world coords using a calibration.

    Mirrors IEP2's FloorProjector so the onboarding verification preview matches
    runtime behaviour exactly. Returns (world_x, world_y) or None.

    PnP path: undistort → back-project → rotate to world → intersect Z=0 plane
    (with the same parallel-ray and behind-camera guards as the runtime).
    """
    if method == "homography":
        if homography_matrix is None:
            return None
        H = np.array(homography_matrix, dtype=np.float64).reshape(3, 3)
        dst = H @ np.array([u, v, 1.0], dtype=np.float64)
        return float(dst[0] / dst[2]), float(dst[1] / dst[2])

    if method == "pnp":
        if intrinsic_matrix is None or rotation_vector is None or translation_vector is None:
            return None
        K = np.array(intrinsic_matrix, dtype=np.float64).reshape(3, 3)
        dist = np.array(dist_coeffs if dist_coeffs is not None else [0, 0, 0, 0, 0], dtype=np.float64).reshape(-1, 1)
        rvec = np.array(rotation_vector, dtype=np.float64).reshape(3, 1)
        tvec = np.array(translation_vector, dtype=np.float64).reshape(3, 1)
        try:
            R, _ = cv2.Rodrigues(rvec)
            cam_center = (-R.T @ tvec).flatten()
            K_inv = np.linalg.inv(K)
        except Exception:
            return None

        pixel = np.array([[[u, v]]], dtype=np.float64)
        undistorted = cv2.undistortPoints(pixel, K, dist, P=K)
        u_corr = undistorted[0][0][0]
        v_corr = undistorted[0][0][1]

        point_cam = K_inv @ np.array([u_corr, v_corr, 1.0], dtype=np.float64)
        ray_dir = R.T @ point_cam
        norm = np.linalg.norm(ray_dir)
        if norm < 1e-12:
            return None
        ray_dir = ray_dir / norm

        if abs(ray_dir[2]) < 1e-6:
            return None
        t = -cam_center[2] / ray_dir[2]
        if t < 0:
            return None
        return float(cam_center[0] + t * ray_dir[0]), float(cam_center[1] + t * ray_dir[1])

    return None


def classify_quality(rms: float, stream_width: int | None) -> str:
    """Map RMS reprojection error to a human-readable quality label.

    Thresholds assume ~3000px-wide sensors. For low-resolution streams
    (< 1000px wide) they are scaled down by a factor of 3.
    """
    excellent, acceptable = 1.0, 3.0
    if stream_width is not None and stream_width < 1000:
        excellent /= 3.0
        acceptable /= 3.0
    if rms < excellent:
        return "excellent"
    if rms <= acceptable:
        return "acceptable"
    return "poor"
