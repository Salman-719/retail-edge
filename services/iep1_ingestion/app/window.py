from dataclasses import dataclass, field
from typing import List, Tuple

ONLINE_FRAME_RATIO  = 0.8
OFFLINE_FRAME_RATIO = 0.2
GAP_MULTIPLIER      = 1.5


@dataclass
class Gap:
    start_ts_ms: int
    end_ts_ms:   int

    @property
    def duration_ms(self) -> int:
        return self.end_ts_ms - self.start_ts_ms


@dataclass
class WindowManifest:
    window_start_ms:  int
    window_end_ms:    int
    batch_number:     int
    status:           str
    frames:           List[Tuple[int, str]]
    gaps:             List[Gap]
    frame_count:      int
    expected_frames:  int


class WindowAccumulator:
    """Collects frames for ONE window and renders the manifest.

    Deliberately knows nothing about when a window starts or ends: boundaries are
    wall-clock aligned and owned by the caller (ADR-003 — "governed by wall clock,
    not relative timers"). `batch_frames` is a SIZING hint only; it must never
    trigger a flush. Letting it close the window re-anchored `window_start` to a
    frame timestamp, so every camera drifted off the shared grid at its own rate
    and cameras silently stopped landing in the same IEP3 reconciliation bucket.
    """

    def __init__(
        self,
        sample_fps: float,
        batch_window_seconds: float,
        batch_frames: int | None = None,
    ) -> None:
        self.sample_fps = sample_fps
        self.batch_window_seconds = batch_window_seconds
        # Expected frame count for a FULL window, used only for the status ratio.
        self.batch_frames = batch_frames
        self._sample_interval_ms: float = 1000.0 / sample_fps
        self._expected_frames: int = batch_frames if batch_frames is not None else round(batch_window_seconds * sample_fps)
        self._frames: List[Tuple[int, str]] = []
        self._gaps: List[Gap] = []

    def add(self, capture_ts_ms: int, s3_key: str) -> None:
        """Add a frame to the current window.

        Returns nothing: the window closes on the wall clock, never on frame
        count. (This used to return True at `batch_frames` to signal a flush.)
        """
        if self._frames:
            prev_ts = self._frames[-1][0]
            elapsed = capture_ts_ms - prev_ts
            # Decimate to sample_fps: drop frames arriving faster than the sample
            # interval. Makes target_fps authoritative for any source — a high-FPS
            # RTSP stream or a fast file read is sampled down to ~sample_fps rather
            # than flooding the window. The 0.9 factor tolerates capture jitter
            # without systematically under-sampling.
            if elapsed < self._sample_interval_ms * 0.9:
                return
            if elapsed > GAP_MULTIPLIER * self._sample_interval_ms:
                self._gaps.append(Gap(start_ts_ms=prev_ts, end_ts_ms=capture_ts_ms))
        self._frames.append((capture_ts_ms, s3_key))

    def expected_for_span(self, span_ms: int) -> int:
        """Frames expected for a window covering `span_ms`.

        A window shorter than nominal — the first one after a camera starts
        mid-grid, or the final partial one at shutdown — is prorated. Without
        this every camera start would emit a spurious "offline" window (a short
        window can never reach 80% of a full window's frame count), and IEP2
        skips offline windows outright.
        """
        nominal_ms = int(self.batch_window_seconds * 1000)
        if nominal_ms <= 0 or span_ms >= nominal_ms or span_ms <= 0:
            return self._expected_frames
        return max(1, round(self._expected_frames * span_ms / nominal_ms))

    def close(self, window_start_ms: int, window_end_ms: int, batch_number: int) -> WindowManifest:
        frame_count = len(self._frames)
        expected = self.expected_for_span(window_end_ms - window_start_ms)
        ratio = frame_count / expected if expected > 0 else 0.0

        if ratio >= ONLINE_FRAME_RATIO:
            status = "online"
        elif ratio <= OFFLINE_FRAME_RATIO:
            status = "offline"
        else:
            status = "degraded"

        return WindowManifest(
            window_start_ms=window_start_ms,
            window_end_ms=window_end_ms,
            batch_number=batch_number,
            status=status,
            frames=list(self._frames),
            gaps=list(self._gaps),
            frame_count=frame_count,
            expected_frames=expected,
        )

    def reset(self) -> None:
        self._frames.clear()
        self._gaps.clear()


if __name__ == "__main__":
    SAMPLE_FPS = 5.0
    WINDOW_SEC = 10.0
    INTERVAL_MS = int(1000.0 / SAMPLE_FPS)

    acc = WindowAccumulator(sample_fps=SAMPLE_FPS, batch_window_seconds=WINDOW_SEC)

    base_ts = 1_000_000_000_000

    # 10 frames at correct interval — no gaps
    for i in range(10):
        acc.add(base_ts + i * INTERVAL_MS, f"frames/cam/{ base_ts + i * INTERVAL_MS }.jpg")

    # 2 deliberate gaps: jump by 5x the interval each time
    gap_ts = base_ts + 10 * INTERVAL_MS
    acc.add(gap_ts + 5 * INTERVAL_MS, f"frames/cam/{gap_ts + 5 * INTERVAL_MS}.jpg")
    acc.add(gap_ts + 10 * INTERVAL_MS, f"frames/cam/{gap_ts + 10 * INTERVAL_MS}.jpg")

    manifest = acc.close(
        window_start_ms=base_ts,
        window_end_ms=base_ts + int(WINDOW_SEC * 1000),
        batch_number=1,
    )

    print(f"status      : {manifest.status}")
    print(f"frame_count : {manifest.frame_count}")
    print(f"expected    : {manifest.expected_frames}")
    print(f"gap_count   : {len(manifest.gaps)}")
    for g in manifest.gaps:
        print(f"  gap duration_ms={g.duration_ms}")

    # idempotency: close() twice without reset() -> same result
    manifest2 = acc.close(
        window_start_ms=base_ts,
        window_end_ms=base_ts + int(WINDOW_SEC * 1000),
        batch_number=1,
    )
    assert manifest.frame_count == manifest2.frame_count, "close() not idempotent"
    assert len(manifest.gaps) == len(manifest2.gaps), "close() not idempotent"
    print("idempotent  : OK")

    # reset then close -> offline empty manifest
    acc.reset()
    empty = acc.close(
        window_start_ms=base_ts,
        window_end_ms=base_ts + int(WINDOW_SEC * 1000),
        batch_number=2,
    )
    assert empty.status == "offline", f"expected offline, got {empty.status}"
    assert empty.frame_count == 0
    print(f"after reset : status={empty.status} frame_count={empty.frame_count} — OK")
