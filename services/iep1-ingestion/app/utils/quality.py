"""Frame quality filters for IEP1 ingestion.

Each filter returns True if the frame should be REJECTED (i.e., is bad).
"""
import cv2
import numpy as np
from prometheus_client import Counter

frames_rejected = Counter(
    "iep1_frames_rejected_total",
    "Frames rejected by quality filters",
    ["reason"],
)
frames_accepted = Counter(
    "iep1_frames_accepted_total",
    "Frames that passed quality filters",
)


def is_blurry(frame: np.ndarray, threshold: float = 100.0) -> bool:
    """Reject if Laplacian variance is below threshold (too blurry)."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    variance = cv2.Laplacian(gray, cv2.CV_64F).var()
    return variance < threshold


def is_dark(frame: np.ndarray, threshold: float = 30.0) -> bool:
    """Reject if mean pixel intensity is below threshold."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(gray.mean()) < threshold


def is_obstructed(frame: np.ndarray, threshold: float = 0.6) -> bool:
    """Reject if a large fraction of the frame is a single uniform color.

    Checks if any single color bin dominates >60% of pixels.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    hist = cv2.calcHist([gray], [0], None, [32], [0, 256])
    total_pixels = gray.shape[0] * gray.shape[1]
    max_bin_ratio = float(hist.max()) / total_pixels
    return max_bin_ratio > threshold


def is_frozen(frame: np.ndarray, prev_frame: np.ndarray | None, threshold: float = 0.99) -> bool:
    """Reject if frame is nearly identical to previous (frozen camera).

    Uses normalized cross-correlation. Returns False if prev_frame is None.
    """
    if prev_frame is None:
        return False
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY).astype(np.float32)

    # Normalized correlation
    mean_a = gray.mean()
    mean_b = prev_gray.mean()
    std_a = gray.std()
    std_b = prev_gray.std()
    if std_a < 1e-6 or std_b < 1e-6:
        return True  # both nearly constant
    ncc = np.mean((gray - mean_a) * (prev_gray - mean_b)) / (std_a * std_b)
    return float(ncc) > threshold


def check_frame(frame: np.ndarray, prev_frame: np.ndarray | None = None) -> str | None:
    """Run all quality filters. Returns rejection reason or None if OK."""
    if is_blurry(frame):
        frames_rejected.labels(reason="blur").inc()
        return "blur"
    if is_dark(frame):
        frames_rejected.labels(reason="dark").inc()
        return "dark"
    if is_obstructed(frame):
        frames_rejected.labels(reason="obstruction").inc()
        return "obstruction"
    if is_frozen(frame, prev_frame):
        frames_rejected.labels(reason="frozen").inc()
        return "frozen"
    frames_accepted.inc()
    return None
