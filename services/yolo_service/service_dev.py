"""YOLO inference service — CPU dev mode (x86 / Intel, no CUDA).

Identical ZMQ wire protocol to service.py.
Replaces TRT engine with ultralytics YOLO .pt model running on CPU.
For local development only — do NOT deploy to production.

Architecture (unchanged from service.py):
  IEP2 × N  ──PUSH──►  PULL (yolo_input.sock)
                            ↓ batch collector
                        YOLO .pt CPU inference
                            ↓ per-camera routing
  IEP2 × N  ◄──PUSH──  PUSH(yolo_output_{camera_id}.sock)
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

log = logging.getLogger("yolo_service_dev")

# ── Configuration ─────────────────────────────────────────────────────────────
YOLO_INPUT_SOCK       = os.environ.get("YOLO_INPUT_SOCK",        "ipc:///tmp/sockets/yolo_input.sock")
YOLO_HEALTH_UNIX_SOCK = os.environ.get("YOLO_HEALTH_SOCK",       "unix:///tmp/sockets/yolo_health.sock")
YOLO_HEALTH_TCP_ADDR  = os.environ.get("YOLO_HEALTH_TCP_ADDR",   "[::]:50052")

YOLO_MODEL_VARIANT    = os.environ.get("YOLO_MODEL_VARIANT",     "n")
YOLO_CONF_THRESHOLD   = float(os.environ.get("YOLO_CONF",        "0.25"))
YOLO_IOU_THRESHOLD    = float(os.environ.get("YOLO_IOU",         "0.45"))
# Smaller defaults on CPU — ultralytics batching on CPU is slower than TRT.
MAX_BATCH_SIZE        = int(os.environ.get("YOLO_MAX_BATCH_SIZE", "4"))
BATCH_TIMEOUT_MS      = float(os.environ.get("YOLO_BATCH_TIMEOUT_MS", "500"))

# ── Per-camera result sockets ─────────────────────────────────────────────────
_result_sockets: dict[str, zmq.asyncio.Socket] = {}


def _result_sock_addr(camera_id: str) -> str:
    return f"ipc:///tmp/sockets/yolo_output_{camera_id}.sock"


def _get_result_socket(ctx: zmq.asyncio.Context, camera_id: str) -> zmq.asyncio.Socket:
    if camera_id not in _result_sockets:
        sock = ctx.socket(zmq.PUSH)
        sock.connect(_result_sock_addr(camera_id))
        _result_sockets[camera_id] = sock
        log.info("Opened result channel for camera %s", camera_id)
    return _result_sockets[camera_id]


# ── Model loading ──────────────────────────────────────────────────────────────

def _load_model(variant: str):
    """Load ultralytics YOLO .pt model on CPU."""
    from ultralytics import YOLO
    model_path = f"yolov8{variant}.pt"
    if not os.path.exists(model_path):
        raise FileNotFoundError(
            f".pt model not found: {model_path}. "
            "Ensure yolov8n.pt is copied into the image by Dockerfile.dev."
        )
    log.info("Loading model: %s  device=cpu", model_path)
    model = YOLO(model_path)
    return model


def _warmup(model) -> None:
    blank = np.zeros((640, 640, 3), dtype=np.uint8)
    model([blank], verbose=False, device="cpu")
    log.info("CPU warmup complete.")


# ── Inference ─────────────────────────────────────────────────────────────────

def _decode_frame(jpeg_bytes: bytes) -> np.ndarray:
    arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        return np.zeros((640, 640, 3), dtype=np.uint8)
    return frame


def _infer_batch(model, batch_items: list[dict]) -> list[dict]:
    """Batch inference — R4 filters to class 0 (person) only. Identical to service.py."""
    frames = [_decode_frame(item["frame"]) for item in batch_items]
    results = model(
        frames,
        verbose=False,
        conf=YOLO_CONF_THRESHOLD,
        iou=YOLO_IOU_THRESHOLD,
        device="cpu",
    )
    responses = []
    for item, result in zip(batch_items, results):
        detections = []
        if result.boxes is not None:
            class_ids = result.boxes.cls.cpu().numpy().astype(int)
            confs     = result.boxes.conf.cpu().numpy()
            xyxys     = result.boxes.xyxy.cpu().numpy()
            for cls_id, conf, xyxy in zip(class_ids, confs, xyxys):
                if cls_id != 0:   # R4: person only
                    continue
                detections.append({
                    "bbox_xyxy":  [float(x) for x in xyxy],
                    "confidence": float(conf),
                })
        responses.append({
            "request_id":   item["request_id"],
            "camera_id":    item["camera_id"],
            "timestamp_ms": item["timestamp_ms"],
            "detections":   detections,
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
        responses = await loop.run_in_executor(None, _infer_batch, model, batch)
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
    server.add_insecure_port(YOLO_HEALTH_UNIX_SOCK)
    server.add_insecure_port(YOLO_HEALTH_TCP_ADDR)
    await server.start()
    log.info("Health server: unix=%s  tcp=%s", YOLO_HEALTH_UNIX_SOCK, YOLO_HEALTH_TCP_ADDR)
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

    log.info("Loading YOLO .pt model  variant=%s  device=cpu", YOLO_MODEL_VARIANT)
    loop = asyncio.get_running_loop()
    model = await loop.run_in_executor(None, _load_model, YOLO_MODEL_VARIANT)
    await loop.run_in_executor(None, _warmup, model)

    health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)
    log.info("YOLO service (dev/CPU) SERVING  model=yolov8%s.pt", YOLO_MODEL_VARIANT)

    os.makedirs("/tmp/sockets", exist_ok=True)
    ctx = zmq.asyncio.Context.instance()
    pull_sock = ctx.socket(zmq.PULL)
    pull_sock.bind(YOLO_INPUT_SOCK)
    log.info("Bound input socket: %s", YOLO_INPUT_SOCK)

    await _inference_loop(model, pull_sock, ctx)


if __name__ == "__main__":
    asyncio.run(main())
