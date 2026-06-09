"""YOLO inference service.

Single GPU process that batches frames from all IEP2 workers and runs
one TRT inference call per batch. Loaded once; never instantiated per camera.

Architecture:
  IEP2 × N  ──PUSH──►  PULL (yolo_input.sock)
                            ↓ batch collector
                        TRT inference (executor)
                            ↓ per-camera routing
  IEP2 × N  ◄──PUSH──  PUSH(yolo_output_{camera_id}.sock)

R1: TRT engine only — .pt at runtime is banned.
R2: ZMQ PUSH/PULL, not REQ/REP.
R3: Batch released on MAX_BATCH_SIZE frames OR BATCH_TIMEOUT_MS elapsed.
R4: Class 0 (person) only.
R5: ipc:// sockets only.
R7: Health reports NOT_SERVING during engine load, SERVING after warmup.
R8: msgpack serialisation.
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
from prometheus_client import Counter, Gauge, Histogram, start_http_server

log = logging.getLogger("yolo_service")

# ── Configuration ─────────────────────────────────────────────────────────────
YOLO_INPUT_SOCK       = os.environ.get("YOLO_INPUT_SOCK",       "ipc:///tmp/sockets/yolo_input.sock")
YOLO_HEALTH_UNIX_SOCK = os.environ.get("YOLO_HEALTH_SOCK",      "unix:///tmp/sockets/yolo_health.sock")
YOLO_HEALTH_TCP_ADDR  = os.environ.get("YOLO_HEALTH_TCP_ADDR",  "[::]:50052")
YOLO_METRICS_PORT     = int(os.environ.get("YOLO_METRICS_PORT", "9400"))

YOLO_MODEL_VARIANT    = os.environ.get("YOLO_MODEL_VARIANT",     "n")
YOLO_CONF_THRESHOLD   = float(os.environ.get("YOLO_CONF",        "0.25"))
YOLO_IOU_THRESHOLD    = float(os.environ.get("YOLO_IOU",         "0.45"))
MAX_BATCH_SIZE        = int(os.environ.get("YOLO_MAX_BATCH_SIZE",  "32"))
BATCH_TIMEOUT_MS      = float(os.environ.get("YOLO_BATCH_TIMEOUT_MS", "20"))

_MODEL_VERSION = os.environ.get("MODEL_VERSION", "production")

DETECTOR_FRAMES = Counter(
    "detector_frames_total",
    "Total frames processed by the detector service",
)
DETECTOR_DETECTIONS = Counter(
    "detector_detections_total",
    "Person detections returned by the detector service",
    ["model_version"],
)
DETECTOR_ERRORS = Counter(
    "detector_errors_total",
    "Frames that failed to decode or caused detector inference errors",
)
DETECTOR_INFERENCE = Histogram(
    "detector_inference_seconds",
    "Wall-clock detector batch inference time",
    ["model_version"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0],
)
DETECTOR_BATCH_SIZE = Histogram(
    "detector_batch_size",
    "Frames per detector inference batch",
    buckets=[1, 2, 4, 8, 16, 24, 32, 48, 64],
)
DETECTOR_CONFIDENCE = Histogram(
    "detector_detection_confidence",
    "Confidence score of each accepted person detection",
    ["model_version"],
    buckets=[0.25, 0.30, 0.35, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.0],
)
DETECTOR_CONF_MEAN = Gauge(
    "detector_inference_confidence_mean",
    "Mean confidence of person detections in the latest detector batch",
    ["model_version"],
)

# ── Per-camera result sockets ─────────────────────────────────────────────────
# One PUSH socket per camera_id — routes results to the correct IEP2 container.
# Deviation from spec single YOLO_OUTPUT_SOCK: ZMQ PUSH/PULL round-robins across
# all connected consumers; per-camera sockets guarantee correct delivery.
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


# ── Engine loading ─────────────────────────────────────────────────────────────

def _load_engine(variant: str):
    """Load TRT engine exported by scripts/export_yolo_trt.py."""
    from ultralytics import YOLO
    engine_path = f"yolov8{variant}.engine"
    if not os.path.exists(engine_path):
        raise FileNotFoundError(
            f"TRT engine not found: {engine_path}. "
            "Rebuild the image with MODEL_VARIANT build arg set."
        )
    log.info("Loading TRT engine: %s", engine_path)
    return YOLO(engine_path)


def _warmup(model) -> None:
    """One forward pass with a blank frame to warm up CUDA kernels."""
    blank = np.zeros((640, 640, 3), dtype=np.uint8)
    model([blank], verbose=False)
    log.info("TRT warmup complete.")


# ── Inference ─────────────────────────────────────────────────────────────────

def _decode_frame(jpeg_bytes: bytes) -> np.ndarray:
    arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        DETECTOR_ERRORS.inc()
        return np.zeros((640, 640, 3), dtype=np.uint8)
    return frame


def _infer_batch(model, batch_items: list[dict]) -> list[dict]:
    """Batch inference on all frames; R4 filters to class 0 (person) only."""
    frames = [_decode_frame(item["frame"]) for item in batch_items]
    t0 = time.monotonic()
    results = model(
        frames,
        verbose=False,
        conf=YOLO_CONF_THRESHOLD,
        iou=YOLO_IOU_THRESHOLD,
    )
    DETECTOR_INFERENCE.labels(model_version=_MODEL_VERSION).observe(time.monotonic() - t0)
    DETECTOR_BATCH_SIZE.observe(len(batch_items))
    DETECTOR_FRAMES.inc(len(batch_items))

    responses = []
    all_confs = []
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
                DETECTOR_CONFIDENCE.labels(model_version=_MODEL_VERSION).observe(float(conf))
                all_confs.append(float(conf))
        DETECTOR_DETECTIONS.labels(model_version=_MODEL_VERSION).inc(len(detections))
        responses.append({
            "request_id":   item["request_id"],
            "camera_id":    item["camera_id"],
            "timestamp_ms": item["timestamp_ms"],
            "detections":   detections,
        })
    if all_confs:
        DETECTOR_CONF_MEAN.labels(model_version=_MODEL_VERSION).set(sum(all_confs) / len(all_confs))
    return responses


# ── Batch collector ────────────────────────────────────────────────────────────

async def _collect_batch(
    pull_sock: zmq.asyncio.Socket,
) -> list[dict]:
    """Block until first frame arrives, then collect until MAX_BATCH_SIZE or BATCH_TIMEOUT_MS."""
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
    """Serve gRPC health on both unix socket (R5) and TCP (for cross-service checks)."""
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

    start_http_server(YOLO_METRICS_PORT)
    log.info("Prometheus metrics server started on :%d", YOLO_METRICS_PORT)

    health_servicer = health.HealthServicer()
    health_servicer.set("", health_pb2.HealthCheckResponse.NOT_SERVING)  # R7

    asyncio.create_task(_run_health_server(health_servicer))
    await asyncio.sleep(0)  # let health server start accepting before engine load

    log.info("Loading TRT engine  variant=%s  max_batch=%d  timeout_ms=%.0f",
             YOLO_MODEL_VARIANT, MAX_BATCH_SIZE, BATCH_TIMEOUT_MS)
    loop = asyncio.get_running_loop()
    model = await loop.run_in_executor(None, _load_engine, YOLO_MODEL_VARIANT)
    await loop.run_in_executor(None, _warmup, model)

    health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)  # R7
    log.info("YOLO service SERVING  model=yolov8%s.engine", YOLO_MODEL_VARIANT)

    os.makedirs("/tmp/sockets", exist_ok=True)
    ctx = zmq.asyncio.Context.instance()
    pull_sock = ctx.socket(zmq.PULL)
    pull_sock.bind(YOLO_INPUT_SOCK)
    log.info("Bound input socket: %s", YOLO_INPUT_SOCK)

    await _inference_loop(model, pull_sock, ctx)


if __name__ == "__main__":
    asyncio.run(main())
