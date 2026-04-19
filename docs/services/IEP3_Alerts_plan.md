# IEP3 — Alerts (Rules + Evaluation + Persistence)

**Role:** Own alert rule definitions and runtime evaluation. Consume tracking events from the EEP orchestrator, fire alerts when thresholds are breached, persist both rules and fired alerts, and expose them for acknowledgement.

**Source:** `services/iep3-alerts/`
**Primary port:** 8003
**Dependencies:** PostgreSQL, EEP (orchestrator callback)

---

## Contract (what IEP3 exposes)

| Route | Purpose | Status |
|-------|---------|--------|
| `GET /health` | Liveness | DONE |
| `POST /alerts/rules` | Create rule (`AlertRuleCreate` → `AlertRule`) | DONE (stub) |
| `GET /alerts/rules/{store_id}` | List rules | DONE (stub) |
| `PATCH /alerts/rules/{rule_id}` | Enable/disable, update threshold | DONE (stub) |
| `DELETE /alerts/rules/{rule_id}` | Delete rule | DONE (stub) |
| `POST /alerts/evaluate` | Evaluate a `TrackingEvent`, return `AlertResult[]` | DONE (stub) |
| `GET /alerts/{store_id}` | List fired alerts (filter: severity, status, date) | DONE (stub) |
| `PATCH /alerts/{alert_id}` | Acknowledge / update (`AlertUpdate`) | DONE (stub) |
| `GET /metrics` | Prometheus | NOT STARTED |

**Schemas:** `services/iep3-alerts/app/schemas.py` — `AlertRuleCreate`, `AlertRule`, `AlertRuleUpdate`, `TrackingEvent`, `AlertResult`, `Alert`, `AlertUpdate`.

---

## Current Status

| Task | Status | Notes |
|------|--------|-------|
| FastAPI skeleton + `/health` | DONE | |
| Typed schemas | DONE | |
| Stub endpoints (in-memory dicts) | DONE | `_rules`, `_alerts` in `main.py` |
| Async SQLAlchemy session | NOT STARTED | M4 |
| DB persistence (`alert_rules`, `alerts` tables) | NOT STARTED | M4 — `alerts` table exists (003 migration), need `alert_rules` |
| `RuleEngine` (zone_dwell, zone_crowding, no_staff) | NOT STARTED | M4 |
| Custom Prometheus metrics | NOT STARTED | M8 |
| Prometheus scrape target | NOT STARTED | M8 |

**Overall: ~25%.**

---

## Rule Taxonomy (MVP)

| Rule `type` | Threshold field | Fires when |
|-------------|-----------------|------------|
| `zone_dwell` | `threshold_seconds` | any person's `zone_occupancy[zone].seconds > threshold` |
| `zone_crowding` | `threshold` (int) | unique `trackId` count in zone > threshold |
| `no_staff` | `threshold_seconds` | zero persons with `personType == "employee"` in zone for > threshold |

Extensible via `rule.type` discriminator + `_check_{type}` handlers in `RuleEngine`.

---

## Implementation Tasks

### 1. Database session + migration

**Files:**
- `services/iep3-alerts/app/core/database.py` (NEW) — mirror EEP pattern (async engine + `AsyncSessionLocal`).
- `services/eep/migrations/versions/004_alert_rules.py` (NEW) — add `alert_rules(id, store_id, name, type, zone_name, threshold, threshold_seconds, enabled, created_at)`.

The existing `alerts` table (created in migration 003) is reused for fired alerts.

### 2. RuleEngine

**File:** `services/iep3-alerts/app/engine.py` (NEW)

```
class RuleEngine:
    def evaluate(event: TrackingEvent, rules: list[AlertRule]) -> list[AlertResult]:
        for rule in rules:
            if not rule.enabled: continue
            handler = getattr(self, f"_check_{rule.type}", None)
            if handler: results += handler(event, rule)

    def _check_zone_dwell(event, rule):
        sec = event.zone_occupancy.get(rule.zone_name, {}).get("seconds", 0)
        if sec > rule.threshold_seconds:
            return [AlertResult(severity="warning", message=..., zone=rule.zone_name)]

    def _check_zone_crowding(event, rule):
        count = len({p.trackId for p in event.trajectory if in_zone(p, rule.zone_name)})
        if count > rule.threshold: ...

    def _check_no_staff(event, rule):
        staff = [p for p in event.trajectory
                 if in_zone(p, rule.zone_name) and p.personType == "employee"]
        if not staff: ...
```

### 3. Replace in-memory dicts with DB queries

In `app/main.py`, swap `_rules` / `_alerts` for async SQLAlchemy queries. Keep the same endpoint shapes so EEP proxy is unaffected.

### 4. Evaluate → persist

In `POST /alerts/evaluate`:
1. Load rules for `event.store_id`.
2. Run `RuleEngine.evaluate(event, rules)`.
3. For each `AlertResult`, insert into `alerts` (status = `open`).
4. Return the `AlertResult[]` so the orchestrator can forward to live monitoring.

Acknowledge path (`PATCH /alerts/{alert_id}`): flip `status` to `acknowledged`, set `resolved_at`.

### 5. Observability

**File:** `services/iep3-alerts/app/core/metrics.py` (NEW)

```
alerts_fired_total         Counter (type, severity)
alert_evaluation_duration  Histogram
active_rules_total         Gauge
alert_acknowledged_total   Counter
```

Install `prometheus-fastapi-instrumentator`; add scrape entry in `monitoring/prometheus.yml`.

---

## Interaction Contract with Orchestrator

Orchestrator (EEP) calls IEP3 once per chunk cycle:

```
POST /alerts/evaluate
{
  "store_id": "...",
  "camera_id": "...",
  "zone_occupancy": { "Checkout": { "seconds": 120, "percent": 74 }, ... },
  "trajectory": [ { frameIdx, x, y, trackId, personType, employeeId } ],
  "timestamp": 1712345678.0
}
→ 200 [ { severity, type, zone, message, rule_id } ]
```

---

## Evaluation Criteria

- [ ] Rule CRUD round-trips through DB (not memory)
- [ ] `zone_crowding` rule fires when N unique track IDs in zone
- [ ] `zone_dwell` fires when any dwell exceeds threshold
- [ ] `no_staff` fires only when no `personType=="employee"` present
- [ ] Fired alert persists with `status="open"` until PATCH
- [ ] Prometheus counters increment on fire
- [ ] Proxy through EEP preserves status codes

---

## Key Files

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI app + endpoints |
| `app/schemas.py` | Typed I/O |
| `app/engine.py` (NEW) | `RuleEngine` |
| `app/core/database.py` (NEW) | async engine |
| `app/core/metrics.py` (NEW) | Prometheus |

---

## Re-iteration Triggers

- Too many false positives → raise thresholds, add min-duration windows
- Evaluate latency high → batch rules by store, cache in memory with 60 s TTL, invalidate on rule change
- `no_staff` firing before employees enrolled → gate behind `store.has_enrolled_staff`
