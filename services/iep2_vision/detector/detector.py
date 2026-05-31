"""Detector — sole owner of: receive frame, return detections.

Swap YOLO for another model here and nothing outside this file changes.
The model variant lives in MODEL_VARIANT below — the only place model
config is allowed to exist.
"""
import json
import sys

import cv2
import numpy as np

MODEL_VARIANT = "yolov8n.pt"
CONF_THRESHOLD = 0.5


def load_model():
    """Load and return the YOLO model. Call once; pass to detect()."""
    from ultralytics import YOLO
    return YOLO(MODEL_VARIANT)


def detect(model, frame: np.ndarray) -> list[dict]:
    """Run detection on a BGR numpy frame using the provided model.

    Returns a list of {label, confidence, bbox: [x1, y1, x2, y2]} dicts.
    """
    results = model(frame, verbose=False, classes=[0])

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
                    "confidence": conf,
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

    print(json.dumps(detect(load_model(), image), indent=2))
