"""OSNet ReID embedding service — CPU dev mode (x86 / Intel, no CUDA).

Identical ZMQ wire protocol to service.py.
Replaces TRT + pycuda with torchvision ResNet-18 on CPU.
ResNet-18 avgpool outputs exactly 512-dim float32 features — correct dimensionality
for the full pipeline. ReID accuracy is lower than OSNet but the wire format,
L2 normalisation, and 2048-byte embedding payload are identical.
For local development only — do NOT deploy to production.

Architecture (unchanged from service.py):
  IEP2 × N  ──PUSH──►  PULL (osnet_input.sock)
                            ↓ batch collector
                        ResNet-18 CPU inference + L2 norm
                            ↓ per-camera routing
  IEP2 × N  ◄──PUSH──  PUSH(osnet_output_{camera_id}.sock)
"""

import asyncio
import logging
import os
import time

import cv2
import msgpack
import numpy as np
import zmq
import zmq.asyncio

log = logging.getLogger("osnet_service_dev")

# ── Configuration ─────────────────────────────────────────────────────────────
OSNET_INPUT_SOCK       = os.environ.get("OSNET_INPUT_SOCK",        "ipc:///tmp/sockets/osnet_input.sock")
OSNET_HEALTH_UNIX_SOCK = os.environ.get("OSNET_HEALTH_SOCK",       "unix:///tmp/sockets/osnet_health.sock")
OSNET_HEALTH_TCP_ADDR  = os.environ.get("OSNET_HEALTH_TCP_ADDR",   "[::]:50053")
# Smaller defaults on CPU.
MAX_BATCH_SIZE         = int(os.environ.get("OSNET_MAX_BATCH_SIZE",    "8"))
BATCH_TIMEOUT_MS       = float(os.environ.get("OSNET_BATCH_TIMEOUT_MS", "200"))
EMBEDDING_DIM          = 512

# ImageNet normalisation — same constants as production OSNet service (R3).
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD  = np.array([0.229, 0.224, 0.225], dtype=np.float32)

# ── Per-camera result sockets ─────────────────────────────────────────────────
_result_sockets: dict[str, zmq.asyncio.Socket] = {}


def _result_sock_addr(camera_id: str) -> str:
    return f"ipc:///tmp/sockets/osnet_output_{camera_id}.sock"


def _get_result_socket(ctx: zmq.asyncio.Context, camera_id: str) -> zmq.asyncio.Socket:
    if camera_id not in _result_sockets:
        sock = ctx.socket(zmq.PUSH)
        sock.connect(_result_sock_addr(camera_id))
        _result_sockets[camera_id] = sock
        log.info("Opened result channel for camera %s", camera_id)
    return _result_sockets[camera_id]


# ── Model loading ──────────────────────────────────────────────────────────────

def _load_model():
    """Load ResNet-18 up to avgpool, weights pre-downloaded at image build time."""
    import torch
    import torchvision.models as models

    # Weights are baked into the image by Dockerfile.dev — no runtime download.
    base = models.resnet18(weights=models.ResNet18_Weights.DEFAULT)
    # Strip the final FC classifier; avgpool output is [B, 512, 1, 1].
    model = torch.nn.Sequential(*list(base.children())[:-1])
    model.eval()
    log.info("ResNet-18 (dev ReID stub) loaded on CPU  output_dim=%d", EMBEDDING_DIM)
    return model


def _warmup(model) -> None:
    import torch
    blank = torch.zeros(1, 3, 256, 128)
    with torch.no_grad():
        model(blank)
    log.info("CPU warmup complete.")


# ── Preprocessing (mirrors production service R3) ─────────────────────────────

def _preprocess_crop(jpeg_bytes: bytes) -> np.ndarray:
    """JPEG bytes → CHW float32 normalised to ImageNet stats. Same as service.py."""
    arr  = np.frombuffer(jpeg_bytes, dtype=np.uint8)
    crop = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if crop is None:
        crop = np.zeros((256, 128, 3), dtype=np.uint8)
    crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
    crop = cv2.resize(crop, (128, 256))          # W×H = 128×256
    crop = crop.astype(np.float32) / 255.0
    crop = (crop - _MEAN) / _STD
    return crop.transpose(2, 0, 1)               # HWC → CHW float32


# ── L2 normalisation (R5) ─────────────────────────────────────────────────────

def _l2_normalize(emb: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(emb)
    if norm < 1e-8:
        return emb
    return emb / norm


# ── Inference ─────────────────────────────────────────────────────────────────

def _infer_and_pack(model, batch_items: list[dict]) -> list[dict]:
    """ResNet-18 inference → 512-dim L2-normalised float32 bytes per crop."""
    import torch

    tensors = [_preprocess_crop(item["crop"]) for item in batch_items]
    batch   = torch.tensor(np.stack(tensors, axis=0), dtype=torch.float32)  # [B, 3, 256, 128]

    with torch.no_grad():
        feats = model(batch)                         # [B, 512, 1, 1]
    embeddings = feats.squeeze(-1).squeeze(-1).numpy()  # [B, 512]

    responses = []
    for item, emb in zip(batch_items, embeddings):
        assert emb.shape == (EMBEDDING_DIM,), f"Expected ({EMBEDDING_DIM},), got {emb.shape}"
        emb = _l2_normalize(emb)
        responses.append({
            "request_id":   item["request_id"],
            "camera_id":    item["camera_id"],
            "track_id":     item["track_id"],
            "timestamp_ms": item["timestamp_ms"],
            "embedding":    emb.astype(np.float32).tobytes(),   # 2048 bytes, matches R2
        })
    return responses


# ── Batch collector ────────────────────────────────────────────────────────────

async def _collect_batch(pull_sock: zmq.asyncio.Socket) -> list[dict]:
    raw = await pull_sock.recv()
    batch = [msgpack.unpackb(raw, raw=False)]

    deadline = time.monotonic() + BATCH_TIMEOUT_MS / 1000.0
    while len(batch) < MAX_BATCH_SIZE:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            raw = await asyncio.wait_for(pull_sock.recv(), timeout=remaining)
            batch.append(msgpack.unpackb(raw, raw=False))
        except asyncio.TimeoutError:
            break

    return batch


# ── Inference loop ─────────────────────────────────────────────────────────────

async def _inference_loop(
    model,
    pull_sock: zmq.asyncio.Socket,
    ctx: zmq.asyncio.Context,
) -> None:
    loop = asyncio.get_running_loop()
    while True:
        batch = await _collect_batch(pull_sock)
        responses = await loop.run_in_executor(None, _infer_and_pack, model, batch)
        for resp in responses:
            sock = _get_result_socket(ctx, resp["camera_id"])
            await sock.send(msgpack.packb(resp, use_bin_type=True))
        log.debug("Batch processed  size=%d", len(batch))


# ── Health server ──────────────────────────────────────────────────────────────

async def _run_health_server(health_servicer) -> None:
    import grpc.aio
    from grpc_health.v1 import health_pb2_grpc

    server = grpc.aio.server()
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)
    server.add_insecure_port(OSNET_HEALTH_UNIX_SOCK)
    server.add_insecure_port(OSNET_HEALTH_TCP_ADDR)
    await server.start()
    log.info("Health server: unix=%s  tcp=%s", OSNET_HEALTH_UNIX_SOCK, OSNET_HEALTH_TCP_ADDR)
    await server.wait_for_termination()


# ── Entry point ────────────────────────────────────────────────────────────────

async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    from grpc_health.v1 import health, health_pb2

    health_servicer = health.HealthServicer()
    health_servicer.set("", health_pb2.HealthCheckResponse.NOT_SERVING)

    asyncio.create_task(_run_health_server(health_servicer))
    await asyncio.sleep(0)

    log.info("Loading ResNet-18 dev ReID stub (CPU)")
    loop = asyncio.get_running_loop()
    model = await loop.run_in_executor(None, _load_model)
    await loop.run_in_executor(None, _warmup, model)

    health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)
    log.info("OSNet service (dev/CPU) SERVING  model=resnet18  dim=%d", EMBEDDING_DIM)

    os.makedirs("/tmp/sockets", exist_ok=True)
    ctx = zmq.asyncio.Context.instance()
    pull_sock = ctx.socket(zmq.PULL)
    pull_sock.bind(OSNET_INPUT_SOCK)
    log.info("Bound input socket: %s", OSNET_INPUT_SOCK)

    await _inference_loop(model, pull_sock, ctx)


if __name__ == "__main__":
    asyncio.run(main())
