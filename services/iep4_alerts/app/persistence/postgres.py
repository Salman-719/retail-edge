"""IEP4 persistence — all asyncpg access. SQL text lives in queries.py.

Methods acquire their own connection from the pool and autocommit, mirroring
IEP3's standalone-method style. The daemon enforces the cross-statement
ordering the spec mandates (close zone_transition_log / visit_sessions before
deleting from active_person_state).
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

import asyncpg

from app.models import AlertRule, AlertState, DeltaRow, ZoneTransition
from app.persistence import queries as q

logger = logging.getLogger(__name__)

# rule.type -> alerts.type CHECK value (alerts only allows staff_absence/queue_buildup/...)
_ALERT_TYPE = {
    "queue_buildup":          "queue_buildup",
    "staff_absence_zone":     "staff_absence",
    "staff_absence_employee": "staff_absence",
}


class AlertRepository:
    def __init__(self, pool: asyncpg.Pool, store_id: str) -> None:
        self._pool = pool
        self._store_id = uuid.UUID(store_id)

    # ── Cursor / guards ──────────────────────────────────────────────────────

    async def get_max_batch(self) -> int | None:
        async with self._pool.acquire() as conn:
            m = await conn.fetchval(q.MAX_BATCH, self._store_id)
        return int(m) if m is not None else None

    async def has_active_version(self) -> bool:
        async with self._pool.acquire() as conn:
            return await conn.fetchval(q.HAS_ACTIVE_VERSION, self._store_id) is not None

    async def get_active_version_id(self) -> uuid.UUID | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchval(q.ACTIVE_VERSION_ID, self._store_id)

    # ── Delta ────────────────────────────────────────────────────────────────

    async def get_delta(self, from_batch: int, to_batch: int) -> list[DeltaRow]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(q.GET_DELTA, self._store_id, from_batch, to_batch)
        return [
            DeltaRow(
                global_id=r["global_id"],
                zone_id=r["zone_id"],
                timestamp_ms=int(r["timestamp_ms"]),
                batch_number=int(r["batch_number"]),
                floor_x=float(r["floor_x"]),
                floor_y=float(r["floor_y"]),
                source_camera=r["source_camera"],
                is_employee=bool(r["is_employee"]),
            )
            for r in rows
        ]

    # ── active_person_state ──────────────────────────────────────────────────

    async def upsert_active_person_state(
        self,
        rows: list[tuple[uuid.UUID, uuid.UUID | None, int | None, int, int, bool]],
    ) -> None:
        """rows: (global_id, current_zone_id, entered_current_zone_at,
        last_seen_at, last_batch_number, is_employee). Bulk unnest upsert."""
        if not rows:
            return
        now = datetime.now(timezone.utc)
        global_ids   = [r[0] for r in rows]
        store_ids    = [self._store_id] * len(rows)
        zone_ids     = [r[1] for r in rows]
        entered_ats  = [r[2] for r in rows]
        last_seens   = [r[3] for r in rows]
        batch_nums   = [r[4] for r in rows]
        is_employees = [r[5] for r in rows]
        updated_ats  = [now] * len(rows)
        async with self._pool.acquire() as conn:
            await conn.execute(
                q.UPSERT_ACTIVE_PERSON_STATE,
                global_ids, store_ids, zone_ids, entered_ats,
                last_seens, batch_nums, is_employees, updated_ats,
            )

    async def load_active_person_state(self) -> list[asyncpg.Record]:
        async with self._pool.acquire() as conn:
            return await conn.fetch(q.LOAD_ACTIVE_PERSON_STATE, self._store_id)

    async def delete_active_person_state(self, global_ids: list[uuid.UUID]) -> None:
        if not global_ids:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(q.DELETE_ACTIVE_PERSON_STATE, self._store_id, global_ids)

    # ── Zone transitions ─────────────────────────────────────────────────────

    async def insert_zone_transitions(self, transitions: list[ZoneTransition]) -> None:
        if not transitions:
            return
        global_ids   = [t.global_id for t in transitions]
        store_ids    = [self._store_id] * len(transitions)
        zone_ids     = [t.zone_id for t in transitions]
        entered_ats  = [t.entered_at_ms for t in transitions]
        exited_ats   = [t.exited_at_ms for t in transitions]
        is_employees = [t.is_employee for t in transitions]
        entry_batch  = [t.entry_batch for t in transitions]
        exit_batch   = [t.exit_batch for t in transitions]
        async with self._pool.acquire() as conn:
            await conn.execute(
                q.INSERT_ZONE_TRANSITIONS,
                global_ids, store_ids, zone_ids, entered_ats,
                exited_ats, is_employees, entry_batch, exit_batch,
            )

    # ── Visit sessions ───────────────────────────────────────────────────────

    async def open_visit(
        self, global_id: uuid.UUID, entered_at_ms: int,
        is_employee: bool, version_id: uuid.UUID | None,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                q.OPEN_VISIT, global_id, self._store_id, entered_at_ms,
                is_employee, version_id,
            )

    async def close_visit(self, global_id: uuid.UUID, exited_at_ms: int) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(q.CLOSE_VISIT, self._store_id, global_id, exited_at_ms)

    # ── global_identities lifecycle ──────────────────────────────────────────

    async def get_global_states(
        self, global_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, str]:
        if not global_ids:
            return {}
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(q.GET_GLOBAL_STATES, global_ids)
        return {r["global_id"]: r["state"] for r in rows}

    # ── Rules / zones / state ────────────────────────────────────────────────

    async def load_rules(self) -> list[AlertRule]:
        async with self._pool.acquire() as conn:
            rule_rows = await conn.fetch(q.LOAD_ACTIVE_RULES, self._store_id)
            if not rule_rows:
                return []
            rule_ids = [r["id"] for r in rule_rows]
            zone_rows = await conn.fetch(q.LOAD_RULE_ZONES, rule_ids)

        zones_by_rule: dict[uuid.UUID, list[uuid.UUID]] = {}
        for zr in zone_rows:
            zones_by_rule.setdefault(zr["alert_rule_id"], []).append(zr["zone_id"])

        return [
            AlertRule(
                id=r["id"],
                type=r["type"],
                name=r["name"],
                severity=r["severity"],
                threshold_minutes=r["threshold_minutes"],
                cooldown_minutes=r["cooldown_minutes"],
                followup_interval_minutes=r["followup_interval_minutes"],
                people_threshold=r["people_threshold"],
                min_employees=r["min_employees"],
                employee_id=r["employee_id"],
                only_during_shift=r["only_during_shift"],
                zone_ids=zones_by_rule.get(r["id"], []),
            )
            for r in rule_rows
        ]

    async def load_alert_states(
        self, rule_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, AlertState]:
        if not rule_ids:
            return {}
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(q.LOAD_ALERT_STATES, rule_ids)
        return {
            r["alert_rule_id"]: AlertState(
                status=r["status"],
                condition_first_met_at=r["condition_first_met_at"],
                fired_at=r["fired_at"],
                condition_cleared_at=r["condition_cleared_at"],
                cooldown_until=r["cooldown_until"],
                last_evaluated_at=r["last_evaluated_at"],
                last_followup_at=r["last_followup_at"],
            )
            for r in rows
        }

    async def upsert_alert_state(
        self, rule_id: uuid.UUID, state: AlertState,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                q.UPSERT_ALERT_STATE,
                rule_id, state.status, state.condition_first_met_at,
                state.fired_at, state.condition_cleared_at, state.cooldown_until,
                state.last_evaluated_at, state.last_followup_at,
            )

    # ── Evaluation counts ────────────────────────────────────────────────────

    async def count_queue_buildup(
        self, zone_ids: list[uuid.UUID], threshold_ms: int,
    ) -> int:
        if not zone_ids:
            return 0
        async with self._pool.acquire() as conn:
            n = await conn.fetchval(
                q.COUNT_QUEUE_BUILDUP, self._store_id, zone_ids, threshold_ms,
            )
        return int(n or 0)

    async def count_staff_in_zones(self, zone_ids: list[uuid.UUID]) -> int:
        if not zone_ids:
            return 0
        async with self._pool.acquire() as conn:
            n = await conn.fetchval(q.COUNT_STAFF_IN_ZONES, self._store_id, zone_ids)
        return int(n or 0)

    async def has_active_shift(self, employee_id: uuid.UUID) -> bool:
        async with self._pool.acquire() as conn:
            return await conn.fetchval(q.ACTIVE_SHIFT_FOR_EMPLOYEE, employee_id) is not None

    async def latest_employee_presence(self) -> int | None:
        async with self._pool.acquire() as conn:
            v = await conn.fetchval(q.LATEST_EMPLOYEE_PRESENCE, self._store_id)
        return int(v) if v is not None else None

    # ── Alerts ───────────────────────────────────────────────────────────────

    async def insert_alert(
        self, rule_type: str, zone_id: uuid.UUID | None,
        details: dict, alert_rule_id: uuid.UUID, is_followup: bool,
        severity: str = "medium",
    ) -> None:
        alert_type = _ALERT_TYPE.get(rule_type, "queue_buildup")
        async with self._pool.acquire() as conn:
            await conn.execute(
                q.INSERT_ALERT, self._store_id, alert_type, zone_id,
                json.dumps(details), alert_rule_id, is_followup, severity,
            )

    async def resolve_alerts_for_rule(self, rule_id: uuid.UUID) -> int:
        async with self._pool.acquire() as conn:
            result = await conn.execute(q.RESOLVE_ALERTS_FOR_RULE, rule_id)
        try:
            return int(result.split()[-1])
        except (AttributeError, ValueError):
            return 0

    async def get_zone_names(
        self, zone_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, str]:
        if not zone_ids:
            return {}
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(q.ZONE_NAMES, zone_ids)
        return {r["id"]: r["name"] for r in rows}

    async def get_recipients(self) -> list[str]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(q.RECIPIENTS, self._store_id)
        return [r["email"] for r in rows if r["email"]]
