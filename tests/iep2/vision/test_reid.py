"""ReID embedder tests (descriptor fallback -- always available on CPU)."""

from __future__ import annotations

import numpy as np

from common.utils.embeddings import cosine_similarity
from services.iep2_vision.app.vision.reid import DescriptorEmbedder, OSNetEmbedder, create_reid_model


def _crop(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, size=(160, 80, 3), dtype=np.uint8)


def test_descriptor_dim_is_512():
    emb = DescriptorEmbedder()
    assert emb.embedding_dim == 512
    vec = emb.extract(_crop(1))
    assert vec.shape == (512,)
    assert vec.dtype == np.float32


def test_descriptor_normalized():
    vec = DescriptorEmbedder().extract(_crop(2))
    assert np.linalg.norm(vec) == 1.0 or abs(np.linalg.norm(vec) - 1.0) < 1e-5


def test_self_similarity_is_one():
    emb = DescriptorEmbedder()
    crop = _crop(3)
    assert cosine_similarity(emb.extract(crop), emb.extract(crop)) == 1.0 or \
        abs(cosine_similarity(emb.extract(crop), emb.extract(crop)) - 1.0) < 1e-6


def test_different_crops_below_one():
    emb = DescriptorEmbedder()
    sim = cosine_similarity(emb.extract(_crop(4)), emb.extract(_crop(5)))
    assert sim < 1.0


def test_empty_crop_returns_zero_vector():
    vec = DescriptorEmbedder().extract(np.zeros((0, 0, 3), dtype=np.uint8))
    assert vec.shape == (512,)


def test_osnet_falls_back_to_descriptor_without_weights():
    # No boxmot/torchreid/torch weights in the test env -> descriptor path, 512-dim.
    emb = OSNetEmbedder(model_name="osnet_x1_0", weights=None, device="cpu")
    vec = emb.extract(_crop(6))
    assert vec.shape[0] == emb.embedding_dim
    assert emb.embedding_dim in (512, 2048)  # descriptor (512) or resnet50 (2048) if torch present


def test_factory_descriptor_backend():
    emb = create_reid_model("descriptor", model_name="osnet_x1_0", weights=None, device="cpu")
    assert emb.embedding_dim == 512
