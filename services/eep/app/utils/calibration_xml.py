"""Parse OpenCV-format XML calibration files (intrinsic + extrinsic)."""
import xml.etree.ElementTree as ET


def _parse_mat(node: ET.Element) -> list:
    """Parse an OpenCV <Mat> XML node into a nested Python list."""
    rows = int(node.findtext("rows", "0"))
    cols = int(node.findtext("cols", "0"))
    data_text = node.findtext("data", "")
    values = [float(v) for v in data_text.split()]
    if rows == 1 or cols == 1:
        return values
    return [values[r * cols:(r + 1) * cols] for r in range(rows)]


def parse_intrinsic_xml(content: bytes) -> dict:
    """
    Parse an OpenCV intrinsic calibration XML file.

    Expected structure:
      <opencv_storage>
        <camera_matrix type_id="opencv-matrix"> ... </camera_matrix>
        <distortion_coefficients type_id="opencv-matrix"> ... </distortion_coefficients>
        <image_width>...</image_width>
        <image_height>...</image_height>
      </opencv_storage>

    Returns dict with: intrinsic_matrix, dist_coeffs, image_width, image_height
    """
    root = ET.fromstring(content)

    cam_node = root.find("camera_matrix")
    dist_node = root.find("distortion_coefficients")

    if cam_node is None or dist_node is None:
        raise ValueError("intrinsic XML must contain <camera_matrix> and <distortion_coefficients>")

    result: dict = {
        "intrinsic_matrix": _parse_mat(cam_node),
        "dist_coeffs": _parse_mat(dist_node),
        "image_width": None,
        "image_height": None,
    }

    w_text = root.findtext("image_width")
    h_text = root.findtext("image_height")
    if w_text:
        result["image_width"] = int(float(w_text))
    if h_text:
        result["image_height"] = int(float(h_text))

    return result


def parse_extrinsic_xml(content: bytes) -> dict:
    """
    Parse an OpenCV extrinsic calibration XML file.

    Expected structure:
      <opencv_storage>
        <rvec type_id="opencv-matrix"> ... </rvec>
        <tvec type_id="opencv-matrix"> ... </tvec>
        <!-- optional: rotation_matrix -->
        <camera_world_x>...</camera_world_x>
        <camera_world_y>...</camera_world_y>
        <camera_world_z>...</camera_world_z>
      </opencv_storage>

    Returns dict with: rotation_vector, translation_vector, rotation_matrix (optional),
                       camera_world_x/y/z (optional)
    """
    import numpy as np
    import cv2

    root = ET.fromstring(content)

    rvec_node = root.find("rvec")
    tvec_node = root.find("tvec")

    if rvec_node is None or tvec_node is None:
        raise ValueError("extrinsic XML must contain <rvec> and <tvec>")

    rvec = _parse_mat(rvec_node)
    tvec = _parse_mat(tvec_node)

    # Compute rotation matrix from rotation vector
    rvec_np = np.array(rvec, dtype=np.float64).reshape(3, 1)
    R, _ = cv2.Rodrigues(rvec_np)
    rotation_matrix = R.tolist()

    # Derive camera world position: C = -R^T * t
    tvec_np = np.array(tvec, dtype=np.float64).reshape(3, 1)
    cam_world = (-R.T @ tvec_np).flatten()

    result: dict = {
        "rotation_vector": rvec,
        "translation_vector": tvec,
        "rotation_matrix": rotation_matrix,
        "camera_world_x": float(cam_world[0]),
        "camera_world_y": float(cam_world[1]),
        "camera_world_z": float(cam_world[2]),
    }

    # Override with explicit world coords if provided in the file
    for axis in ("x", "y", "z"):
        val_text = root.findtext(f"camera_world_{axis}")
        if val_text:
            result[f"camera_world_{axis}"] = float(val_text)

    return result
