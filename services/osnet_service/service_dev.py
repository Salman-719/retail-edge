"""ReID embedding service — CPU/GPU dev mode (x86 / Intel / NVIDIA).

Identical ZMQ wire protocol to service.py.
Runs resnet50_msmt17 via boxmot (ReidAutoBackend PyTorch backend). The model
outputs 2048-dim float32 features — the production ReID embedding dimensionality.
For local development only — do NOT deploy to production (use Dockerfile/TRT).

Architecture (unchanged from service.py):
  IEP2 × N  ──PUSH──►  PULL (osnet_input.sock)
                            ↓ batch collector
                        resnet50_msmt17 inference + L2 norm
                            ↓ per-camera routing
  IEP2 × N  ◄──PUSH──  PUSH(osnet_output_{camera_id}.sock)
"""

import asyncio
import json
import logging
import os
import threading
import time

import cv2
import msgpack
import numpy as np
import zmq
import zmq.asyncio

log = logging.getLogger("osnet_service_dev")

# ── Device selection (CPU / GPU) shared with the dev pipeline ──────────────────
# Mirrors the detector service: reads the desired device from Redis `inference:device`,
# resolves against real hardware, applies live, and publishes capability to
# `inference:capability:reid`.
_REDIS_URL      = os.environ.get("SERVER_REDIS_URL") or os.environ.get("REDIS_URL", "redis://redis:6379/0")
_DEVICE_KEY     = "inference:device"
_CAP_KEY        = "inference:capability:reid"
_INITIAL_DEVICE = os.environ.get("INFERENCE_DEVICE", "cpu")

_state = {"device": "cpu", "model_device": None}


def _detect_caps() -> dict:
    try:
        import torch
        cuda = bool(torch.cuda.is_available())
        xpu  = bool(getattr(torch, "xpu", None) and torch.xpu.is_available())
    except Exception:
        cuda = xpu = False
    return {"cuda": cuda, "xpu": xpu}


def _resolve_device(requested: str, caps: dict) -> str:
    requested = (requested or "cpu").lower()
    if requested == "cpu":
        return "cpu"
    if requested == "cuda":
        return "cuda" if caps["cuda"] else "cpu"
    if requested == "xpu":
        return "xpu" if caps["xpu"] else "cpu"
    if caps["cuda"]:
        return "cuda"
    if caps["xpu"]:
        return "xpu"
    return "cpu"


def _device_watcher() -> None:
    try:
        import redis
        r = redis.Redis.from_url(_REDIS_URL)
    except Exception as exc:
        log.warning("Device watcher disabled (redis unavailable): %s", exc)
        return
    caps = _detect_caps()
    log.info("ReID GPU capability: cuda=%s xpu=%s", caps["cuda"], caps["xpu"])
    while True:
        try:
            requested = r.get(_DEVICE_KEY)
            requested = requested.decode() if requested else _INITIAL_DEVICE
            resolved = _resolve_device(requested, caps)
            if resolved != _state["device"]:
                log.info("Inference device → %s (requested=%s)", resolved, requested)
                _state["device"] = resolved
            r.set(_CAP_KEY, json.dumps({
                "role": "reid", "cuda": caps["cuda"], "xpu": caps["xpu"],
                "device": _state["device"],
            }), ex=15)
        except Exception as exc:
            log.warning("Device watcher tick failed: %s", exc)
        time.sleep(2)

# ── Configuration ─────────────────────────────────────────────────────────────
OSNET_INPUT_SOCK       = os.environ.get("OSNET_INPUT_SOCK",        "ipc:///tmp/sockets/osnet_input.sock")
OSNET_HEALTH_UNIX_SOCK = os.environ.get("OSNET_HEALTH_SOCK",       "unix:///tmp/sockets/osnet_health.sock")
OSNET_HEALTH_TCP_ADDR  = os.environ.get("OSNET_HEALTH_TCP_ADDR",   "[::]:50053")
OSNET_MODEL_PATH       = os.environ.get("OSNET_MODEL_PATH",        "resnet50_msmt17.pt")
# Smaller defaults on CPU.
MAX_BATCH_SIZE         = int(os.environ.get("OSNET_MAX_BATCH_SIZE",    "8"))
BATCH_TIMEOUT_MS       = float(os.environ.get("OSNET_BATCH_TIMEOUT_MS", "200"))
EMBEDDING_DIM          = 2048

# ImageNet normalisation — same constants boxmot's backend uses (R3).
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
    """Load resnet50_msmt17 via boxmot ReidAutoBackend (weights baked at build time)."""
    import torch
    from pathlib import Path
    from boxmot.appearance.reid_auto_backend import ReidAutoBackend

    device = _state["device"]
    # boxmot select_device expects "cpu" or a CUDA index ("0", "1", …),
    # not PyTorch's "cuda" string.
    boxmot_device = "0" if device == "cuda" else device
    rab = ReidAutoBackend(
        weights=Path(OSNET_MODEL_PATH),
        device=torch.device(boxmot_device) if boxmot_device == "cpu" else boxmot_device,
        half=False,
    )
    _state["model_device"] = device
    log.info("resnet50_msmt17 (boxmot) loaded  device=%s  output_dim=%d", device, EMBEDDING_DIM)
    return rab.model   # PyTorchBackend — owns .model (nn.Module) and .forward()


def _warmup(model) -> None:
    import torch
    device = torch.device(_state["device"])
    blank = torch.zeros(1, 3, 256, 128, device=device)
    model.forward(blank)
    log.info("Warmup complete on device=%s", _state["device"])


# ── Preprocessing ─────────────────────────────────────────────────────────────

def _preprocess_crop(jpeg_bytes: bytes) -> np.ndarray:
    """JPEG bytes → CHW float32 normalised to ImageNet stats."""
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
    """resnet50_msmt17 inference → 2048-dim L2-normalised float32 bytes per crop."""
    import torch

    device = torch.device(_state["device"])
    # Move model onto the active device only when it changes.
    if _state["model_device"] != _state["device"]:
        model.model.to(device)
        _state["model_device"] = _state["device"]

    tensors = [_preprocess_crop(item["crop"]) for item in batch_items]
    batch   = torch.tensor(np.stack(tensors, axis=0), dtype=torch.float32, device=device)  # [B,3,256,128]

    embeddings = model.forward(batch)
    if hasattr(embeddings, "cpu"):
        embeddings = embeddings.cpu().numpy()
    embeddings = np.asarray(embeddings).reshape(len(batch_items), -1)  # [B, 2048]

    responses = []
    for item, emb in zip(batch_items, embeddings):
        assert emb.shape == (EMBEDDING_DIM,), f"Expected ({EMBEDDING_DIM},), got {emb.shape}"
        emb = _l2_normalize(emb)
        responses.append({
            "request_id":   item["request_id"],
            "camera_id":    item["camera_id"],
            "track_id":     item["track_id"],
            "timestamp_ms": item["timestamp_ms"],
            "embedding":    emb.astype(np.float32).tobytes(),   # 8192 bytes
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

    # Resolve initial device, then start the watcher that tracks the dev toggle.
    _state["device"] = _resolve_device(_INITIAL_DEVICE, _detect_caps())
    threading.Thread(target=_device_watcher, name="device-watcher", daemon=True).start()

    log.info("Loading resnet50_msmt17 (boxmot)  device=%s", _state["device"])
    loop = asyncio.get_running_loop()
    model = await loop.run_in_executor(None, _load_model)
    await loop.run_in_executor(None, _warmup, model)

    health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)
    log.info("ReID service (dev) SERVING  model=resnet50_msmt17  dim=%d  device=%s", EMBEDDING_DIM, _state["device"])

    os.makedirs("/tmp/sockets", exist_ok=True)
    ctx = zmq.asyncio.Context.instance()
    pull_sock = ctx.socket(zmq.PULL)
    pull_sock.bind(OSNET_INPUT_SOCK)
    log.info("Bound input socket: %s", OSNET_INPUT_SOCK)

    await _inference_loop(model, pull_sock, ctx)


if __name__ == "__main__":
    asyncio.run(main())
