from __future__ import annotations

import asyncio
from datetime import timezone
import os
from types import SimpleNamespace

from sqlalchemy import func, select, text

from common.config import get_settings
from common.db.engine import dispose_engine, session_scope
from common.models.iep2_tables import LocalCentroid
from common.models.shared_tables import CameraCalibration
from services.iep2_vision.app.calibration import load_calibration_from_eep
from services.iep2_vision.app.event_bus import KafkaJsonConsumer
from services.iep2_vision.app.ingest.frame_resolver import FrameResolver
from services.iep2_vision.app.runtime import Iep2Runtime
from services.iep2_vision.app.vision_events import FrameRefEvent

FRAME_REF_TOPIC = "vision.frame_ref.v1"


def _source_ts_ms(event: FrameRefEvent) -> int:
    value = event.source_ts
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1000)


def _identity_calibration(camera_id: str):
    return SimpleNamespace(
        cam_id=camera_id,
        homography=[1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
        zone_polygons={"zones": []},
    )


async def _load_calibration(event: FrameRefEvent):
    camera_id = str(event.camera_id)
    async with session_scope() as session:
        demo = (
            await session.execute(select(CameraCalibration).where(CameraCalibration.cam_id == camera_id))
        ).scalar_one_or_none()
        if demo is not None:
            return demo

        row = (
            await session.execute(
                text(
                    """
                    SELECT c.homography_matrix, cc.section_id
                    FROM calibrations c
                    JOIN camera_configs cc ON cc.id = c.camera_config_id
                    WHERE c.camera_config_id = :camera_config_id
                      AND c.is_current = TRUE
                      AND c.status IN ('complete', 'verified')
                    ORDER BY c.created_at DESC
                    LIMIT 1
                    """
                ),
                {"camera_config_id": str(event.camera_config_id)},
            )
        ).first()
        if row is None or row.homography_matrix is None:
            return _identity_calibration(camera_id)

        zones = (
            await session.execute(
                text(
                    """
                    SELECT id::text AS id, name, points
                    FROM zones
                    WHERE version_id = :version_id AND section_id = :section_id
                    """
                ),
                {"version_id": str(event.version_id), "section_id": str(row.section_id)},
            )
        ).mappings().all()

    h, zone_rows, bounds = load_calibration_from_eep(
        row.homography_matrix,
        [dict(z) for z in zones],
        camera_id,
    )
    return SimpleNamespace(cam_id=camera_id, homography=h.reshape(-1).tolist(), zone_polygons={"zones": zone_rows}, bounds=bounds)


async def _latest_batch_number(camera_id: str) -> int:
    async with session_scope() as session:
        value = (
            await session.execute(
                select(func.max(LocalCentroid.updated_at_batch)).where(LocalCentroid.camera_id == camera_id)
            )
        ).scalar_one_or_none()
    return int(value) if value is not None else -1


class CameraStreamProcessor:
    def __init__(self, event: FrameRefEvent):
        self.store_id = event.store_id
        self.camera_id = str(event.camera_id)
        self.settings = get_settings()
        self.runtime = Iep2Runtime(event.store_id, self.camera_id, self.settings)
        self.batch_number = 0
        self.window_start_ms: int | None = None
        self.frames_in_window = 0
        self.window_ms = int(self.settings.batch_window_seconds * 1000)
        self.ready = False

    async def setup(self, event: FrameRefEvent) -> None:
        self.batch_number = await _latest_batch_number(self.camera_id) + 1
        await self.runtime.setup(await _load_calibration(event), current_batch=self.batch_number)
        self.ready = True

    async def process(self, frame, event: FrameRefEvent) -> None:
        if not self.ready:
            await self.setup(event)
        ts_ms = _source_ts_ms(event)
        if self.window_start_ms is None:
            self.window_start_ms = ts_ms
        empty_windows_skipped = 0
        while self.window_start_ms is not None and ts_ms >= self.window_start_ms + self.window_ms:
            if self.frames_in_window > 0:
                await self.runtime.flush_batch(
                    self.batch_number,
                    self.window_start_ms,
                    self.window_start_ms + self.window_ms,
                )
                self.batch_number += 1
                self.frames_in_window = 0
            else:
                empty_windows_skipped += 1
            self.window_start_ms += self.window_ms
        if empty_windows_skipped > 0:
            self.runtime.reset_tracker()
        await self.runtime.process_sampled_frame(frame, ts_ms)
        self.frames_in_window += 1

    async def flush(self) -> None:
        if self.window_start_ms is not None and self.frames_in_window > 0:
            await self.runtime.flush_batch(
                self.batch_number,
                self.window_start_ms,
                self.window_start_ms + self.window_ms,
            )
            self.batch_number += 1
            self.frames_in_window = 0


class DetectorWorker:
    def __init__(self) -> None:
        self.consumer = KafkaJsonConsumer(
            os.getenv("VISION_FRAME_REF_TOPIC", FRAME_REF_TOPIC),
            os.getenv("IEP2_DETECTOR_GROUP_ID", "iaip2-detector-workers"),
        )
        self.resolver = FrameResolver()
        self.processors: dict[str, CameraStreamProcessor] = {}

    async def run(self) -> None:
        await self.consumer.start()
        try:
            async for raw in self.consumer.messages():
                await self.process_event(FrameRefEvent.model_validate(raw))
        finally:
            for processor in self.processors.values():
                await processor.flush()
            self.resolver.close()
            await self.consumer.stop()
            await dispose_engine()

    async def process_event(self, event: FrameRefEvent) -> None:
        camera_id = str(event.camera_id)
        processor = self.processors.get(camera_id)
        if processor is None:
            processor = CameraStreamProcessor(event)
            self.processors[camera_id] = processor
        frame = self.resolver.read(event)
        await processor.process(frame, event)


async def main() -> None:
    await DetectorWorker().run()


if __name__ == "__main__":
    asyncio.run(main())
