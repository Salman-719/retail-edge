"""YOLOv8 client — delegates frame inference to the shared yolo-service via ZMQ.

IEP2 no longer loads or owns the YOLO model. It submits JPEG frames to the
yolo-service over a ZMQ PUSH socket and receives person-only detections on a
per-camera PULL socket.

Transport: ipc:// only (R5). Serialisation: msgpack only (R8).
"""
import asyncio
import logging
import os
import uuid

import cv2
import msgpack
import numpy as np
import zmq.asyncio

log = logging.getLogger("iep2.detector")

# ── Socket addresses ──────────────────────────────────────────────────────────
YOLO_INPUT_SOCK = os.environ.get("YOLO_INPUT_SOCK", "ipc:///tmp/sockets/yolo_input.sock")

# ── Inference deadline ────────────────────────────────────────────────────────
# A stalled yolo-service must never hang IEP2 forever. Each detect() awaits its
# result with a deadline; the batch path (detect_batch) scales the budget by the
# number of frames so a large batch queued behind other cameras does not
# false-timeout its tail. On deadline the frame falls back to [] (no detections).
YOLO_REQUEST_TIMEOUT_S = float(os.environ.get("YOLO_REQUEST_TIMEOUT_S", "5.0"))
YOLO_BATCH_PER_FRAME_S = float(os.environ.get("YOLO_BATCH_PER_FRAME_S", "0.1"))

try:
    from ..metrics import IEP2_INFERENCE_TIMEOUTS
except ImportError:  # pragma: no cover — bare-cwd import inside the container
    from metrics import IEP2_INFERENCE_TIMEOUTS


def _result_sock_addr(camera_id: str) -> str:
    """Per-camera result socket — IEP2 binds, yolo-service connects."""
    return f"ipc:///tmp/sockets/yolo_output_{camera_id}.sock"


# ── Client ────────────────────────────────────────────────────────────────────

class YoloClient:
    """Async ZMQ client for the shared yolo-service.

    Lifecycle: call start() before detect(), close() when done.
    """

    def __init__(self, camera_id: str):
        self._camera_id = camera_id
        self._ctx  = zmq.asyncio.Context.instance()

        # PUSH to shared yolo-service input (all cameras share this socket).
        self._push = self._ctx.socket(zmq.PUSH)
        self._push.connect(YOLO_INPUT_SOCK)

        # PULL bound per camera — yolo-service connects PUSH to this address.
        # Binding here ensures each IEP2 container gets exactly its own results.
        self._pull = self._ctx.socket(zmq.PULL)
        self._pull.bind(_result_sock_addr(camera_id))

        # In-flight requests: request_id → Future[detections]
        self._pending: dict[str, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None
        self._timeouts = 0  # cumulative inference-deadline fallbacks (batch stats)

    async def start(self) -> None:
        """Start the background reader loop. Must be called inside a running event loop."""
        self._reader_task = asyncio.create_task(self._reader_loop())

    async def close(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        self._push.close(linger=0)
        self._pull.close(linger=0)

    async def _reader_loop(self) -> None:
        """Receive results from yolo-service and resolve pending Futures."""
        while True:
            try:
                raw  = await self._pull.recv()
                resp = msgpack.unpackb(raw, raw=False)
                req_id = resp.get("request_id")
                fut = self._pending.pop(req_id, None)
                if fut and not fut.done():
                    # Normalise yolo-service format → IEP2 pipeline format.
                    detections = [
                        {
                            "label":      "person",
                            "confidence": d["confidence"],
                            "bbox":       d["bbox_xyxy"],
                        }
                        for d in resp.get("detections", [])
                    ]
                    fut.set_result(detections)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.warning("Reader loop error: %s", exc)

    async def detect(
        self,
        frame: np.ndarray,
        timestamp_ms: int,
    ) -> list[dict]:
        """Send frame to yolo-service and await person detections.

        Returns list of {"label", "confidence", "bbox"} dicts compatible with
        the existing BoTSORT pipeline.
        """
        req_id = str(uuid.uuid4())
        fut = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut

        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            log.warning("JPEG encode failed for camera %s — skipping frame", self._camera_id)
            del self._pending[req_id]
            return []

        payload = msgpack.packb(
            {
                "request_id":   req_id,
                "camera_id":    self._camera_id,
                "timestamp_ms": timestamp_ms,
                "frame":        buf.tobytes(),
            },
            use_bin_type=True,
        )
        await self._push.send(payload)
        try:
            return await asyncio.wait_for(fut, timeout=YOLO_REQUEST_TIMEOUT_S)
        except asyncio.TimeoutError:
            self._timeouts += 1
            IEP2_INFERENCE_TIMEOUTS.labels(camera_id=self._camera_id, service="yolo").inc()
            log.warning(
                "YOLO inference timeout camera=%s req=%s after %.1fs — empty fallback",
                self._camera_id, req_id, YOLO_REQUEST_TIMEOUT_S,
            )
            return []
        finally:
            self._pending.pop(req_id, None)

    async def detect_batch(
        self,
        frames: list[np.ndarray],
        timestamps_ms: list[int],
    ) -> list[list[dict]]:
        """Send a batch of frames concurrently and await all results.

        Dispatches all frames to yolo-service in one asyncio step, then awaits
        each result under one batch-wide deadline. Order of results matches input
        order. Frames that fail JPEG encoding, or whose result misses the
        deadline, are returned as empty detection lists — one slow/lost frame
        never sinks the rest, and a wedged service never hangs the batch forever.
        """
        loop = asyncio.get_running_loop()
        futs: list[asyncio.Future] = []
        req_ids: list[str | None] = []  # None marks a pre-resolved (encode-failed) slot
        for frame, ts in zip(frames, timestamps_ms):
            req_id = str(uuid.uuid4())
            fut = loop.create_future()
            self._pending[req_id] = fut

            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not ok:
                log.warning("JPEG encode failed for camera %s ts=%d — skipping", self._camera_id, ts)
                del self._pending[req_id]
                placeholder = loop.create_future()
                placeholder.set_result([])
                futs.append(placeholder)
                req_ids.append(None)
                continue

            payload = msgpack.packb(
                {
                    "request_id":   req_id,
                    "camera_id":    self._camera_id,
                    "timestamp_ms": ts,
                    "frame":        buf.tobytes(),
                },
                use_bin_type=True,
            )
            await self._push.send(payload)
            futs.append(fut)
            req_ids.append(req_id)

        # One wall-clock budget for the whole batch, scaled by frame count so a
        # large batch queued behind other cameras does not false-timeout its tail.
        deadline = loop.time() + YOLO_REQUEST_TIMEOUT_S + YOLO_BATCH_PER_FRAME_S * len(frames)
        results: list[list[dict]] = []
        for fut, req_id in zip(futs, req_ids):
            try:
                remaining = max(0.0, deadline - loop.time())
                results.append(await asyncio.wait_for(fut, timeout=remaining))
            except asyncio.TimeoutError:
                self._timeouts += 1
                IEP2_INFERENCE_TIMEOUTS.labels(camera_id=self._camera_id, service="yolo").inc()
                log.warning(
                    "YOLO batch timeout camera=%s req=%s — empty fallback for frame",
                    self._camera_id, req_id,
                )
                results.append([])
            finally:
                if req_id is not None:
                    self._pending.pop(req_id, None)
        return results
