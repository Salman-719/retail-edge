"""LocalIdentityManager: turns ephemeral tracker Track IDs into stable per-camera
Local IDs (IEP2 spec §8).

Consumes M2's ``FrameDetection`` list + ``TrackerOutput`` for one frame, drives
the three pools, calls the embedder, and emits persistence intents through the
``PersistencePort``. Per-frame order is lost -> new -> confirmed -> pending so
lost tracks are available as ReID candidates before new tracks resolve.

Timestamp wiring: M2's ``FrameDetection`` carries no time, so the per-frame
epoch-ms ``timestamp_ms`` is passed explicitly to ``process_frame`` (M4 supplies
``SampledFrame.timestamp_ms``; M3 tests inject it). This replaces the spec's
``det....`` placeholders without mutating the M2 contract.
"""

from __future__ import annotations

import uuid

from common.config import Settings
from services.iep2_vision.app.identity.gallery import EmbeddingGallery
from services.iep2_vision.app.identity.pools import (
    ActiveTrack,
    IdentityPools,
    LostEntry,
    PendingTrack,
    TempPosition,
)
from services.iep2_vision.app.identity.resolution import resolve
from services.iep2_vision.app.persistence.ports import PersistencePort


class LocalIdentityManager:
    def __init__(self, camera_id: str, embedder, persistence: PersistencePort, settings: Settings):
        self._cam = camera_id
        self._embed = embedder
        self._db = persistence
        self._s = settings
        self.pools = IdentityPools()
        self._batch_number = 0

    # ---- per-frame entry point ----

    async def process_frame(self, frame, frame_dets, tracker_out, timestamp_ms: int) -> None:
        by_track = {d.track_id: d for d in frame_dets}

        # 1. lost tracks first (so they are available as ReID candidates)
        for tid in tracker_out.lost_track_ids:
            self._on_lost(tid)

        # 2. new tracks: begin Local ID assignment
        for t in tracker_out.new:
            det = by_track.get(t.track_id)
            if det is None or det.floor_pos is None:
                continue
            await self._on_new_track(frame, t.track_id, det, timestamp_ms)

        # 3. confirmed tracks: update + sample embeddings
        for t in tracker_out.confirmed:
            det = by_track.get(t.track_id)
            if det is None:
                continue
            await self._on_confirmed(frame, t.track_id, det, timestamp_ms)

        # 4. pending tracks still alive: collect init embeddings
        for tid, pending in list(self.pools.pending.items()):
            det = by_track.get(tid)
            if det is None or det.floor_pos is None:
                continue
            await self._on_pending(frame, pending, det, timestamp_ms)

    # ---- lifecycle handlers ----

    def _on_lost(self, track_id: int) -> None:
        at = self.pools.active.pop(track_id, None)
        if at is None:
            return  # was pending or unknown; nothing to lose
        self.pools.lost[at.local_id] = LostEntry(
            local_id=at.local_id,
            camera_id=self._cam,
            last_floor_x=at.floor_x,
            last_floor_y=at.floor_y,
            last_seen_ts=at.last_seen_ts,
            expiry_batch=self._batch_number + self._s.lost_pool_ttl_batches,
            centroid=at.gallery.snapshot_centroid(),
            gallery=list(at.gallery.embeddings),
        )

    async def _on_new_track(self, frame, track_id: int, det, timestamp_ms: int) -> None:
        if not self.pools.lost:
            # Fast path: no lost candidates -> assign a fresh Local ID immediately
            await self._assign_confirmed(frame, track_id, uuid.uuid4(), det, timestamp_ms)
        else:
            # Pending path: collect init embeddings, resolve via ReID
            self.pools.pending[track_id] = PendingTrack(
                track_id=track_id, camera_id=self._cam, created_ts=timestamp_ms
            )

    async def _on_pending(self, frame, pending: PendingTrack, det, timestamp_ms: int) -> None:
        pending.last_floor_x = det.floor_pos.x
        pending.last_floor_y = det.floor_pos.y
        pending.last_seen_ts = timestamp_ms
        pending.temp_positions.append(
            TempPosition(
                timestamp_ms=timestamp_ms,
                floor_x=det.floor_pos.x,
                floor_y=det.floor_pos.y,
                zone_id=det.zone_id,
                bbox_confidence=det.confidence,
                bbox_area=det.bbox.area,
            )
        )
        if len(pending.embeddings) < self._s.init_embeddings_count:
            vec = self._embed.extract(self._crop(frame, det.bbox))
            pending.embeddings.append(vec)
            pending.embedding_ts.append(timestamp_ms)
            if len(pending.embeddings) == self._s.init_embeddings_count:
                await self._resolve_pending(pending)

    async def _on_confirmed(self, frame, track_id: int, det, timestamp_ms: int) -> None:
        at = self.pools.active.get(track_id)
        if at is None:
            return  # still pending (handled in step 4) or unknown
        at.last_seen_ts = timestamp_ms
        at.confirmed_frames += 1
        if det.floor_pos is not None:
            at.floor_x, at.floor_y, at.zone_id = det.floor_pos.x, det.floor_pos.y, det.zone_id
            at.bbox_confidence = det.confidence
            self._db.append_position(
                at.local_id, self._cam, timestamp_ms, at.floor_x, at.floor_y,
                at.zone_id, det.confidence, det.bbox.area,
            )
        if at.sample_counter >= self._s.sample_interval_frames:
            at.sample_counter = 0
            await self._sample_embedding(frame, at, det, timestamp_ms)
        else:
            at.sample_counter += 1

    # ---- resolution + commit ----

    async def _resolve_pending(self, pending: PendingTrack) -> None:
        decision = resolve(pending, self.pools, self._s)
        if decision.matched:
            self.pools.lost.pop(decision.matched_lost_local_id, None)
        await self._commit(pending, decision.local_id)

    async def _commit(self, pending: PendingTrack, local_id: uuid.UUID) -> None:
        gallery = EmbeddingGallery(self._s.gallery_max_size, self._s.centroid_ema_alpha)
        for v in pending.embeddings:
            gallery.add(v)
        last = pending.temp_positions[-1]
        self.pools.active[pending.track_id] = ActiveTrack(
            track_id=pending.track_id,
            local_id=local_id,
            camera_id=self._cam,
            floor_x=last.floor_x,
            floor_y=last.floor_y,
            zone_id=last.zone_id,
            last_seen_ts=last.timestamp_ms,
            bbox_confidence=last.bbox_confidence,
            confirmed_frames=len(pending.temp_positions),
            sample_counter=0,
            gallery=gallery,
        )
        # Persist init embeddings (each with its own captured_ts), centroid, then
        # flush the buffered pending positions under the resolved Local ID.
        for vec, ts in zip(pending.embeddings, pending.embedding_ts):
            await self._db.write_embedding(local_id, self._cam, ts, vec, last.bbox_confidence, is_init=True)
        await self._db.upsert_centroid(local_id, self._cam, gallery.snapshot_centroid(), self._batch_number)
        self._db.flush_temp_positions(local_id, self._cam, pending.temp_positions)
        del self.pools.pending[pending.track_id]

    async def _assign_confirmed(self, frame, track_id: int, local_id: uuid.UUID, det, timestamp_ms: int) -> None:
        """No-lost fast path: create the ActiveTrack and bootstrap its gallery
        with one init embedding from the current frame, so the centroid is never
        None (required when the track later moves to the LostPool)."""
        gallery = EmbeddingGallery(self._s.gallery_max_size, self._s.centroid_ema_alpha)
        vec = self._embed.extract(self._crop(frame, det.bbox))
        gallery.add(vec)
        self.pools.active[track_id] = ActiveTrack(
            track_id=track_id,
            local_id=local_id,
            camera_id=self._cam,
            floor_x=det.floor_pos.x,
            floor_y=det.floor_pos.y,
            zone_id=det.zone_id,
            last_seen_ts=timestamp_ms,
            bbox_confidence=det.confidence,
            confirmed_frames=1,
            sample_counter=0,
            gallery=gallery,
        )
        self._db.append_position(
            local_id, self._cam, timestamp_ms, det.floor_pos.x, det.floor_pos.y,
            det.zone_id, det.confidence, det.bbox.area,
        )
        await self._db.write_embedding(local_id, self._cam, timestamp_ms, vec, det.confidence, is_init=True)
        await self._db.upsert_centroid(local_id, self._cam, gallery.snapshot_centroid(), self._batch_number)

    # ---- sampling (quality-gated) ----

    async def _sample_embedding(self, frame, active: ActiveTrack, det, timestamp_ms: int) -> None:
        if not self._quality_gate(det, active):
            return  # counter already reset by caller
        vec = self._embed.extract(self._crop(frame, det.bbox))
        active.gallery.add(vec)
        await self._db.write_embedding(active.local_id, self._cam, timestamp_ms, vec, det.confidence, is_init=False)
        await self._db.upsert_centroid(active.local_id, self._cam, active.gallery.snapshot_centroid(), self._batch_number)

    def _quality_gate(self, det, active: ActiveTrack) -> bool:
        return (
            det.confidence >= self._s.yolo_confidence_gate
            and active.confirmed_frames >= self._s.track_age_gate_frames
            and det.bbox.area >= self._s.min_bbox_area_px
        )

    # ---- empty / offline window (IEP1 integration) ----

    def on_empty_window(self, batch=None) -> dict:
        """No frames were delivered this window (camera offline/down). Move every
        active track to the Lost pool so it becomes a ReID candidate when the feed
        returns, and let the normal batch-boundary TTL prune it if the outage is
        long. Pending tracks (incomplete init embeddings) are dropped — their
        tracker tracks are gone and they will reappear as new detections."""
        moved = list(self.pools.active.keys())
        for track_id in moved:
            self._on_lost(track_id)
        self.pools.pending.clear()
        return {"moved_to_lost": len(moved), "lost": len(self.pools.lost)}

    # ---- batch boundary ----

    def on_batch_boundary(self, batch_number: int) -> dict:
        """Called after the last frame of a batch. Prunes the LostPool (the only
        place pruning happens) and returns metrics."""
        self._batch_number = batch_number
        pruned = self.pools.prune_lost(batch_number)
        return {
            "pruned_lost": len(pruned),
            "active": len(self.pools.active),
            "pending_carryover": len(self.pools.pending),
            "lost": len(self.pools.lost),
        }

    # ---- helpers ----

    @staticmethod
    def _crop(frame, bbox):
        h, w = frame.shape[:2]
        x1 = max(0, min(w - 1, int(round(bbox.x1))))
        y1 = max(0, min(h - 1, int(round(bbox.y1))))
        x2 = max(0, min(w, int(round(bbox.x2))))
        y2 = max(0, min(h, int(round(bbox.y2))))
        if x2 <= x1 or y2 <= y1:
            return frame[0:0, 0:0]
        return frame[y1:y2, x1:x2]
