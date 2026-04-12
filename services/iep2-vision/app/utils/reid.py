"""ReID feature extractor for person re-identification.

Uses a lightweight appearance model to extract embeddings from person crops.
Supports comparison via cosine similarity.
"""
import logging
from typing import Optional

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from torchvision import transforms

logger = logging.getLogger(__name__)

# Crop preprocessing: resize to 256x128, normalize
_TRANSFORM = transforms.Compose([
    transforms.ToPILImage(),
    transforms.Resize((256, 128)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])


class ReIDExtractor:
    """Extract appearance embeddings from person crops.

    Uses a pretrained model from torchvision as the backbone.
    In production, replace with OSNet or FastReID for better quality.
    """

    def __init__(self, model_name: str = "mobilenet_v3_small", device: str | None = None):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model_name = model_name
        self._model = None

    @property
    def model(self):
        if self._model is None:
            self._model = self._load_model()
        return self._model

    def _load_model(self):
        """Load a pretrained backbone and strip the classification head."""
        from torchvision import models as tv_models

        if self.model_name == "mobilenet_v3_small":
            base = tv_models.mobilenet_v3_small(weights="DEFAULT")
            # Remove classifier, keep features (outputs 576-dim)
            base.classifier = torch.nn.Identity()
        elif self.model_name == "resnet50":
            base = tv_models.resnet50(weights="DEFAULT")
            base.fc = torch.nn.Identity()
        else:
            base = tv_models.mobilenet_v3_small(weights="DEFAULT")
            base.classifier = torch.nn.Identity()

        base = base.to(self.device)
        base.eval()
        logger.info(f"ReID model loaded: {self.model_name} on {self.device}")
        return base

    def extract(self, crop_bgr: np.ndarray) -> Optional[np.ndarray]:
        """Extract a normalized embedding vector from a BGR person crop.

        Args:
            crop_bgr: OpenCV BGR image of a person crop (any size).

        Returns:
            Normalized embedding as a 1-D numpy array, or None on failure.
        """
        if crop_bgr is None or crop_bgr.size == 0:
            return None

        # Minimum crop size check
        h, w = crop_bgr.shape[:2]
        if h < 32 or w < 16:
            return None

        try:
            crop_rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
            tensor = _TRANSFORM(crop_rgb).unsqueeze(0).to(self.device)

            with torch.no_grad():
                embedding = self.model(tensor)

            # L2-normalize
            embedding = F.normalize(embedding, p=2, dim=1)
            return embedding.cpu().numpy().flatten()
        except Exception as e:
            logger.warning(f"ReID extraction failed: {e}")
            return None

    def extract_batch(self, crops: list[np.ndarray]) -> list[Optional[np.ndarray]]:
        """Extract embeddings for a batch of crops."""
        if not crops:
            return []

        valid_indices = []
        tensors = []
        for i, crop in enumerate(crops):
            if crop is None or crop.size == 0 or crop.shape[0] < 32 or crop.shape[1] < 16:
                continue
            try:
                crop_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
                tensors.append(_TRANSFORM(crop_rgb))
                valid_indices.append(i)
            except Exception:
                continue

        results: list[Optional[np.ndarray]] = [None] * len(crops)
        if not tensors:
            return results

        batch = torch.stack(tensors).to(self.device)
        with torch.no_grad():
            embeddings = self.model(batch)
        embeddings = F.normalize(embeddings, p=2, dim=1).cpu().numpy()

        for idx, vi in enumerate(valid_indices):
            results[vi] = embeddings[idx]

        return results


def cosine_similarity(emb_a: np.ndarray, emb_b: np.ndarray) -> float:
    """Compute cosine similarity between two embeddings."""
    dot = np.dot(emb_a, emb_b)
    norm_a = np.linalg.norm(emb_a)
    norm_b = np.linalg.norm(emb_b)
    if norm_a < 1e-8 or norm_b < 1e-8:
        return 0.0
    return float(dot / (norm_a * norm_b))


def match_against_gallery(
    query_emb: np.ndarray,
    gallery: dict[str, np.ndarray],
    threshold: float = 0.75,
) -> Optional[str]:
    """Match a query embedding against a gallery of known embeddings.

    Args:
        query_emb: The query embedding to match.
        gallery: Dict mapping employee_id -> average embedding.
        threshold: Minimum cosine similarity for a match.

    Returns:
        employee_id of best match, or None if below threshold.
    """
    best_id = None
    best_sim = threshold

    for emp_id, gallery_emb in gallery.items():
        sim = cosine_similarity(query_emb, gallery_emb)
        if sim > best_sim:
            best_sim = sim
            best_id = emp_id

    return best_id
