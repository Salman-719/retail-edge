"""Shared dataclasses for IEP4. Neutral module to avoid circular imports
between the persistence, state, and alerts layers.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass
class DeltaRow:
    """One global_tracking_history row in the per-cycle delta."""
    global_id:    uuid.UUID
    zone_id:      uuid.UUID | None
    timestamp_ms: int
    batch_number: int
    floor_x:      float
    floor_y:      float
    source_camera: str
    is_employee:  bool


@dataclass
class PersonState:
    """In-memory snapshot of one person's active_person_state, carried between
    cycles so zone changes can be detected without a DB read."""
    global_id:               uuid.UUID
    current_zone_id:         uuid.UUID | None
    entered_current_zone_at: int | None
    last_seen_at:            int
    last_batch_number:       int
    is_employee:             bool
    # Batch at which the person entered current_zone_id — for zone_transition_log
    # entry_batch on the *next* transition. Not persisted; tracked in memory.
    entered_zone_batch:      int | None = None


@dataclass
class ZoneTransition:
    global_id:     uuid.UUID
    zone_id:       uuid.UUID          # the zone being EXITED (previous zone)
    entered_at_ms: int
    exited_at_ms:  int
    is_employee:   bool
    entry_batch:   int
    exit_batch:    int


@dataclass
class AlertRule:
    id:                        uuid.UUID
    type:                      str
    name:                      str
    severity:                  str
    threshold_minutes:         int
    cooldown_minutes:          int
    followup_interval_minutes: int
    people_threshold:          int | None
    min_employees:             int | None
    employee_id:               uuid.UUID | None
    only_during_shift:         bool
    zone_ids:                  list[uuid.UUID] = field(default_factory=list)


@dataclass
class AlertState:
    status:                 str = "idle"   # idle | firing | cooldown
    condition_first_met_at: int | None = None
    fired_at:               int | None = None
    condition_cleared_at:   int | None = None
    cooldown_until:         int | None = None
    last_evaluated_at:      int | None = None
    last_followup_at:       int | None = None
