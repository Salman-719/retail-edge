"""ReID client — delegates crop embedding to the shared reid-service via ZMQ.

IEP2 no longer loads or owns ReID weights. It extracts the person crop from the
full frame, JPEG-encodes it, and submits it to the reid-service. The service
handles all preprocessing (R3), runs inference (resnet50_msmt17), L2-normalises
(R5), and returns 2048-dim float32 bytes.

Transport: ipc:// only. Serialisation: msgpack only.
Swap the ReID model in reid-service — nothing outside this file changes.
"""
import asyncio
import logging
import os
import uuid

import cv2
import msgpack
import numpy as np
import zmq.asyncio

log = logging.getLogger("iep2.reid")

EMBEDDING_DIM = 2048
REID_INPUT_SOCK = os.environ.get("REID_INPUT_SOCK", "ipc:///tmp/sockets/reid_input.sock")

# ── Inference deadline ────────────────────────────────────────────────────────
# A stalled reid-service must never hang IEP2. extract() awaits its embedding with
# a deadline; on expiry it returns None (no embedding) — already the handled
# fallback at every caller in the identity manager (`if emb is not None`).
REID_REQUEST_TIMEOUT_S = float(os.environ.get("REID_REQUEST_TIMEOUT_S", "3.0"))

try:
    from ..metrics import IEP2_INFERENCE_TIMEOUTS
except ImportError:  # pragma: no cover — bare-cwd import inside the container
    from metrics import IEP2_INFERENCE_TIMEOUTS


def _result_sock_addr(camera_id: str) -> str:
    """Per-camera result socket — IEP2 binds, reid-service connects."""
    return f"ipc:///tmp/sockets/reid_output_{camera_id}.sock"


class ReidClient:
    """Async ZMQ client for the shared reid-service.

    Lifecycle: call start() before extract(), close() when done.
    """

    def __init__(self, camera_id: str):
        self._camera_id = camera_id
        self._ctx  = zmq.asyncio.Context.instance()

        self._push = self._ctx.socket(zmq.PUSH)
        self._push.connect(REID_INPUT_SOCK)

        # Bind per-camera result socket — reid-service connects PUSH to this.
        self._pull = self._ctx.socket(zmq.PULL)
        self._pull.bind(_result_sock_addr(camera_id))

        self._pending: dict[str, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None
        self._timeouts = 0  # cumulative inference-deadline fallbacks (batch stats)

    async def start(self) -> None:
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
        while True:
            try:
                raw  = await self._pull.recv()
                resp = msgpack.unpackb(raw, raw=False)
                req_id = resp.get("request_id")
                fut = self._pending.pop(req_id, None)
                if fut and not fut.done():
                    emb_bytes = resp.get("embedding")
                    if emb_bytes:
                        emb = np.frombuffer(emb_bytes, dtype=np.float32).copy()
                        fut.set_result(emb if emb.shape == (EMBEDDING_DIM,) else None)
                    else:
                        fut.set_result(None)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.warning("ReID reader loop error: %s", exc)

    async def extract(
        self,
        frame: np.ndarray,
        bbox: list,
        track_id: int,
        timestamp_ms: int,
    ) -> np.ndarray | None:
        """Extract ReID embedding for the person at bbox.

        Clamps bbox to frame boundaries; returns None for zero-area crops.
        Returns (2048,) float32 L2-normalised embedding from reid-service.
        """
        h, w = frame.shape[:2]
        x1 = max(0, int(bbox[0]))
        y1 = max(0, int(bbox[1]))
        x2 = min(w, int(bbox[2]))
        y2 = min(h, int(bbox[3]))
        if x2 <= x1 or y2 <= y1:
            return None

        crop = frame[y1:y2, x1:x2]
        ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            log.warning("JPEG encode failed for crop  camera=%s  track=%d", self._camera_id, track_id)
            return None

        req_id = str(uuid.uuid4())
        fut = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut

        payload = msgpack.packb(
            {
                "request_id":   req_id,
                "camera_id":    self._camera_id,
                "track_id":     track_id,
                "timestamp_ms": timestamp_ms,
                "crop":         buf.tobytes(),
            },
            use_bin_type=True,
        )
        await self._push.send(payload)
        try:
            return await asyncio.wait_for(fut, timeout=REID_REQUEST_TIMEOUT_S)
        except asyncio.TimeoutError:
            self._timeouts += 1
            IEP2_INFERENCE_TIMEOUTS.labels(camera_id=self._camera_id, service="reid").inc()
            log.warning(
                "ReID inference timeout camera=%s track=%d req=%s after %.1fs — None fallback",
                self._camera_id, track_id, req_id, REID_REQUEST_TIMEOUT_S,
            )
            return None
        finally:
            self._pending.pop(req_id, None)
