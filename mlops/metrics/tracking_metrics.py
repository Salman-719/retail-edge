"""Tracking metrics — pure functions + a FrameStats -> metric-dict converter.

The tracking experiment FIXES detection (rtdetr-x conf0.5) and varies the tracker,
so every run sees identical detections. That makes track-count metrics valid: any
difference is the tracker's stitching quality, not detection.

Agreed metric set (drop_to_zero intentionally excluded — no discriminating signal
on an always-occupied crowded clip):
  Tier 1 (primary):  id_switches, unique_track_ids, track_fragmentation
  Tier 2 (support):  peak_confirmed_tracks, peak_track_error, avg_track_lifetime
  Tier 3 (perf):     per_frame_assoc_ms, throughput_fps
"""
from __future__ import annotations


def track_fragmentation(unique_track_ids: int, total_people_gt: int) -> float:
    """Track IDs created per real person. 1.0 = perfect (one track per person);
    >1 = over-segmentation/churn. e.g. BoT-SORT 29 / 16 = 1.81."""
    if total_people_gt <= 0:
        raise ValueError("total_people_gt must be > 0")
    return unique_track_ids / total_people_gt


def peak_track_error(peak_confirmed_tracks: int, peak_people_gt: int) -> int:
    """|max simultaneous confirmed tracks - ground-truth peak|. 0 = the tracker
    held exactly the right number of people at the busiest moment."""
    return abs(peak_confirmed_tracks - peak_people_gt)


def avg_track_lifetime(track_frames: dict) -> float:
    """Mean number of frames a track was ACTUALLY present (count of frames it was
    seen), averaged over all tracks. Counts real presence, not the first..last span
    — so an ID reused after a long gap is not credited for the gap. Higher = more
    stable, longer-lived identities."""
    if not track_frames:
        return 0.0
    lifetimes = [len(frames) for frames in track_frames.values()]
    return sum(lifetimes) / len(lifetimes)


def programmable_metrics(stats, total_people_gt: int, peak_people_gt: int) -> dict:
    """Convert raw harness FrameStats into the tracking metric dict.

    `total_people_gt` / `peak_people_gt` come from mlops/labeling/labels.json for
    the clip (crowded: 16 people, peak 14).
    """
    tcounts = stats.per_frame_track_counts
    unique = len(stats.track_ids_seen)
    peak_tracks = max(tcounts) if tcounts else 0
    tracker_ms = (stats.tracker_time_s / stats.frames_processed * 1000.0
                  if stats.frames_processed else 0.0)
    return {
        # Tier 1 — primary
        "id_switches":           stats.id_switches,
        "unique_track_ids":      unique,
        "track_fragmentation":   track_fragmentation(unique, total_people_gt),
        # Tier 2 — supporting
        "peak_confirmed_tracks": peak_tracks,
        "peak_track_error":      peak_track_error(peak_tracks, peak_people_gt),
        "avg_track_lifetime":    avg_track_lifetime(stats.track_frames),
        # Tier 3 — performance (tracker.update() only)
        "per_frame_assoc_ms":    tracker_ms,
        "throughput_fps":        (stats.frames_processed / stats.tracker_time_s
                                  if stats.tracker_time_s else 0.0),
        # comparability
        "frames_processed":      stats.frames_processed,
    }
