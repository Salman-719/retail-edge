"""Person detector plugin: protocol + YOLO11 / RT-DETR / YOLOX-MOT implementations + factory.

Backend and model name come from config, so swapping detectors is a config
change, never a code change downstream. Implementations return only
person-class detections, already confidence-filtered.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

import numpy as np

from common.contracts.detection import Detection
from common.contracts.geometry import BBox

PERSON_CLASS = 0  # COCO person class
BYTETRACK_X_MOT17_GOOGLE_DRIVE_ID = "1P4mY0Yyd3PPTybgZkjMYhFri88nTmJX5"


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


def _torch_device(device: str | None) -> str:
    if device:
        return device
    try:
        import torch

        return "cuda:0" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _download_google_drive_file(file_id: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import gdown
    except Exception as exc:
        raise RuntimeError("gdown is required to download the YOLOX-MOT checkpoint") from exc

    url = f"https://drive.google.com/uc?id={file_id}"
    downloaded = gdown.download(url, str(output_path), quiet=False)
    if not downloaded or not output_path.exists():
        raise RuntimeError(f"Unable to download YOLOX-MOT checkpoint to {output_path}")


def _load_matching_state_dict(model, checkpoint: dict) -> None:
    model_state = model.state_dict()
    raw_state = checkpoint.get("model", checkpoint)
    matching_state = {
        key: value
        for key, value in raw_state.items()
        if key in model_state and tuple(model_state[key].shape) == tuple(value.shape)
    }
    if not matching_state:
        raise RuntimeError("YOLOX checkpoint did not contain compatible weights")
    model.load_state_dict(matching_state, strict=False)


class YoloxMotPersonDetector:
    """YOLOX-X MOT/CrowdHuman-style detector path.

    This backend is optional because the YOLOX package/checkpoint is heavier than
    the default Ultralytics path. Production images can bake both in; local
    development can fall back to YOLO11.
    """

    def __init__(
        self,
        model_name: str,
        confidence: float,
        nms_iou: float,
        device: str | None,
        weights: str | None = None,
        yolox_input_size: tuple[int, int] = (800, 1440),
    ) -> None:
        try:
            import torch
            from yolox.data.data_augment import preproc
            from yolox.exp import get_exp
            from yolox.utils import postprocess
        except Exception as exc:
            raise RuntimeError(
                "YOLOX is required for detector_backend='yolox_mot'. "
                "Bake YOLOX into the model image or enable detector_allow_fallback."
            ) from exc

        model_dir = Path(os.getenv("IEP2_MODEL_DIR", "/app/runtime/models"))
        checkpoint_path = Path(weights) if weights else model_dir / "bytetrack_x_mot17.pth.tar"
        if not checkpoint_path.exists():
            _download_google_drive_file(BYTETRACK_X_MOT17_GOOGLE_DRIVE_ID, checkpoint_path)

        self._torch = torch
        self._preproc = preproc
        self._postprocess = postprocess
        self._conf = confidence
        self._nms = nms_iou
        self._device = _torch_device(device)
        self._input_size = yolox_input_size
        self.model_name = model_name or "bytetrack_x_mot17"

        exp = get_exp(None, "yolox-x")
        exp.num_classes = 1
        exp.test_size = yolox_input_size
        model = exp.get_model()
        checkpoint = torch.load(str(checkpoint_path), map_location="cpu")
        _load_matching_state_dict(model, checkpoint)
        model.eval()
        model.to(self._device)
        self._model = model

    def detect(self, frame: np.ndarray) -> list[Detection]:
        tensor_image, ratio = self._preproc(frame, self._input_size)
        tensor = self._torch.from_numpy(tensor_image).unsqueeze(0).float().to(self._device)
        with self._torch.no_grad():
            outputs = self._model(tensor)
            outputs = self._postprocess(
                outputs,
                num_classes=1,
                conf_thre=self._conf,
                nms_thre=self._nms,
                class_agnostic=True,
            )

        output = outputs[0]
        if output is None or len(output) == 0:
            return []

        data = output.detach().cpu().numpy()
        boxes = data[:, 0:4] / ratio
        scores = data[:, 4] * data[:, 5]
        keep = scores >= self._conf
        return [
            Detection(bbox=BBox(float(x1), float(y1), float(x2), float(y2)), confidence=float(score))
            for (x1, y1, x2, y2), score in zip(boxes[keep], scores[keep])
        ]


def create_detector(backend: str, **kwargs) -> Detector:
    allow_fallback = kwargs.pop("allow_fallback", True)
    fallback_model = kwargs.pop("fallback_model", "yolo11x.pt")
    yolox_input_size = kwargs.pop("yolox_input_size", (800, 1440))
    if backend == "yolo11":
        kwargs.pop("allow_fallback", None)
        return Yolo11PersonDetector(**kwargs)
    if backend == "rtdetr":
        return RtDetrPersonDetector(**kwargs)
    if backend == "yolox_mot":
        try:
            return YoloxMotPersonDetector(**kwargs, yolox_input_size=yolox_input_size)
        except Exception:
            if not allow_fallback:
                raise
            fallback_kwargs = dict(kwargs)
            fallback_kwargs["model_name"] = fallback_model
            return Yolo11PersonDetector(**fallback_kwargs)
    raise ValueError(f"unknown detector backend: {backend}")
