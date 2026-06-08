"""Camera → zone coverage population.

Computes, for every camera_config in a config version, which floor zones the
camera observes, and writes the result to `camera_zone_coverage`. IEP3 reads
that table to build its cross-camera overlap graph (Stage 0 of the matcher) —
only cameras that share a covered zone are ever compared.

Called at version activation (and reactivation), the point at which a version's
zones and calibrations are final and it becomes the version IEP3 reads. Pure
geometry lives in app.utils.camera_coverage; this module is the DB glue only.
"""
from __future__ import annotations

import json
import logging

import numpy as np
from shapely.geometry import Polygon
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.utils.camera_coverage import (
    CameraCalibration,
    camera_floor_footprint,
    frame_bounds_from_correspondences,
    zone_coverages,
)

logger = logging.getLogger(__name__)

# Fallback camera frame resolution when no DB source is available yet. At version
# activation time physical_cameras.stream_width is not written until IEP2 has run,
# and homography calibrations do not record image dimensions — so without a
# fallback no coverage could ever be computed before the pipeline first runs. The
# overlap graph is only a coarse pre-filter (runtime spatial voting does the real
# matching), so an approximate footprint is acceptable; it self-corrects to the
# exact resolution once IEP2 records stream_width/height and coverage is recomputed.
DEFAULT_FRAME_WIDTH  = 1920
DEFAULT_FRAME_HEIGHT = 1080


def _parse_json(raw):
    """JSONB columns come back as str (asyncpg) or already-parsed — normalise."""
    if raw is None:
        return None
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


def _build_calibration(row, ppm, origin_x, origin_y) -> CameraCalibration | None:
    """Construct a CameraCalibration from a current `calibrations` row, or None.

    None means the camera has no usable current calibration and therefore no
    coverage can be computed (it will simply have no overlap-graph edges).
    """
    method = row["method"]
    if method == "homography":
        H = _parse_json(row["homography_matrix"])
        if H is None:
            return None
        # ppm/origin needed to convert the homography's floor-plan-pixel output
        # to world metres (the space of zones / tracking floor positions).
        return CameraCalibration(
            "homography",
            homography=np.array(H, dtype=np.float64).reshape(3, 3),
            ppm=ppm, origin_x=origin_x, origin_y=origin_y,
        )

    if method == "pnp":
        K = _parse_json(row["intrinsic_matrix"])
        rvec = _parse_json(row["rotation_vector"])
        tvec = _parse_json(row["translation_vector"])
        if K is None or rvec is None or tvec is None:
            return None
        dist = _parse_json(row["dist_coeffs"])
        return CameraCalibration(
            "pnp",
            camera_matrix=np.array(K, dtype=np.float64).reshape(3, 3),
            dist_coeffs=np.array(dist, dtype=np.float64).reshape(-1, 1) if dist is not None else np.zeros((5, 1)),
            rotation_vector=np.array(rvec, dtype=np.float64),
            translation_vector=np.array(tvec, dtype=np.float64),
            ppm=ppm, origin_x=origin_x, origin_y=origin_y,
        )

    if method == "tps":
        corr = _parse_json(row["correspondences"])
        if not corr or len(corr) < 4:
            return None
        return CameraCalibration(
            "tps", correspondences=corr, ppm=ppm, origin_x=origin_x, origin_y=origin_y,
        )

    # 'calibration_files' or unsupported method — no projection available.
    return None


async def populate_camera_zone_coverage(version_id: str) -> int:
    """Recompute camera_zone_coverage for one config version.

    Idempotent: replaces every coverage row for the version's camera_configs.
    Returns the number of coverage rows written. Never raises on a single
    camera's geometry failure — that camera is logged and skipped so activation
    is not blocked.
    """
    async with AsyncSessionLocal() as db:
        # ── Floor-plan scale + boundary (shared by all cameras in the version) ──
        fp_row = (await db.execute(
            text("""
                SELECT origin_x, origin_y, pixels_per_meter,
                       boundary_polygon, width_px, height_px
                FROM floor_plans
                WHERE version_id = :v
                LIMIT 1
            """),
            {"v": version_id},
        )).mappings().first()

        if fp_row is None:
            logger.info("Coverage: no floor plan for version %s — skipping", version_id)
            return 0

        ppm = fp_row["pixels_per_meter"]
        origin_x = fp_row["origin_x"]
        origin_y = fp_row["origin_y"]

        # All geometry is in WORLD METRES (the space of zones.points and
        # tracking_history.floor_x/y). boundary_polygon is already stored in
        # metres; the floor-plan image rectangle fallback is in pixels and is
        # converted to metres via (px - origin) / ppm.
        boundary = None
        bpoly = _parse_json(fp_row["boundary_polygon"])
        if bpoly:
            boundary = Polygon(bpoly)
        elif (fp_row["width_px"] and fp_row["height_px"]
              and ppm and ppm > 0 and origin_x is not None and origin_y is not None):
            w, h = fp_row["width_px"], fp_row["height_px"]
            boundary = Polygon([
                ((px - origin_x) / ppm, (py - origin_y) / ppm)
                for px, py in [(0, 0), (w, 0), (w, h), (0, h)]
            ])

        # ── Zones (floor-plan pixel space) ─────────────────────────────────────
        zone_rows = (await db.execute(
            text("SELECT id, points FROM zones WHERE version_id = :v"),
            {"v": version_id},
        )).mappings().all()

        zones: list[tuple[object, Polygon]] = []
        for zr in zone_rows:
            pts = _parse_json(zr["points"])
            if pts and len(pts) >= 3:
                zones.append((zr["id"], Polygon(pts)))

        if not zones:
            logger.info("Coverage: no zones for version %s — clearing coverage", version_id)

        # ── Per-camera calibration + frame dimensions ──────────────────────────
        cam_rows = (await db.execute(
            text("""
                SELECT cc.id AS camera_config_id,
                       pc.stream_width, pc.stream_height,
                       cc.video_width, cc.video_height,
                       cal.method, cal.homography_matrix, cal.intrinsic_matrix,
                       cal.dist_coeffs, cal.rotation_vector, cal.translation_vector,
                       cal.correspondences, cal.image_width, cal.image_height
                FROM camera_configs cc
                JOIN physical_cameras pc ON pc.id = cc.physical_camera_id
                LEFT JOIN calibrations cal
                       ON cal.camera_config_id = cc.id
                      AND cal.is_current = TRUE
                      AND cal.status IN ('ok', 'verified')
                WHERE cc.version_id = :v
            """),
            {"v": version_id},
        )).mappings().all()

        # The reads above auto-began a transaction on this AsyncSession, so we
        # accumulate all changes and commit once at the end (one atomic recompute)
        # rather than opening a second transaction with db.begin().
        total_written = 0
        for row in cam_rows:
            config_id = row["camera_config_id"]

            # Replace this camera's prior coverage.
            await db.execute(
                text("DELETE FROM camera_zone_coverage WHERE camera_config_id = :c"),
                {"c": config_id},
            )

            if not zones or row["method"] is None:
                continue

            # Prefer the calibration's own control-point frame range — it removes
            # any dependency on the camera's true resolution and avoids
            # extrapolating the homography/TPS far beyond where it was fit. Only
            # fall back to DB frame dimensions (then a default) if the calibration
            # carries no usable frame correspondences.
            sample_region = frame_bounds_from_correspondences(_parse_json(row["correspondences"]))
            frame_w = frame_h = 0
            if sample_region is None:
                frame_w = row["stream_width"] or row["video_width"] or row["image_width"]
                frame_h = row["stream_height"] or row["video_height"] or row["image_height"]
                if not frame_w or not frame_h:
                    frame_w = frame_w or DEFAULT_FRAME_WIDTH
                    frame_h = frame_h or DEFAULT_FRAME_HEIGHT
                    logger.warning(
                        "Coverage: no calibration correspondences or DB frame dimensions for "
                        "camera_config %s — using default %dx%d.", config_id, frame_w, frame_h,
                    )

            try:
                calib = _build_calibration(row, ppm, origin_x, origin_y)
                if calib is None:
                    continue
                footprint = camera_floor_footprint(
                    calib, int(frame_w), int(frame_h), boundary, sample_region=sample_region
                )
                covs = zone_coverages(footprint, zones)
            except Exception:
                logger.exception(
                    "Coverage: geometry failed for camera_config %s — skipping", config_id
                )
                continue

            for zone_id, pct in covs:
                await db.execute(
                    text("""
                        INSERT INTO camera_zone_coverage
                            (camera_config_id, zone_id, coverage_percent)
                        VALUES (:c, :z, :p)
                        ON CONFLICT (camera_config_id, zone_id)
                        DO UPDATE SET coverage_percent = EXCLUDED.coverage_percent,
                                      computed_at      = NOW()
                    """),
                    {"c": config_id, "z": zone_id, "p": pct},
                )
                total_written += 1

        await db.commit()

    logger.info(
        "Coverage: wrote %d camera_zone_coverage rows for version %s (%d cameras, %d zones)",
        total_written, version_id, len(cam_rows), len(zones),
    )
    return total_written
