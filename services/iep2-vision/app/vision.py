from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.tracking import as_float_bbox


@dataclass
class TrackedDetection:
    local_track_id: int
    bbox: list[float]
    confidence: float


BYTETRACK_X_MOT17_GOOGLE_DRIVE_ID = "1P4mY0Yyd3PPTybgZkjMYhFri88nTmJX5"


def _torch_device(device: str | None) -> str:
    if device:
        return device
    try:
        import torch

        return "cuda:0" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _resolve_model_path(value: str | None, runtime_dir: Path, filename: str) -> Path:
    if value:
        path = Path(value)
        if path.exists():
            return path
        return runtime_dir / filename if not path.is_absolute() else path
    return runtime_dir / filename


def _download_google_drive_file(file_id: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import gdown
    except Exception as exc:  # pragma: no cover - dependency availability is environment-specific
        raise RuntimeError(
            "gdown is required to download the YOLOX-X MOT checkpoint. "
            "Install services/iep2-vision/requirements.txt or set detector_weights to a local checkpoint."
        ) from exc

    url = f"https://drive.google.com/uc?id={file_id}"
    downloaded = gdown.download(url, str(output_path), quiet=False)
    if not downloaded or not output_path.exists():
        raise RuntimeError(f"Unable to download YOLOX-X MOT checkpoint to {output_path}.")


def _load_matching_state_dict(model: Any, checkpoint: dict[str, Any]) -> None:
    model_state = model.state_dict()
    raw_state = checkpoint.get("model", checkpoint)
    matching_state = {
        key: value
        for key, value in raw_state.items()
        if key in model_state and tuple(model_state[key].shape) == tuple(value.shape)
    }
    missing = len(model_state) - len(matching_state)
    if not matching_state:
        raise RuntimeError("YOLOX checkpoint did not contain weights compatible with the YOLOX-X model.")
    model.load_state_dict(matching_state, strict=False)
    if missing:
        print(f"Loaded YOLOX checkpoint with {missing} unmatched layers ignored.")


class YoloxMotDetector:
    def __init__(
        self,
        checkpoint_path: Path,
        confidence_threshold: float,
        nms_threshold: float,
        input_size: tuple[int, int],
        device: str | None = None,
    ) -> None:
        try:
            import torch
            from yolox.data.data_augment import preproc
            from yolox.exp import get_exp
            from yolox.utils import postprocess
        except Exception as exc:  # pragma: no cover - dependency availability is environment-specific
            raise RuntimeError(
                "YOLOX is required for detector_backend='yolox_mot'. "
                "Install services/iep2-vision/requirements.txt."
            ) from exc

        self.confidence_threshold = confidence_threshold
        self.nms_threshold = nms_threshold
        self.input_size = input_size
        self.device = _torch_device(device)
        self._torch = torch
        self._preproc = preproc
        self._postprocess = postprocess

        exp = get_exp(None, "yolox-x")
        exp.num_classes = 1
        exp.test_size = input_size
        model = exp.get_model()
        checkpoint = torch.load(str(checkpoint_path), map_location="cpu")
        _load_matching_state_dict(model, checkpoint)
        model.eval()
        model.to(self.device)
        self.model = model

    def detect_people(self, frame: Any) -> np.ndarray:
        tensor_image, ratio = self._preproc(frame, self.input_size)
        tensor = self._torch.from_numpy(tensor_image).unsqueeze(0).float().to(self.device)
        with self._torch.no_grad():
            outputs = self.model(tensor)
            outputs = self._postprocess(
                outputs,
                num_classes=1,
                conf_thre=self.confidence_threshold,
                nms_thre=self.nms_threshold,
                class_agnostic=True,
            )

        output = outputs[0]
        if output is None or len(output) == 0:
            return np.empty((0, 6), dtype=np.float32)

        data = output.detach().cpu().numpy()
        boxes = data[:, 0:4] / ratio
        scores = data[:, 4] * data[:, 5]
        keep = scores >= self.confidence_threshold
        if not np.any(keep):
            return np.empty((0, 6), dtype=np.float32)

        detections = np.zeros((int(np.sum(keep)), 6), dtype=np.float32)
        detections[:, 0:4] = boxes[keep]
        detections[:, 4] = scores[keep]
        detections[:, 5] = 0.0
        return detections


class UltralyticsYoloPersonDetector:
    def __init__(
        self,
        model_name: str,
        detector_weights: str | None,
        confidence_threshold: float,
        nms_threshold: float,
        device: str | None = None,
    ) -> None:
        try:
            from ultralytics import YOLO
        except Exception as exc:  # pragma: no cover - dependency availability is environment-specific
            raise RuntimeError(
                "ultralytics is required for detector_backend='ultralytics_yolo'. "
                "Install services/iep2-vision/requirements.txt."
            ) from exc

        self.model_name = detector_weights or model_name
        self.confidence_threshold = confidence_threshold
        self.nms_threshold = nms_threshold
        self.device = device
        self.model = YOLO(self.model_name)

    def detect_people(self, frame: Any) -> np.ndarray:
        kwargs: dict[str, Any] = {
            "classes": [0],
            "conf": self.confidence_threshold,
            "iou": self.nms_threshold,
            "verbose": False,
        }
        if self.device:
            kwargs["device"] = self.device

        result = self.model.predict(frame, **kwargs)[0]
        boxes = result.boxes
        if boxes is None or len(boxes) == 0:
            return np.empty((0, 6), dtype=np.float32)

        xyxy = boxes.xyxy.cpu().numpy()
        confs = boxes.conf.cpu().numpy()
        detections = np.zeros((len(xyxy), 6), dtype=np.float32)
        detections[:, 0:4] = xyxy
        detections[:, 4] = confs
        detections[:, 5] = 0.0
        return detections


def _create_boxmot_botsort_tracker(
    reid_weights: str | None,
    confidence_threshold: float,
    device: str | None,
) -> Any:
    try:
        from boxmot.reid import ReID
        from boxmot.trackers.botsort.botsort import BotSort
    except Exception as exc:  # pragma: no cover - dependency availability is environment-specific
        raise RuntimeError(
            "boxmot is required for tracker_backend='boxmot_botsort'. "
            "Install services/iep2-vision/requirements.txt."
        ) from exc

    from app.storage import RUNTIME_DIR

    model_dir = RUNTIME_DIR / "models"
    resolved_device = _torch_device(device)
    reid_path = Path(reid_weights) if reid_weights else model_dir / "osnet_x1_0_msmt17.pt"
    reid_backend = ReID(
        weights=reid_path,
        device=resolved_device,
        half=resolved_device != "cpu",
    )
    reid_model = getattr(reid_backend, "model", reid_backend)
    return BotSort(
        reid_model=reid_model,
        track_high_thresh=confidence_threshold,
        new_track_thresh=confidence_threshold,
        with_reid=True,
    )


class BoxMotYoloxBotSortReidTracker:
    def __init__(
        self,
        detector_weights: str | None,
        confidence_threshold: float,
        nms_threshold: float,
        input_size: tuple[int, int],
        reid_weights: str | None,
        device: str | None = None,
    ) -> None:
        from app.storage import RUNTIME_DIR

        model_dir = RUNTIME_DIR / "models"
        detector_path = _resolve_model_path(detector_weights, model_dir, "bytetrack_x_mot17.pth.tar")
        if not detector_path.exists():
            _download_google_drive_file(BYTETRACK_X_MOT17_GOOGLE_DRIVE_ID, detector_path)

        self.detector = YoloxMotDetector(
            checkpoint_path=detector_path,
            confidence_threshold=confidence_threshold,
            nms_threshold=nms_threshold,
            input_size=input_size,
            device=device,
        )

        reid_path = Path(reid_weights) if reid_weights else model_dir / "osnet_x1_0_msmt17.pt"
        self.reid_weights = reid_path
        self.tracker_name = "boxmot_botsort_reid"
        self.model_name = "bytetrack_x_mot17"
        self.device = _torch_device(device)
        self.tracker = _create_boxmot_botsort_tracker(reid_weights, confidence_threshold, device)

    def track_people(self, frame: Any) -> list[TrackedDetection]:
        detections = self.detector.detect_people(frame)
        tracks = self.tracker.update(detections, frame)
        if tracks is None or len(tracks) == 0:
            return []

        tracked: list[TrackedDetection] = []
        for row in np.asarray(tracks):
            if len(row) < 6:
                continue
            x1, y1, x2, y2, track_id, confidence = row[:6]
            tracked.append(
                TrackedDetection(
                    local_track_id=int(track_id),
                    bbox=[float(x1), float(y1), float(x2), float(y2)],
                    confidence=float(confidence),
                )
            )
        return tracked


class BoxMotUltralyticsYoloBotSortReidTracker:
    def __init__(
        self,
        model_name: str,
        detector_weights: str | None,
        confidence_threshold: float,
        nms_threshold: float,
        reid_weights: str | None,
        device: str | None = None,
    ) -> None:
        self.detector = UltralyticsYoloPersonDetector(
            model_name=model_name,
            detector_weights=detector_weights,
            confidence_threshold=confidence_threshold,
            nms_threshold=nms_threshold,
            device=device,
        )
        self.reid_weights = Path(reid_weights) if reid_weights else None
        self.tracker_name = "boxmot_botsort_reid"
        self.model_name = model_name
        self.device = _torch_device(device)
        self.tracker = _create_boxmot_botsort_tracker(reid_weights, confidence_threshold, device)

    def track_people(self, frame: Any) -> list[TrackedDetection]:
        detections = self.detector.detect_people(frame)
        tracks = self.tracker.update(detections, frame)
        if tracks is None or len(tracks) == 0:
            return []

        tracked: list[TrackedDetection] = []
        for row in np.asarray(tracks):
            if len(row) < 6:
                continue
            x1, y1, x2, y2, track_id, confidence = row[:6]
            tracked.append(
                TrackedDetection(
                    local_track_id=int(track_id),
                    bbox=[float(x1), float(y1), float(x2), float(y2)],
                    confidence=float(confidence),
                )
            )
        return tracked


class RtDetrBotSortReidTracker:
    def __init__(
        self,
        model_name: str,
        confidence_threshold: float,
        tracker_config: str | Path,
        device: str | None = None,
    ) -> None:
        try:
            from ultralytics import RTDETR
        except Exception as exc:  # pragma: no cover - dependency availability is environment-specific
            raise RuntimeError(
                "ultralytics is required for RT-DETR tracking. Install services/iep2-vision/requirements.txt."
            ) from exc

        self.model_name = model_name
        self.confidence_threshold = confidence_threshold
        self.tracker_config = str(tracker_config)
        self.device = device
        self.model = RTDETR(model_name)

    def track_people(self, frame: Any) -> list[TrackedDetection]:
        kwargs: dict[str, Any] = {
            "classes": [0],
            "conf": self.confidence_threshold,
            "persist": True,
            "tracker": self.tracker_config,
            "verbose": False,
        }
        if self.device:
            kwargs["device"] = self.device

        result = self.model.track(frame, **kwargs)[0]
        boxes = result.boxes
        if boxes is None or len(boxes) == 0:
            return []
        if boxes.id is None:
            return []

        xyxy = boxes.xyxy.cpu().numpy()
        confs = boxes.conf.cpu().numpy()
        ids = boxes.id.cpu().numpy().astype(int)
        return [
            TrackedDetection(local_track_id=int(track_id), bbox=as_float_bbox(box), confidence=float(conf))
            for track_id, box, conf in zip(ids, xyxy, confs)
        ]


def create_people_tracker(
    detector_backend: str,
    tracker_backend: str,
    detector_model: str,
    detector_weights: str | None,
    confidence_threshold: float,
    nms_threshold: float,
    yolox_input_size: tuple[int, int],
    tracker_config: str | Path,
    reid_weights: str | None,
    device: str | None = None,
) -> Any:
    if detector_backend == "ultralytics_yolo" and tracker_backend == "boxmot_botsort":
        return BoxMotUltralyticsYoloBotSortReidTracker(
            model_name=detector_model,
            detector_weights=detector_weights,
            confidence_threshold=confidence_threshold,
            nms_threshold=nms_threshold,
            reid_weights=reid_weights,
            device=device,
        )

    if detector_backend == "yolox_mot" and tracker_backend == "boxmot_botsort":
        return BoxMotYoloxBotSortReidTracker(
            detector_weights=detector_weights,
            confidence_threshold=confidence_threshold,
            nms_threshold=nms_threshold,
            input_size=yolox_input_size,
            reid_weights=reid_weights,
            device=device,
        )

    if detector_backend == "rtdetr" and tracker_backend == "ultralytics_botsort":
        return RtDetrBotSortReidTracker(
            model_name=detector_model,
            confidence_threshold=confidence_threshold,
            tracker_config=tracker_config,
            device=device,
        )

    raise RuntimeError(
        f"Unsupported detector/tracker combination: detector_backend={detector_backend}, "
        f"tracker_backend={tracker_backend}."
    )
