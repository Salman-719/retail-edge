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

from services.iep1_ingestion.app.metrics import (
    IEP1_BACKPRESSURE_DROPS,
    IEP1_BACKPRESSURE_ENGAGED,
    IEP1_ENCODE_ERRORS,
    IEP1_FRAMES,
    IEP1_FRAMES_DROPPED,
    IEP1_LATE_FRAMES,
    IEP1_MEMORY_FRACTION,
    IEP1_PUBLISH_LATENCY,
    IEP1_WINDOW_FLUSH_LAG,
)
from services.iep1_ingestion.app.window import WindowAccumulator

logger = logging.getLogger(__name__)

TMPFS_ROOT       = os.environ.get("TMPFS_FRAME_ROOT", "/dev/shm/frames")
JPEG_QUALITY     = int(os.environ.get("JPEG_QUALITY", "85"))
FRAME_QUEUE_SIZE = int(os.environ.get("FRAME_QUEUE_SIZE", "30"))
STREAM_PREFIX    = "stream:iep1"
STREAM_MAXLEN    = 1000

# How long past a window's wall-clock end we keep accepting frames for it, to
# cover capture→enqueue latency. Must exceed that latency or trailing frames get
# counted as late; must stay well under one window or flushes bunch up.
WINDOW_GRACE_MS  = int(os.environ.get("IEP1_WINDOW_GRACE_MS", "1000"))

# ── Memory backpressure ───────────────────────────────────────────────────────
# Frames written to /dev/shm are charged to IEP1's cgroup memory; if IEP2 stalls
# they pile up and OOM-kill IEP1 (observed: one health flap → 26-restart crash
# loop → total pipeline death). This sheds frames *before* the OOM: when cgroup
# memory crosses the high mark we drop frames (windows degrade gracefully), and
# resume at the low mark. Hysteresis avoids flapping. cgroup v2 first, v1 fallback.
BACKPRESSURE_HIGH     = float(os.environ.get("IEP1_BACKPRESSURE_HIGH", "0.85"))
BACKPRESSURE_LOW      = float(os.environ.get("IEP1_BACKPRESSURE_LOW", "0.60"))
BACKPRESSURE_INTERVAL = float(os.environ.get("IEP1_BACKPRESSURE_INTERVAL_S", "1.0"))


def now_ms() -> int:
    return int(time.time() * 1000)


def _read_cgroup_mem_fraction() -> float:
    """IEP1 container memory usage / limit in [0,1], or 0.0 if unknown/unlimited."""
    try:  # cgroup v2
        with open("/sys/fs/cgroup/memory.max") as fh:
            raw = fh.read().strip()
        if raw != "max":
            limit = int(raw)
            with open("/sys/fs/cgroup/memory.current") as fh:
                cur = int(fh.read().strip())
            return cur / limit if limit > 0 else 0.0
    except (OSError, ValueError):
        pass
    try:  # cgroup v1
        with open("/sys/fs/cgroup/memory/memory.limit_in_bytes") as fh:
            limit = int(fh.read().strip())
        with open("/sys/fs/cgroup/memory/memory.usage_in_bytes") as fh:
            cur = int(fh.read().strip())
        if 0 < limit < (1 << 62):  # v1 uses a huge sentinel when unlimited
            return cur / limit
    except (OSError, ValueError):
        pass
    return 0.0


class MemoryBackpressure:
    """Process-wide memory backpressure with hysteresis (all camera workers share
    IEP1's cgroup). should_drop() is cheap — it re-samples at most every
    BACKPRESSURE_INTERVAL seconds and returns the cached engaged state otherwise."""

    def __init__(self) -> None:
        self._engaged = False
        self._last_check = 0.0

    def should_drop(self) -> bool:
        now = time.monotonic()
        if now - self._last_check >= BACKPRESSURE_INTERVAL:
            self._last_check = now
            frac = _read_cgroup_mem_fraction()
            IEP1_MEMORY_FRACTION.set(frac)
            if self._engaged and frac <= BACKPRESSURE_LOW:
                self._engaged = False
                IEP1_BACKPRESSURE_ENGAGED.set(0)
                logger.warning("IEP1 backpressure RELEASED — memory=%.0f%%", frac * 100)
            elif not self._engaged and frac >= BACKPRESSURE_HIGH:
                self._engaged = True
                IEP1_BACKPRESSURE_ENGAGED.set(1)
                logger.warning(
                    "IEP1 backpressure ENGAGED — memory=%.0f%% — shedding frames "
                    "(IEP2 behind); windows will degrade", frac * 100,
                )
        return self._engaged


# One shared monitor for the whole IEP1 process (cgroup memory is process-wide).
_BACKPRESSURE = MemoryBackpressure()


def _write_to_tmpfs(camera_id: str, ts_ms: int, frame) -> str | None:
    success, buf = cv2.imencode(
        ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
    )
    if not success or buf is None:
        IEP1_ENCODE_ERRORS.labels(camera_id=camera_id).inc()
        logger.warning("Frame encode failed camera=%s ts=%d", camera_id, ts_ms)
        IEP1_ENCODE_ERRORS.labels(camera_id=camera_id).inc()
        return None
    path = f"{TMPFS_ROOT}/{camera_id}/{ts_ms}.jpg"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "wb") as fh:
            fh.write(buf.tobytes())
    except OSError as exc:
        # tmpfs full (ENOSPC) or other write failure — drop the frame, never crash
        # the window loop (a crash here is what froze the whole pipeline before).
        IEP1_ENCODE_ERRORS.labels(camera_id=camera_id).inc()
        logger.warning("tmpfs write failed camera=%s ts=%d: %s", camera_id, ts_ms, exc)
        return None
    IEP1_FRAMES.labels(camera_id=camera_id).inc()
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
        self._frame_queue = asyncio.Queue(maxsize=FRAME_QUEUE_SIZE)
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
        def _enqueue(q=self._frame_queue, it=item, cam=self._config.camera_id):
            try:
                q.put_nowait(it)
                IEP1_FRAMES.labels(camera_id=self._config.camera_id).inc()
            except asyncio.QueueFull:
                self._frames_dropped += 1
                IEP1_FRAMES_DROPPED.labels(camera_id=cam).inc()
                if self._frames_dropped % 100 == 0:
                    logger.warning(
                        "camera=%s dropped %d frames (queue full)",
                        cam, self._frames_dropped,
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
                    logger.debug("camera=%s video file ended — looping from start",
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
            # The proto default (0) — also produced by stale stubs — must be treated
            # as "unset" so expected_frames falls back to window_seconds*sample_fps;
            # otherwise expected_frames=0 marks every window "offline" and IEP2 skips it.
            batch_frames=(self._config.batch_frames or None),
        )

    async def _flush_accumulator(
        self,
        accumulator: WindowAccumulator,
        window_start: int,
        window_end: int,
    ) -> None:
        manifest = accumulator.close(window_start, window_end, self._batch_number)
        # Never let a publish failure kill the window loop: the capture thread keeps
        # running and the queue would fill forever ("dropped frames"). Drop the
        # window, log, and keep going — IEP1 self-heals when redis recovers.
        try:
            await self._publish_manifest(manifest)
        except Exception as exc:
            logger.warning(
                "camera=%s dropping window after publish failure: %s",
                self._config.camera_id, exc,
            )
        self._batch_number += 1

    async def _window_loop(self) -> None:
        """Emit one manifest per wall-clock window, on a fixed epoch-aligned grid.

        ADR-003 requires every camera to share identical window boundaries
        "defined by wall clock, aligned to the minute … not relative timers", so
        IEP3 can group cameras by rounded window_start. Boundaries here are
        therefore derived only from the clock: floor(now / W) * W, advancing by
        exactly W. They are never re-anchored to a frame timestamp — doing that
        made each window last (frames / actual_fps) instead of W, so every camera
        slid off the grid at its own rate and pairs of cameras periodically fell
        into different IEP3 buckets, losing all cross-camera identity merging for
        those windows with no error raised.
        """
        W = int(self._config.window_seconds * 1000)
        accumulator  = self._make_accumulator()
        window_start = (now_ms() // W) * W
        window_end   = window_start + W

        async def _close_window() -> None:
            """Emit the current window and step to the next grid slot."""
            nonlocal accumulator, window_start, window_end
            IEP1_WINDOW_FLUSH_LAG.labels(camera_id=self._config.camera_id).observe(
                max(0, now_ms() - window_end) / 1000.0
            )
            await self._flush_accumulator(accumulator, window_start, window_end)
            window_start = window_end
            window_end   = window_start + W
            accumulator  = self._make_accumulator()

        try:
            while True:
                ts = frame = None
                try:
                    ts, frame = await asyncio.wait_for(
                        self._frame_queue.get(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    pass

                # Close every window whose deadline has passed, even with no
                # frames arriving — a dead source still produces "offline"
                # windows on the grid instead of leaving a hole in the timeline.
                while now_ms() >= window_end + WINDOW_GRACE_MS:
                    await _close_window()

                if ts is not None:
                    self._last_frame_ts = ts
                    # Frame belongs to a later slot: close windows until it fits.
                    while ts >= window_end:
                        await _close_window()
                    # Frame belongs to a window already published. Dropped, not
                    # back-dated: IEP3 matches co-visibility within 150 ms, so a
                    # frame filed under the wrong window corrupts that matching.
                    if ts < window_start:
                        IEP1_LATE_FRAMES.labels(camera_id=self._config.camera_id).inc()
                        continue
                    if _BACKPRESSURE.should_drop():
                        # IEP2 is behind and IEP1 memory is high — shed this frame
                        # instead of writing it. The window ends up with fewer
                        # frames and flushes as "degraded" (IEP2 still processes
                        # it); this converts the old "IEP2 stall → IEP1 OOM → total
                        # death" into graceful degradation that self-recovers.
                        IEP1_BACKPRESSURE_DROPS.labels(camera_id=self._config.camera_id).inc()
                    else:
                        path = _write_to_tmpfs(self._config.camera_id, ts, frame)
                        if path is not None:
                            accumulator.add(ts, path)

        except asyncio.CancelledError:
            # publish partial window before exiting (R8). Ends at "now" rather
            # than the grid boundary, so close() prorates expected_frames and the
            # short window is not mislabelled offline.
            if accumulator._frames:
                manifest = accumulator.close(window_start, min(now_ms(), window_end), self._batch_number)
                manifest_dict = self._manifest_to_dict(manifest)
                manifest_dict["status"] = "partial"
                await self._xadd(manifest_dict)
            raise

    async def _publish_manifest(self, manifest) -> None:
        payload = self._manifest_to_dict(manifest)
        for attempt in range(3):
            try:
                t0 = time.monotonic()
                await self._xadd(payload)
                IEP1_PUBLISH_LATENCY.observe(time.monotonic() - t0)
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
