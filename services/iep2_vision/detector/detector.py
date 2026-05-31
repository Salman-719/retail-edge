"""Detector — sole owner of: receive frame, return detections.

Swap YOLO for another model here and nothing outside this file changes.
The model variant lives in MODEL_VARIANT below — the only place model
config is allowed to exist.
"""
import json
import sys

import cv2
import numpy as np

# The only place the model variant is configured. YOLOv8n (nano, fast).
MODEL_VARIANT = "yolov8n.pt"

# Lazily-loaded singleton so importing this module is cheap and the weights
# download/load happens once on first detect().
_model = None


def _get_model():
    global _model
    if _model is None:
        from ultralytics import YOLO

        _model = YOLO(MODEL_VARIANT)
    return _model


def detect(frame: np.ndarray) -> list[dict]:
    """Run detection on a BGR numpy frame.

    Returns a list of {label, confidence, bbox: [x1, y1, x2, y2]} dicts.
    """
    model = _get_model()
    results = model(frame, verbose=False, classes=[0])
    CONF_THRESHOLD = 0.5

    detections: list[dict] = []
    for result in results:
        names = result.names
        boxes = result.boxes
        if boxes is None:
            continue
        for box in boxes:
            conf = float(box.conf[0])
            if conf < CONF_THRESHOLD:
                continue

            cls_id = int(box.cls[0])
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            detections.append(
                {
                    "label": names[cls_id],
                    "confidence": float(box.conf[0]),
                    "bbox": [float(x1), float(y1), float(x2), float(y2)],
                }
            )
    return detections


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python detector.py <image_path>")
        sys.exit(1)

    image = cv2.imread(sys.argv[1])
    if image is None:
        print(f"cannot read image: {sys.argv[1]}")
        sys.exit(1)

    print(json.dumps(detect(image), indent=2))
