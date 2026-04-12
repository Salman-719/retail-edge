# Milestone 4: Multi-Camera Pipeline & Core E2E

**Duration:** 2 weeks
**Dependencies:** M2, M3
**Goal:** Cross-camera tracking, person database, chunk overlap/reconciliation, and basic alerts working end-to-end. First fully functional system.

---

## Current Status

| Task | Status | Notes |
|------|--------|-------|
| Chunk overlap mechanism | NOT STARTED | |
| Warm-up tracking (overlap replay) | NOT STARTED | |
| Reconciliation (ID continuity) | NOT STARTED | |
| Cross-camera ReID association | NOT STARTED | |
| Person database in Redis | NOT STARTED | |
| Entrance/exit detection | NOT STARTED | |
| Queue detection (IEP3) | NOT STARTED | Stub endpoints exist |
| Staff absence detection (IEP3) | NOT STARTED | Stub endpoints exist |
| Alert persistence to DB | NOT STARTED | In-memory dict only |
| EEP orchestration state machine | NOT STARTED | |

**Overall: ~15% complete** (only IEP3 stub endpoints exist)

---

## Implementation Tasks

### 1. Chunk Overlap Mechanism

**File:** `services/iep2-vision/app/utils/carryover.py` (NEW)

```python
class CarryoverPayload:
    """State carried between consecutive chunks for track continuity."""
    tracker_states: dict       # BoT-SORT internal state per track ID
    reid_embeddings: dict      # track_id -> latest ReID embedding (512-dim)
    id_mapping: dict           # local_track_id -> global_person_id
    last_positions: dict       # track_id -> (x, y, timestamp)

    def serialize(self) -> bytes:
        """Serialize to Redis."""

    @classmethod
    def deserialize(cls, data: bytes) -> "CarryoverPayload":
        """Restore from Redis."""
```

**Redis key:** `carryover:{camera_id}` with TTL = chunk_duration * 2

### 2. Warm-up Tracking (Overlap Replay)

**File:** `services/iep2-vision/app/utils/tracker.py`

Modify `run_tracking_job()`:
```
Phase 1: Load carryover from Redis (if exists)
Phase 2: Feed overlap frames (last 30s of prev chunk) through tracker
         - Re-establish tracks, don't emit results yet
Phase 3: Process new frames, emit trajectory + zone occupancy
Phase 4: At chunk end, serialize carryover to Redis
```

### 3. Reconciliation Logic

**File:** `services/iep2-vision/app/utils/reconciler.py` (NEW)

```python
def reconcile(carryover: CarryoverPayload, new_tracks: list) -> dict:
    """Match new chunk tracks to previous chunk's global IDs.

    Strategy:
    1. For each new track in overlap window:
       - Compare ReID embedding vs carryover embeddings (cosine sim)
       - Check spatial distance (must be < 3m)
       - Check temporal gap (must be < overlap_duration)
    2. Hungarian algorithm for optimal assignment (scipy.linear_sum_assignment)
    3. Matched tracks inherit global_person_id
    4. Unmatched tracks get new global IDs

    Returns: {local_track_id: global_person_id}
    """
```

### 4. Cross-Camera ReID Association

**File:** `services/iep2-vision/app/utils/cross_camera.py` (NEW)

```python
def associate_across_cameras(camera_results: list[dict]) -> dict:
    """Associate persons across multiple camera views.

    Input: List of per-camera results with ReID embeddings + floor positions
    Process:
      1. Build NxM appearance similarity matrix (cosine distance)
      2. Apply spatial plausibility filter:
         - Max walking speed 1.5 m/s
         - Remove impossible transitions
      3. Hungarian algorithm for optimal global assignment
      4. Merge into unified person records

    Returns: {camera_id: {local_id: global_person_id}}
    """
```

**Called by EEP after all cameras finish a chunk cycle.**

### 5. Person Database in Redis

**File:** `services/eep/app/core/person_db.py` (NEW)

```python
Redis hash structure per person:
  Key: person:{store_id}:{global_id}
  Fields:
    type: "customer" | "employee"
    employee_id: (if identified)
    current_zone: zone_name
    entered_at: ISO timestamp
    last_seen: ISO timestamp
    camera_ids: JSON list
    embedding: base64 encoded
  TTL: 1800 (30 min — customer auto-timeout)

Operations:
  create_person(store_id, global_id, type, zone, embedding)
  update_person(store_id, global_id, zone=None, camera_id=None)
  get_person(store_id, global_id)
  list_active(store_id) -> list
  get_headcount(store_id) -> int
  get_zone_occupants(store_id, zone_name) -> list
```

### 6. Entrance/Exit Detection

**File:** `services/iep2-vision/app/utils/entrance.py` (NEW)

```python
def detect_entrance_exit(trajectory, entrance_zones, fps):
    """Detect persons entering/exiting via entrance zones.

    Strategy:
    - Define entrance zones in store config (zone.type == "entrance")
    - Track first/last appearance in entrance zone
    - Use velocity vector to determine direction (in vs out)
    - Emit events: {"person_id", "direction": "enter"|"exit", "timestamp"}
    """
```

### 7. IEP3 Rule Evaluation Engine

**File:** `services/iep3-alerts/app/engine.py` (NEW)

```python
class RuleEngine:
    """Evaluate alert rules against tracking events."""

    def evaluate(self, event: TrackingEvent, rules: list[AlertRule]) -> list[AlertResult]:
        results = []
        for rule in rules:
            if not rule.enabled:
                continue
            if rule.type == "zone_dwell":
                results += self._check_dwell(event, rule)
            elif rule.type == "zone_crowding":
                results += self._check_crowding(event, rule)
            elif rule.type == "no_staff":
                results += self._check_no_staff(event, rule)
        return results

    def _check_dwell(self, event, rule):
        """Alert if any person dwells in zone > threshold_seconds."""
        zone_data = event.zone_occupancy.get(rule.zone_name, {})
        if zone_data.get("seconds", 0) > rule.threshold_seconds:
            return [AlertResult(severity="warning", ...)]

    def _check_crowding(self, event, rule):
        """Alert if zone person count > threshold_count."""
        # Count unique trackIds in zone from trajectory

    def _check_no_staff(self, event, rule):
        """Alert if no employee detected in zone for > threshold."""
        # Requires person_type from tracker (M3 employee identification)
```

### 8. IEP3 Alert Persistence

**File:** `services/iep3-alerts/app/main.py`

Replace in-memory `_rules` / `_alerts` dicts with PostgreSQL:
- Use `AsyncSessionLocal` (same pattern as EEP)
- Persist alert rules to `alert_rules` table (add via migration if needed)
- Persist fired alerts to `alerts` table
- Query alerts by store_id, severity, status, date range

### 9. EEP Orchestration

**File:** `services/eep/app/api/orchestrator.py` (NEW)

```python
Chunk processing pipeline:
  1. Receive "chunk ready" signal (from IEP1 or manual trigger)
  2. For each active camera in store:
     - POST to IEP2 /tracking/start (parallel via asyncio.gather)
  3. Poll IEP2 /tracking/progress until all cameras done
  4. Collect results from all cameras
  5. Run cross-camera association
  6. Update person database in Redis
  7. POST combined event to IEP3 /alerts/evaluate
  8. POST snapshot to IEP4 /analytics/ingest
  9. Return orchestration result

State machine: idle -> dispatching -> tracking -> associating -> alerting -> done
```

---

## Evaluation Criteria (must pass before M5)

- [ ] Track continuity across chunk boundaries: <10% ID loss at transitions
- [ ] Cross-camera association: same person gets same global ID >80% of the time
- [ ] Person database headcount matches ground truth within +/-2 people
- [ ] Entrance/exit detection >90% accuracy
- [ ] Queue alert fires when crowding threshold met
- [ ] Staff absence alert fires when employee missing >15 min
- [ ] Full 8-camera chunk pipeline completes in <3 min
- [ ] E2E test: chunk -> full pipeline -> correct DB state + alerts

## Re-iteration Triggers

- If cross-chunk ID continuity poor: increase overlap from 30s to 45-60s
- If cross-camera association fails: lower similarity threshold, average embeddings over more frames
- If orchestration timing tight: batch cameras in groups of 4 instead of all 8
