"""Window accumulator + gap detection -- the heart of the robustness design.

Bounds windows by capture time (not frame count), so a window with gaps simply
holds fewer keys and a window from a dead camera holds zero. On close it computes
the explicit gap list and classifies camera status. IEP1 reports gaps as raw
facts; IEP2 interprets them against ByteTrack's ``max_age``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Gap:
    start_ms: int
    end_ms: int
    missing_frames: int


@dataclass
class WindowManifest:
    camera_id: str
    store_id: str
    batch_number: int
    window_start_ms: int
    window_end_ms: int
    camera_status: str  # online | degraded | offline
    expected_frames: int
    captured_frames: int
    frame_keys: list[str] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    schema_version: int = 1


class WindowAccumulator:
    """Collects ``(capture_ts, s3_key)`` for the current window; ``close``
    computes gaps + status and returns a manifest, then resets for the next
    window."""

    def __init__(self, camera_id, store_id, window_ms, sample_fps, settings):
        self._cam, self._store = camera_id, store_id
        self._window_ms = window_ms
        self._expected = int((window_ms / 1000) * sample_fps)
        self._sample_interval_ms = 1000.0 / sample_fps
        self._gap_threshold_ms = 1.5 * self._sample_interval_ms
        self._s = settings
        self._frames: list[tuple[int, str]] = []

    def add(self, capture_ts_ms: int, s3_key: str) -> None:
        self._frames.append((capture_ts_ms, s3_key))

    @property
    def pending_count(self) -> int:
        return len(self._frames)

    def close(self, window_start_ms: int, window_end_ms: int, batch_number: int) -> WindowManifest:
        frames = sorted(self._frames, key=lambda f: f[0])
        gaps = self._detect_gaps(frames, window_start_ms, window_end_ms)
        captured = len(frames)
        manifest = WindowManifest(
            camera_id=self._cam, store_id=self._store, batch_number=batch_number,
            window_start_ms=window_start_ms, window_end_ms=window_end_ms,
            camera_status=self._classify(captured), expected_frames=self._expected,
            captured_frames=captured, frame_keys=[k for _, k in frames], gaps=gaps,
        )
        self._frames = []
        return manifest

    def _detect_gaps(self, frames, w_start, w_end) -> list[Gap]:
        gaps: list[Gap] = []
        prev = w_start
        for ts, _ in frames:
            if ts - prev > self._gap_threshold_ms:
                missing = int((ts - prev) / self._sample_interval_ms) - 1
                gaps.append(Gap(prev, ts, max(missing, 0)))
            prev = ts
        if w_end - prev > self._gap_threshold_ms:  # trailing gap (camera died mid-window / offline)
            missing = int((w_end - prev) / self._sample_interval_ms)
            gaps.append(Gap(prev, w_end, max(missing, 0)))
        return gaps

    def _classify(self, captured: int) -> str:
        ratio = captured / self._expected if self._expected else 0.0
        if ratio >= self._s.online_frame_ratio:
            return "online"
        if ratio >= self._s.offline_frame_ratio:
            return "degraded"
        return "offline"
