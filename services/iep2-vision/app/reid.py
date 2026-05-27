from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


def _normalize(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-12:
        return vector.astype(np.float32)
    return (vector / norm).astype(np.float32)


def cosine_distance(left: np.ndarray, right: np.ndarray) -> float:
    return float(1.0 - np.dot(_normalize(left), _normalize(right)))


class AppearanceEmbedder:
    """Deep embedding when available, deterministic CV descriptor as fallback."""

    def __init__(
        self,
        backend: str = "osnet",
        model_name: str = "osnet_x1_0",
        model_path: str | Path | None = None,
        device: str | None = None,
    ) -> None:
        self.backend = "descriptor"
        self._boxmot_reid_model = None
        self._torchreid_extractor = None
        self._torch_model = None
        self._torch_preprocess = None
        self._torch = None
        self._device = self._resolve_device(device)

        if backend == "osnet":
            self._try_load_boxmot_osnet(model_name=model_name, model_path=model_path)
            if self._boxmot_reid_model is not None:
                return
            self._try_load_osnet(model_name=model_name, model_path=model_path)
            if self._torchreid_extractor is not None:
                return

        if backend == "descriptor":
            return

        self._try_load_resnet50()

    def _resolve_device(self, device: str | None) -> str:
        if device:
            return device
        try:
            import torch
        except Exception:
            return "cpu"
        return "cuda:0" if torch.cuda.is_available() else "cpu"

    def _try_load_boxmot_osnet(self, model_name: str, model_path: str | Path | None) -> None:
        try:
            from boxmot.reid import ReID

            from app.storage import RUNTIME_DIR

            path = Path(model_path) if model_path else RUNTIME_DIR / "models" / f"{model_name}_msmt17.pt"
            reid_backend = ReID(
                weights=path,
                device=self._device,
                half=self._device != "cpu",
            )
            reid_model = getattr(reid_backend, "model", reid_backend)
            if not hasattr(reid_model, "get_features"):
                return
            self._boxmot_reid_model = reid_model
            self.backend = f"boxmot_{model_name}_{path.name}"
        except Exception:
            self._boxmot_reid_model = None

    def _try_load_osnet(self, model_name: str, model_path: str | Path | None) -> None:
        try:
            from torchreid.utils import FeatureExtractor

            clean_name = model_name.replace("_msmt17", "").replace("_market1501", "")
            path = Path(model_path) if model_path else None
            kwargs: dict[str, Any] = {
                "model_name": clean_name,
                "device": self._device,
            }
            if path and path.exists():
                kwargs["model_path"] = str(path)
            self._torchreid_extractor = FeatureExtractor(**kwargs)
            suffix = path.name if path and path.exists() else "default"
            self.backend = f"torchreid_{clean_name}_{suffix}"
        except Exception:
            self._torchreid_extractor = None

    def _try_load_resnet50(self) -> None:
        try:
            import torch
            from torchvision.models import ResNet50_Weights, resnet50

            weights = ResNet50_Weights.DEFAULT
            model = resnet50(weights=weights)
            model.fc = torch.nn.Identity()
            model.eval()
            model.to(self._device)
            self._torch = torch
            self._torch_model = model
            self._torch_preprocess = weights.transforms()
            self.backend = "torchvision_resnet50"
        except Exception:
            self.backend = "descriptor"

    def embed(self, crop_bgr: Any) -> np.ndarray:
        if crop_bgr is None or crop_bgr.size == 0:
            return np.zeros(64, dtype=np.float32)

        if self._boxmot_reid_model is not None:
            try:
                return self._embed_boxmot_reid(crop_bgr)
            except Exception:
                self._boxmot_reid_model = None
                self._try_load_osnet(model_name="osnet_x1_0", model_path=None)

        if self._torchreid_extractor is not None:
            try:
                return self._embed_torchreid(crop_bgr)
            except Exception:
                self._torchreid_extractor = None
                self._try_load_resnet50()

        if self._torch_model is not None:
            try:
                return self._embed_torch(crop_bgr)
            except Exception:
                self.backend = "descriptor"

        return self._embed_descriptor(crop_bgr)

    def _embed_torch(self, crop_bgr: Any) -> np.ndarray:
        import cv2
        from PIL import Image

        rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        tensor = self._torch_preprocess(image).unsqueeze(0)
        tensor = tensor.to(self._device)
        with self._torch.no_grad():
            embedding = self._torch_model(tensor).squeeze(0).cpu().numpy()
        return _normalize(embedding)

    def _embed_torchreid(self, crop_bgr: Any) -> np.ndarray:
        import cv2

        rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
        embedding = self._torchreid_extractor([rgb])
        if hasattr(embedding, "detach"):
            embedding = embedding.detach().cpu().numpy()
        embedding_array = np.asarray(embedding)
        return _normalize(embedding_array.reshape(-1))

    def _embed_boxmot_reid(self, crop_bgr: Any) -> np.ndarray:
        height, width = crop_bgr.shape[:2]
        xyxys = np.array([[0.0, 0.0, float(width), float(height)]], dtype=np.float32)
        embedding = self._boxmot_reid_model.get_features(xyxys, crop_bgr)
        embedding_array = np.asarray(embedding)
        return _normalize(embedding_array.reshape(-1))

    def _embed_descriptor(self, crop_bgr: Any) -> np.ndarray:
        import cv2

        resized = cv2.resize(crop_bgr, (64, 128), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
        hist_h = cv2.calcHist([hsv], [0], None, [24], [0, 180]).flatten()
        hist_s = cv2.calcHist([hsv], [1], None, [16], [0, 256]).flatten()
        hist_v = cv2.calcHist([hsv], [2], None, [16], [0, 256]).flatten()

        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        mag, angle = cv2.cartToPolar(gx, gy, angleInDegrees=True)
        grad_hist = np.histogram(angle, bins=8, range=(0, 360), weights=mag)[0]

        descriptor = np.concatenate([hist_h, hist_s, hist_v, grad_hist]).astype(np.float32)
        return _normalize(descriptor)


@dataclass
class GallerySample:
    embedding: np.ndarray
    camera_id: str
    local_track: str
    timestamp_sec: float


@dataclass
class IdentityRecord:
    global_person_id: str
    centroid: np.ndarray
    gallery_samples: list[GallerySample] = field(default_factory=list)
    cameras: set[str] = field(default_factory=set)
    local_tracks: set[str] = field(default_factory=set)
    observations: int = 0
    first_seen_sec: float = 0.0
    last_seen_sec: float = 0.0
    best_match_distance: float | None = None


@dataclass(frozen=True)
class IdentityAssignment:
    global_person_id: str
    match_distance: float | None
    matched_existing_identity: bool
    match_type: str
    merged_global_person_id: str | None = None


class IdentityGallery:
    def __init__(
        self,
        threshold: float,
        min_cross_camera_observations: int = 3,
        gallery_size: int = 6,
    ) -> None:
        self.threshold = threshold
        self.min_cross_camera_observations = min_cross_camera_observations
        self.gallery_size = max(1, gallery_size)
        self._next_id = 1
        self._identities: dict[str, IdentityRecord] = {}
        self._local_to_global: dict[tuple[str, int], str] = {}

    def assign(
        self,
        camera_id: str,
        local_track_id: int,
        embedding: np.ndarray,
        timestamp_sec: float,
    ) -> IdentityAssignment:
        local_key = (camera_id, local_track_id)
        if local_key in self._local_to_global:
            global_id = self._local_to_global[local_key]
            best_id, best_distance = self._find_best_identity(
                camera_id=camera_id,
                embedding=embedding,
                exclude_global_id=global_id,
            )
            if best_id is not None and best_distance is not None and best_distance <= self.threshold:
                source_id = global_id
                target_id = best_id
                target_identity = self._identities[target_id]
                match_type = "local_id_switch_recovered" if camera_id in target_identity.cameras else "cross_camera_reid"
                self._merge_identities(source_id=source_id, target_id=target_id)
                self._local_to_global[local_key] = target_id
                self._update(target_id, camera_id, local_track_id, embedding, timestamp_sec, best_distance)
                return IdentityAssignment(
                    global_person_id=target_id,
                    match_distance=best_distance,
                    matched_existing_identity=True,
                    match_type=match_type,
                    merged_global_person_id=source_id,
                )

            self._update(global_id, camera_id, local_track_id, embedding, timestamp_sec, None)
            return IdentityAssignment(
                global_person_id=global_id,
                match_distance=None,
                matched_existing_identity=True,
                match_type="existing_local_track",
            )

        best_id, best_distance = self._find_best_identity(camera_id=camera_id, embedding=embedding)

        matched = best_id is not None and best_distance is not None and best_distance <= self.threshold
        if matched:
            global_id = best_id
            identity = self._identities[global_id]
            match_type = "local_id_switch_recovered" if camera_id in identity.cameras else "cross_camera_reid"
        else:
            global_id = f"G{self._next_id:03d}"
            self._next_id += 1
            self._identities[global_id] = IdentityRecord(
                global_person_id=global_id,
                centroid=_normalize(embedding),
                first_seen_sec=timestamp_sec,
                last_seen_sec=timestamp_sec,
            )
            match_type = "new_identity"

        self._local_to_global[local_key] = global_id
        self._update(global_id, camera_id, local_track_id, embedding, timestamp_sec, best_distance)
        return IdentityAssignment(
            global_person_id=global_id,
            match_distance=best_distance,
            matched_existing_identity=matched,
            match_type=match_type,
        )

    def _find_best_identity(
        self,
        camera_id: str,
        embedding: np.ndarray,
        exclude_global_id: str | None = None,
    ) -> tuple[str | None, float | None]:
        best_id: str | None = None
        best_distance: float | None = None
        for global_id, identity in self._identities.items():
            if global_id == exclude_global_id:
                continue
            if camera_id not in identity.cameras and identity.observations < self.min_cross_camera_observations:
                continue
            distance = self._best_gallery_distance(identity, embedding)
            if best_distance is None or distance < best_distance:
                best_id = global_id
                best_distance = distance
        return best_id, best_distance

    def _best_gallery_distance(self, identity: IdentityRecord, embedding: np.ndarray) -> float:
        if not identity.gallery_samples:
            return cosine_distance(embedding, identity.centroid)
        return min(cosine_distance(embedding, sample.embedding) for sample in identity.gallery_samples)

    def _merge_identities(self, source_id: str, target_id: str) -> None:
        if source_id == target_id or source_id not in self._identities or target_id not in self._identities:
            return

        source = self._identities.pop(source_id)
        target = self._identities[target_id]
        total_observations = max(1, source.observations + target.observations)
        target.centroid = _normalize(
            (target.centroid * target.observations + source.centroid * source.observations)
            / total_observations
        )
        target.cameras.update(source.cameras)
        target.local_tracks.update(source.local_tracks)
        target.observations += source.observations
        target.first_seen_sec = min(target.first_seen_sec, source.first_seen_sec)
        target.last_seen_sec = max(target.last_seen_sec, source.last_seen_sec)
        if source.best_match_distance is not None:
            if target.best_match_distance is None:
                target.best_match_distance = source.best_match_distance
            else:
                target.best_match_distance = min(target.best_match_distance, source.best_match_distance)
        target.gallery_samples = self._select_diverse_gallery([
            *target.gallery_samples,
            *source.gallery_samples,
        ])

        for local_key, global_id in list(self._local_to_global.items()):
            if global_id == source_id:
                self._local_to_global[local_key] = target_id

    def _select_diverse_gallery(self, samples: list[GallerySample]) -> list[GallerySample]:
        if len(samples) <= self.gallery_size:
            return samples
        if self.gallery_size == 1:
            return [samples[0]]

        best_pair: tuple[GallerySample, GallerySample] | None = None
        best_score = -1.0
        for left_index, left in enumerate(samples):
            for right in samples[left_index + 1:]:
                score = cosine_distance(left.embedding, right.embedding)
                if left.camera_id != right.camera_id:
                    score += 0.05
                if score > best_score:
                    best_score = score
                    best_pair = (left, right)

        selected = list(best_pair or samples[:2])
        while len(selected) < self.gallery_size:
            selected_keys = {id(sample) for sample in selected}
            selected_cameras = {sample.camera_id for sample in selected}
            best_sample: GallerySample | None = None
            best_sample_score = -1.0
            for sample in samples:
                if id(sample) in selected_keys:
                    continue
                min_distance = min(cosine_distance(sample.embedding, chosen.embedding) for chosen in selected)
                camera_bonus = 0.05 if sample.camera_id not in selected_cameras else 0.0
                score = min_distance + camera_bonus
                if score > best_sample_score:
                    best_sample_score = score
                    best_sample = sample
            if best_sample is None:
                break
            selected.append(best_sample)

        return sorted(selected, key=lambda sample: (sample.timestamp_sec, sample.camera_id, sample.local_track))

    def _update(
        self,
        global_id: str,
        camera_id: str,
        local_track_id: int,
        embedding: np.ndarray,
        timestamp_sec: float,
        match_distance: float | None,
    ) -> None:
        identity = self._identities[global_id]
        count = identity.observations
        normalized_embedding = _normalize(embedding)
        identity.centroid = _normalize((identity.centroid * count + normalized_embedding) / max(count + 1, 1))
        identity.cameras.add(camera_id)
        local_track = f"{camera_id}:{local_track_id}"
        identity.local_tracks.add(local_track)
        identity.gallery_samples = self._select_diverse_gallery([
            *identity.gallery_samples,
            GallerySample(
                embedding=normalized_embedding,
                camera_id=camera_id,
                local_track=local_track,
                timestamp_sec=timestamp_sec,
            ),
        ])
        identity.observations += 1
        identity.last_seen_sec = max(identity.last_seen_sec, timestamp_sec)
        if identity.observations == 1:
            identity.first_seen_sec = timestamp_sec
        if match_distance is not None:
            if identity.best_match_distance is None:
                identity.best_match_distance = match_distance
            else:
                identity.best_match_distance = min(identity.best_match_distance, match_distance)

    def to_json(self) -> list[dict[str, Any]]:
        return [
            {
                "global_person_id": identity.global_person_id,
                "cameras": sorted(identity.cameras),
                "local_tracks": sorted(identity.local_tracks),
                "observations": identity.observations,
                "first_seen_sec": round(identity.first_seen_sec, 3),
                "last_seen_sec": round(identity.last_seen_sec, 3),
                "gallery_size": len(identity.gallery_samples),
                "gallery_cameras": sorted({sample.camera_id for sample in identity.gallery_samples}),
                "best_match_distance": (
                    None if identity.best_match_distance is None else round(identity.best_match_distance, 4)
                ),
            }
            for identity in sorted(self._identities.values(), key=lambda item: item.global_person_id)
        ]

    def gallery_to_json(self, include_vectors: bool = True) -> list[dict[str, Any]]:
        rows = []
        for identity in sorted(self._identities.values(), key=lambda item: item.global_person_id):
            embeddings = []
            for index, sample in enumerate(identity.gallery_samples, start=1):
                row: dict[str, Any] = {
                    "slot": index,
                    "camera_id": sample.camera_id,
                    "local_track": sample.local_track,
                    "timestamp_sec": round(sample.timestamp_sec, 3),
                }
                if include_vectors:
                    row["embedding"] = [round(float(value), 6) for value in sample.embedding.tolist()]
                embeddings.append(row)

            rows.append({
                "global_person_id": identity.global_person_id,
                "max_embeddings": self.gallery_size,
                "embedding_count": len(identity.gallery_samples),
                "selection": "farthest-first cosine diversity with cross-camera coverage bonus",
                "match_rule": "same identity when the minimum cosine distance to any saved embedding is <= match_threshold",
                "embeddings": embeddings,
            })
        return rows
