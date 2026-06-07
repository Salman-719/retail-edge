"""CameraWorker — per-camera capture thread + async window manager.

One CameraWorker is created per AddCamera call.  Blocking cv2 capture runs in
a dedicated OS thread; the async window manager runs on the shared event loop.
"""
import asyncio
import json
import logging
import os
import shutil
import threading
import time

import cv2
import redis.asyncio as aioredis

from services.iep1_ingestion.app.window import WindowAccumulator

logger = logging.getLogger(__name__)

TMPFS_ROOT    = os.environ.get("TMPFS_FRAME_ROOT", "/dev/shm/frames")
JPEG_QUALITY  = int(os.environ.get("JPEG_QUALITY", "85"))
STREAM_PREFIX = "stream:iep1"
STREAM_MAXLEN = 1000


def now_ms() -> int:
    return int(time.time() * 1000)


def _write_to_tmpfs(camera_id: str, ts_ms: int, frame) -> str | None:
    success, buf = cv2.imencode(
        ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
    )
    if not success or buf is None:
        logger.warning("Frame encode failed camera=%s ts=%d", camera_id, ts_ms)
        return None
    path = f"{TMPFS_ROOT}/{camera_id}/{ts_ms}.jpg"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(buf.tobytes())
    return path


class CameraWorker:
    def __init__(self, config) -> None:
        self._config         = config
        self._stop_event     = threading.Event()
        self._frames_dropped = 0
        self._last_frame_ts  = 0
        self._status         = "stopped"
        self._loop: asyncio.AbstractEventLoop | None = None
        self._frame_queue: asyncio.Queue | None = None
        self._thread: threading.Thread | None = None
        self._window_task: asyncio.Task | None = None
        self._redis: aioredis.Redis | None = None
        self._batch_number   = 0

    # ── Public interface ──────────────────────────────────────────────────────

    @property
    def camera_id(self) -> str:
        return self._config.camera_id

    @property
    def status(self) -> str:
        return self._status

    @property
    def last_frame_ts(self) -> int:
        return self._last_frame_ts

    @property
    def frames_dropped(self) -> int:
        return self._frames_dropped

    async def start(self, redis: aioredis.Redis) -> None:
        self._loop        = asyncio.get_running_loop()
        self._frame_queue = asyncio.Queue(maxsize=30)
        self._redis       = redis
        self._thread = threading.Thread(
            target=self._capture_loop, daemon=True,
            name=f"iep1-capture-{self._config.camera_id}",
        )
        self._thread.start()
        self._status      = "capturing"
        self._window_task = asyncio.create_task(
            self._window_loop(), name=f"window-{self._config.camera_id}"
        )

    async def stop(self) -> None:
        self._status = "stopped"
        self._stop_event.set()

        if self._window_task and not self._window_task.done():
            self._window_task.cancel()
            try:
                await self._window_task
            except asyncio.CancelledError:
                pass

        if self._thread:
            # join with timeout; thread is daemon so process exit cleans it up
            await self._loop.run_in_executor(
                None, lambda: self._thread.join(timeout=5.0)
            )

        self._cleanup_tmpfs()

    # ── Capture thread ────────────────────────────────────────────────────────

    @staticmethod
    def _is_file_source(url: str) -> bool:
        """Return True if url is a local file path rather than a network stream.

        cv2.VideoCapture accepts both file paths and network URLs. For files,
        EOF (cap.read() → False) means the video finished normally and should
        loop immediately. For network streams, False means a connection failure
        that warrants backoff and a warning.
        """
        return not url.startswith(("rtsp://", "rtsps://", "rtmp://", "http://", "https://"))

    def _open_cap(self) -> cv2.VideoCapture:
        cap = cv2.VideoCapture(self._config.rtsp_url)
        if not self._is_file_source(self._config.rtsp_url):
            # Network stream timeouts only apply to RTSP/RTMP — not file paths.
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
            cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)
        return cap

    def _enqueue_frame(self, frame) -> None:
        """Hand a captured frame to the asyncio queue from the capture thread."""
        item = (now_ms(), frame)

        # put_nowait must run on the event-loop thread; schedule it there.
        def _enqueue(q=self._frame_queue, it=item):
            try:
                q.put_nowait(it)
            except asyncio.QueueFull:
                self._frames_dropped += 1
                if self._frames_dropped % 100 == 0:
                    logger.warning(
                        "camera=%s dropped %d frames (queue full)",
                        self._config.camera_id, self._frames_dropped,
                    )

        self._loop.call_soon_threadsafe(_enqueue)

    def _capture_loop(self) -> None:
        is_file = self._is_file_source(self._config.rtsp_url)
        cap = self._open_cap()
        consecutive_failures = 0
        target_fps = self._config.target_fps if self._config.target_fps > 0 else 5.0

        # ── File sampling: keep ~target_fps frames per second of real-time video ──
        # A file decodes far faster than real-time, so we (a) skip frames using a
        # stride derived from the video's native FPS, and (b) pace at native FPS so
        # the window spans real footage time. Result: target_fps sampling across
        # the actual video, not the first N consecutive frames.
        native_fps = cap.get(cv2.CAP_PROP_FPS) if is_file else 0.0
        if not (1.0 <= native_fps <= 240.0):
            native_fps = target_fps                      # unknown/invalid → no skip
        stride = max(1, round(native_fps / target_fps)) if is_file else 1
        frame_period = (1.0 / native_fps) if is_file else 0.0
        if is_file:
            logger.info(
                "camera=%s file sampling: native_fps=%.1f target_fps=%.1f stride=%d",
                self._config.camera_id, native_fps, target_fps, stride,
            )
        idx = 0

        while not self._stop_event.is_set():
            if is_file:
                t0 = time.monotonic()
                if not cap.grab():
                    cap.release()
                    logger.info("camera=%s video file ended — looping from start",
                                self._config.camera_id)
                    cap = self._open_cap()
                    idx = 0
                    continue
                if idx % stride == 0:
                    ok, frame = cap.retrieve()
                    if ok:
                        self._status = "capturing"
                        self._enqueue_frame(frame)
                idx += 1
                # Pace to real-time so a window covers `window_seconds` of footage.
                dt = time.monotonic() - t0
                if frame_period > dt:
                    time.sleep(frame_period - dt)
                continue

            # ── RTSP / network source ────────────────────────────────────────────
            ret, frame = cap.read()
            if not ret:
                cap.release()
                consecutive_failures += 1
                delay = min(2.0 * (2 ** consecutive_failures), 60.0)
                self._status = "reconnecting"
                logger.warning(
                    "camera=%s RTSP read failed, reconnect in %.1fs (attempt %d)",
                    self._config.camera_id, delay, consecutive_failures,
                )
                time.sleep(delay)
                cap = self._open_cap()
                continue
            consecutive_failures = 0
            self._status = "capturing"
            self._enqueue_frame(frame)

        cap.release()
        logger.info("camera=%s capture thread exiting", self._config.camera_id)

    # ── Async window loop ─────────────────────────────────────────────────────

    def _make_accumulator(self) -> WindowAccumulator:
        return WindowAccumulator(
            sample_fps=self._config.target_fps,
            batch_window_seconds=self._config.window_seconds,
            batch_frames=self._config.batch_frames,
        )

    async def _flush_accumulator(
        self,
        accumulator: WindowAccumulator,
        window_start: int,
        window_end: int,
    ) -> None:
        manifest = accumulator.close(window_start, window_end, self._batch_number)
        await self._publish_manifest(manifest)
        self._batch_number += 1

    async def _window_loop(self) -> None:
        window_seconds_ms = int(self._config.window_seconds * 1000) + 3500
        accumulator  = self._make_accumulator()
        window_start = now_ms()

        try:
            while True:
                try:
                    ts, frame = await asyncio.wait_for(
                        self._frame_queue.get(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    pass
                else:
                    self._last_frame_ts = ts
                    path = _write_to_tmpfs(self._config.camera_id, ts, frame)
                    if path is not None:
                        batch_full = accumulator.add(ts, path)
                        if batch_full:
                            # Frame-count trigger: flush immediately.
                            window_end   = ts
                            await self._flush_accumulator(accumulator, window_start, window_end)
                            window_start = window_end
                            accumulator  = self._make_accumulator()
                            continue

                # Safety-flush: emit whatever has accumulated if the time budget
                # expires — prevents frames from being held indefinitely when the
                # source delivers fewer than batch_frames in window_seconds.
                if now_ms() - window_start >= window_seconds_ms:
                    window_end = window_start + window_seconds_ms
                    await self._flush_accumulator(accumulator, window_start, window_end)
                    window_start += window_seconds_ms  # fixed advance, no drift
                    accumulator   = self._make_accumulator()

        except asyncio.CancelledError:
            # publish partial window before exiting (R8)
            if accumulator._frames:
                window_end = now_ms()
                manifest = accumulator.close(window_start, window_end, self._batch_number)
                manifest_dict = self._manifest_to_dict(manifest)
                manifest_dict["status"] = "partial"
                await self._xadd(manifest_dict)
            raise

    async def _publish_manifest(self, manifest) -> None:
        payload = self._manifest_to_dict(manifest)
        for attempt in range(3):
            try:
                await self._xadd(payload)
                return
            except Exception as exc:
                logger.warning(
                    "camera=%s XADD failed attempt=%d err=%s",
                    self._config.camera_id, attempt + 1, exc,
                )
                await asyncio.sleep(0.5 * (2 ** attempt))
        raise RuntimeError(
            f"camera={self._config.camera_id}: failed to publish manifest after 3 attempts"
        )

    async def _xadd(self, payload: dict) -> None:
        await self._redis.xadd(
            f"{STREAM_PREFIX}:{self._config.camera_id}",
            {"manifest": json.dumps(payload)},
            maxlen=STREAM_MAXLEN,
            approximate=True,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _manifest_to_dict(manifest) -> dict:
        import dataclasses
        d = dataclasses.asdict(manifest)
        # gaps are Gap dataclass objects; asdict already handles them
        return d

    def _cleanup_tmpfs(self) -> None:
        path = f"{TMPFS_ROOT}/{self._config.camera_id}"
        if os.path.exists(path):
            shutil.rmtree(path, ignore_errors=True)
            logger.info("camera=%s tmpfs cleaned up: %s", self._config.camera_id, path)
