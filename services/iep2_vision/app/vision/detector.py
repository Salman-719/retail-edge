"""Person detector plugin: protocol + YOLO11 / RT-DETR implementations + factory.

Backend and model name come from config, so swapping detectors is a config
change, never a code change downstream. Implementations return only
person-class detections, already confidence-filtered.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

from common.contracts.detection import Detection
from common.contracts.geometry import BBox

PERSON_CLASS = 0  # COCO person class


class Detector(Protocol):
    def detect(self, frame: np.ndarray) -> list[Detection]:
        """frame: BGR HxWx3 uint8. Returns person detections."""
        ...


class _UltralyticsDetector:
    """Shared base for ultralytics-backed detectors (YOLO11, RT-DETR)."""

    def __init__(
        self,
        model_cls,
        model_name: str,
        confidence: float,
        nms_iou: float,
        device: str | None,
        weights: str | None = None,
    ) -> None:
        self._model = model_cls(weights or model_name)
        self._conf = confidence
        self._nms = nms_iou
        self._device = device

    def detect(self, frame: np.ndarray) -> list[Detection]:
        results = self._model.predict(
            frame,
            conf=self._conf,
            iou=self._nms,
            classes=[PERSON_CLASS],
            device=self._device,
            verbose=False,
        )
        detections: list[Detection] = []
        for r in results:
            for box in r.boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                detections.append(Detection(bbox=BBox(x1, y1, x2, y2), confidence=float(box.conf[0])))
        return detections


class Yolo11PersonDetector(_UltralyticsDetector):
    """Ultralytics YOLO11. Person class only (COCO class 0)."""

    def __init__(self, model_name: str, confidence: float, nms_iou: float, device: str | None,
                 weights: str | None = None) -> None:
        from ultralytics import YOLO

        super().__init__(YOLO, model_name, confidence, nms_iou, device, weights)


class RtDetrPersonDetector(_UltralyticsDetector):
    """RT-DETR (alternative, for the latency-vs-occlusion comparison)."""

    def __init__(self, model_name: str, confidence: float, nms_iou: float, device: str | None,
                 weights: str | None = None) -> None:
        from ultralytics import RTDETR

        super().__init__(RTDETR, model_name, confidence, nms_iou, device, weights)


def create_detector(backend: str, **kwargs) -> Detector:
    if backend == "yolo11":
        return Yolo11PersonDetector(**kwargs)
    if backend == "rtdetr":
        return RtDetrPersonDetector(**kwargs)
    raise ValueError(f"unknown detector backend: {backend}")
