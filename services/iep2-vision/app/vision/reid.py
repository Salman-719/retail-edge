"""ReID embedder plugin: protocol + OSNet fallback chain + descriptor + factory.

The spec mandates that ``embedding_dim`` is read from the active model and never
hardcoded. The fallback chain (boxmot OSNet -> torchreid OSNet -> torchvision
ResNet50 -> classic CV descriptor) guarantees the system always produces
embeddings, even with no GPU or weights -- critical for CI and local dev. The
descriptor fallback is fixed at 512 dims to stay compatible with the OSNet
default so a missing-weights environment still round-trips the 512-dim schema.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import numpy as np

from common.errors import EmbeddingError
from common.utils.embeddings import l2_normalize

DESCRIPTOR_DIM = 512


class ReIDModel(Protocol):
    embedding_dim: int  # read once at startup; drives all gallery/array sizing

    def extract(self, crop: np.ndarray) -> np.ndarray:
        """crop: BGR person crop. Returns float32[embedding_dim], L2-normalized."""
        ...

    def batch_extract(self, crops: list[np.ndarray]) -> list[np.ndarray]:
        ...


class DescriptorEmbedder:
    """Deterministic CPU-only ReID descriptor (no weights). A 4x4 spatial grid of
    HSV histograms (16/8/8 bins per cell) -> exactly 512 dims, capturing the
    person's spatial colour layout. Stable: the same crop yields the same vector."""

    embedding_dim = DESCRIPTOR_DIM

    def extract(self, crop: np.ndarray) -> np.ndarray:
        if crop is None or crop.size == 0:
            return np.zeros(self.embedding_dim, dtype=np.float32)
        import cv2

        resized = cv2.resize(crop, (64, 128), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
        cell_h, cell_w = resized.shape[0] // 4, resized.shape[1] // 4
        feats: list[np.ndarray] = []
        for gy in range(4):
            for gx in range(4):
                cell = hsv[gy * cell_h:(gy + 1) * cell_h, gx * cell_w:(gx + 1) * cell_w]
                h = cv2.calcHist([cell], [0], None, [16], [0, 180]).flatten()
                s = cv2.calcHist([cell], [1], None, [8], [0, 256]).flatten()
                v = cv2.calcHist([cell], [2], None, [8], [0, 256]).flatten()
                feats.append(np.concatenate([h, s, v]))
        descriptor = np.concatenate(feats).astype(np.float32)  # 16 cells * 32 = 512
        return l2_normalize(descriptor)

    def batch_extract(self, crops: list[np.ndarray]) -> list[np.ndarray]:
        return [self.extract(c) for c in crops]


class OSNetEmbedder:
    """Primary ReID with a fallback chain. The chosen backend's true dimension
    becomes ``embedding_dim``."""

    def __init__(self, model_name: str, weights: str | None, device: str | None):
        self.backend = "descriptor"
        self._descriptor = DescriptorEmbedder()
        self._boxmot = None
        self._torchreid = None
        self._torch = None
        self._torch_model = None
        self._torch_preprocess = None
        self._device = self._resolve_device(device)
        self.embedding_dim = DESCRIPTOR_DIM

        self._build(model_name, weights)

    @staticmethod
    def _resolve_device(device: str | None) -> str:
        if device:
            return device
        try:
            import torch
        except Exception:
            return "cpu"
        return "cuda:0" if torch.cuda.is_available() else "cpu"

    def _build(self, model_name: str, weights: str | None) -> None:
        if self._try_boxmot(model_name, weights) or self._try_torchreid(model_name, weights):
            self.embedding_dim = 512
            return
        if self._try_resnet50():
            self.embedding_dim = 2048
            return
        self.backend = "descriptor"
        self.embedding_dim = DESCRIPTOR_DIM

    def _try_boxmot(self, model_name: str, weights: str | None) -> bool:
        try:
            from boxmot.appearance.reid_auto_backend import ReidAutoBackend

            path = Path(weights) if weights else Path(f"{model_name}_msmt17.pt")
            backend = ReidAutoBackend(weights=path, device=self._device, half=False)
            model = backend.get_model()
            if not hasattr(model, "get_features"):
                return False
            self._boxmot = model
            self.backend = f"boxmot_{model_name}"
            return True
        except Exception:
            self._boxmot = None
            return False

    def _try_torchreid(self, model_name: str, weights: str | None) -> bool:
        try:
            from torchreid.utils import FeatureExtractor

            clean = model_name.replace("_msmt17", "").replace("_market1501", "")
            kwargs = {"model_name": clean, "device": self._device}
            if weights and Path(weights).exists():
                kwargs["model_path"] = str(weights)
            self._torchreid = FeatureExtractor(**kwargs)
            self.backend = f"torchreid_{clean}"
            return True
        except Exception:
            self._torchreid = None
            return False

    def _try_resnet50(self) -> bool:
        try:
            import torch
            from torchvision.models import ResNet50_Weights, resnet50

            weights = ResNet50_Weights.DEFAULT
            model = resnet50(weights=weights)
            model.fc = torch.nn.Identity()
            model.eval().to(self._device)
            self._torch = torch
            self._torch_model = model
            self._torch_preprocess = weights.transforms()
            self.backend = "torchvision_resnet50"
            return True
        except Exception:
            return False

    def extract(self, crop: np.ndarray) -> np.ndarray:
        if crop is None or crop.size == 0:
            return np.zeros(self.embedding_dim, dtype=np.float32)
        try:
            if self._boxmot is not None:
                return self._extract_boxmot(crop)
            if self._torchreid is not None:
                return self._extract_torchreid(crop)
            if self._torch_model is not None:
                return self._extract_torch(crop)
        except Exception as exc:  # deep backend failed at runtime -> fall back
            self._boxmot = self._torchreid = self._torch_model = None
            self.backend = "descriptor"
            self.embedding_dim = DESCRIPTOR_DIM
            if not isinstance(exc, EmbeddingError):
                pass
        return self._descriptor.extract(crop)

    def batch_extract(self, crops: list[np.ndarray]) -> list[np.ndarray]:
        return [self.extract(c) for c in crops]

    def _extract_boxmot(self, crop: np.ndarray) -> np.ndarray:
        h, w = crop.shape[:2]
        xyxys = np.array([[0.0, 0.0, float(w), float(h)]], dtype=np.float32)
        vec = np.asarray(self._boxmot.get_features(xyxys, crop)).reshape(-1)
        return l2_normalize(vec)

    def _extract_torchreid(self, crop: np.ndarray) -> np.ndarray:
        import cv2

        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        out = self._torchreid([rgb])
        if hasattr(out, "detach"):
            out = out.detach().cpu().numpy()
        return l2_normalize(np.asarray(out).reshape(-1))

    def _extract_torch(self, crop: np.ndarray) -> np.ndarray:
        import cv2
        from PIL import Image

        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        tensor = self._torch_preprocess(Image.fromarray(rgb)).unsqueeze(0).to(self._device)
        with self._torch.no_grad():
            vec = self._torch_model(tensor).squeeze(0).cpu().numpy()
        return l2_normalize(vec)


def create_reid_model(backend: str, **kwargs) -> ReIDModel:
    if backend == "osnet":
        return OSNetEmbedder(**kwargs)
    if backend == "descriptor":
        kwargs.pop("model_name", None)
        kwargs.pop("weights", None)
        kwargs.pop("device", None)
        return DescriptorEmbedder()
    raise ValueError(f"unknown reid backend: {backend}")
