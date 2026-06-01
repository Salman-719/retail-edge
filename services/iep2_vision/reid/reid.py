"""ReID Embedder — sole owner of OSNet model loading and embedding extraction.

Swap OSNet for another ReID model here and nothing outside this file changes.
All model config lives in the constants below; nothing is buried in functions.
"""
import sys
from pathlib import Path

import cv2
import numpy as np

MODEL_NAME    = "osnet_x1_0"
DEVICE        = "cpu"
EMBEDDING_DIM = 512


def load_model(device: str = DEVICE):
    """Load and return the OSNet ReID model via boxmot.

    Call once; pass the returned object to extract_embedding — never call
    load_model() per frame. boxmot handles weight download and caching.
    """
    from boxmot.reid.core.reid import ReID

    return ReID(
        weights=Path(f"{MODEL_NAME}.pt"),
        device=device,
        half=False,
    )


def extract_embedding(model, frame: np.ndarray, bbox: list[int]):
    """Return an L2-normalized float32 embedding for the person crop.

    bbox: [x1, y1, x2, y2] in pixel coordinates (ints or floats).
    Returns a (EMBEDDING_DIM,) float32 numpy vector, or None if the
    clamped crop has zero area (fully out-of-bounds bbox).

    Crop resizing to model input dimensions is handled by boxmot internally.
    """
    x1, y1, x2, y2 = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
    h, w = frame.shape[:2]

    # Clamp to frame boundaries — never crash on edge-touching boxes.
    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = min(w, x2)
    y2 = min(h, y2)

    if x2 <= x1 or y2 <= y1:
        return None

    crop = frame[y1:y2, x1:x2]

    # boxmot ReID handles crop preprocessing (resize, normalise) internally.
    payload = model.preprocess([crop])
    result  = model.process(payload)

    if result is None:
        return None

    emb = result.cpu().numpy()[0].astype(np.float32)
    norm = np.linalg.norm(emb)
    if norm > 0:
        emb = emb / norm
    return emb


if __name__ == "__main__":
    if len(sys.argv) != 6:
        print("usage: python reid.py <image_path> <x1> <y1> <x2> <y2>")
        sys.exit(1)

    image_path = sys.argv[1]
    bbox = [int(a) for a in sys.argv[2:6]]

    img = cv2.imread(image_path)
    if img is None:
        print(f"cannot read image: {image_path}")
        sys.exit(1)

    reid_model = load_model()
    emb = extract_embedding(reid_model, img, bbox)

    if emb is None:
        print("zero-area bbox — no embedding produced")
        sys.exit(1)

    print(f"shape: {emb.shape}")
    print(f"norm:  {np.linalg.norm(emb):.6f}")
