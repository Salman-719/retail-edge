# Employee Linking — Punch-In Anchored Global-ID ↔ Employee Linkage

_Goal: for every tracked person, know whether they are an employee and **which** one,
by linking IEP3's `global_id` to `employees.id` using a punch-in event as the
ground-truth spatiotemporal anchor._

---

## The idea

1. A punch-in machine (simulated for now) emits `(employee_id, timestamp)` when an
   employee scans in.
2. The store manager has designated, in store config, **which camera sees the punch
   machine** and **where on the floor the machine sits** (a point + radius, in world
   metres).
3. At punch time `T`, a resolver finds the `global_id` whose floor position was within
   `radius_m` of the machine point at `≈T` (using `global_tracking_history`).
4. That `global_id` is linked: `global_identities.is_employee = TRUE`,
   `global_identities.employee_id = <id>`. The matched person's appearance centroids are
   snapshotted into `employee_embeddings(source='punch_in')` for future re-linking.
5. IEP4 (alerts) and IEP5 (analytics) — already written to consume `is_employee` and
   `employee_id` — now produce real per-employee presence, punctuality, and targeted
   staff-absence alerts.

## Design decisions (locked)

| Decision | Choice |
|---|---|
| Link mechanism | **Positional** match + **capture embedding** (copy centroid → `employee_embeddings`) |
| Link lifetime | **Per-punch, ReID-persisted.** One punch stamps `employee_id` onto the current `global_id`. IEP3's existing ReID recovery (it matches re-appearing tracks against the `active`+`lost` candidate pool via `global_embeddings`, see [repository.py:444](../../services/iep3_reconciliation/app/repository.py#L444)) keeps that `global_id` stable across loss/re-acquisition, so the link continues normally for the life of the identity. Only a terminal `exited` → brand-new `global_id` (employee fully leaves and returns) needs a re-punch. The captured `employee_embeddings(source='punch_in')` seed a future phase-2 auto-re-attach for that case. |
| Machine location | **Floor point + radius** (world metres), reusing the P1 px↔metres coordinate system. Manager also picks the punch camera. |
| Simulation | **Production-shaped webhook** (`POST .../punch-events`) + a DEBUG-mode dev trigger. |
| Consumer scope | **Populate link + upgrade IEP4/IEP5** to use the specific `employee_id`. |
| Activation gate | Resolver runs **only for stores with a punch-in station in their active version**. |

## What the codebase already provides (consumer contract — do not re-derive)

- **IEP4** `GET_DELTA` ([iep4_alerts/app/persistence/queries.py:31](../../services/iep4_alerts/app/persistence/queries.py#L31))
  joins `global_identities gi` for `gi.is_employee` and propagates it into
  `active_person_state`, `zone_transition_log`, `visit_sessions`.
- **IEP4** `staff_employee.py` and **IEP5** `employees.py` both document the *exact*
  limitation this feature removes: "there is no employee_id ↔ global_id link (Employee
  ReID flow not implemented)."
- `employee_embeddings.source` already permits `'punch_in'`
  ([schema.sql:338](../../services/eep/schema.sql#L338)).

## ⚠️ Latent gap this feature must repair

`global_identities.is_employee` is **read by IEP4's `GET_DELTA`** but is **defined in no
migration and absent from `schema.sql`** (the `global_identities` CREATE TABLE at
[schema.sql:794](../../services/eep/schema.sql#L794) has no such column, and no migration
ALTERs it in). IEP3 inserts global identities without it. **S1 adds this column**, which
also makes IEP4's existing query valid. Before implementing S1, run `\d global_identities`
against the running DB to confirm — the `ADD COLUMN IF NOT EXISTS` is safe either way.

## Subparts

| Spec | Subpart | Touches |
|---|---|---|
| [S1-schema.md](S1-schema.md) | Schema & data model | Alembic `0013`, `schema.sql` |
| [S2-station-config-api.md](S2-station-config-api.md) | Punch-station config (draft wizard) | `eep/app/api/routers/draft.py`, `schemas/draft.py`, models |
| [S3-punch-ingestion.md](S3-punch-ingestion.md) | Punch ingestion + simulation | new `routers/punch.py`, `dev_pipeline.py`, `schemas/punch.py` |
| [S4-resolver.md](S4-resolver.md) | Linking engine (background tick) | new `core/punch_resolver.py`, `main.py` lifespan, `settings` |
| [S5-consumer-upgrade.md](S5-consumer-upgrade.md) | IEP4/IEP5 use the specific `employee_id` | `iep4_alerts/...`, `iep5_analytics/aggregators/employees.py` |

## Implementation order

S1 → (S2, S3 in parallel) → S4 → S5. S4 depends on S1+S2+S3. S5 depends on S4 producing
links. Each spec lists "Read before implementing" — honor the repo rule: read target
files first, report deviations.

## Data-flow summary

```
punch machine ──POST /punch-events──▶ punch_events(status=pending)
                                              │
                       resolver tick (settled, station in active version)
                                              ▼
        global_tracking_history  ──nearest within radius_m at ≈T──▶ global_id
                                              │
   ┌──────────────────────────────────────────┼───────────────────────────────┐
   ▼                                           ▼                                ▼
global_identities                       active_person_state            employee_embeddings
 is_employee=TRUE                        is_employee=TRUE                source='punch_in'
 employee_id=<id>                        employee_id=<id>                (centroid copy)
                                         (live IEP4 state)
                                              │
                                punch_events.status=linked
                                              │
                  IEP4 alerts / IEP5 analytics join global_id→employee_id
```
