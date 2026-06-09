# D5 — Retire `alert_config`

_One store-wide knob set was always too blunt for per-zone, per-type alerting; `alert_rules`
replaced it. Keep its sensible numbers as the defaults a new rule starts from, then delete the
table, its endpoints, and its Settings panel so there is exactly one place alerts are configured._

## Non-obvious tooling / facts

- `/alert-config` is served from **settings.py** (`AlertConfig` model, `GET`/`PATCH`
  [settings.py:43-74](../../services/eep/app/api/routers/settings.py#L43)). Settings.jsx renders it
  ([Settings.jsx:101-149](../../frontend/src/pages/Settings.jsx#L101)) via `getAlertConfig`/
  `patchAlertConfig` ([api.js:402-406](../../frontend/src/api.js#L402)).
- Migration 0011 already said IEP4 moved off `alert_config` ("left untouched for backward
  compatibility"). **Verify** no runtime reader remains before dropping (see Rule 1).
- The five numbers map cleanly to rule fields and become the create-form defaults:
  `queue_people_threshold → people_threshold`, `queue_wait_min_threshold → threshold_minutes
  (queue)`, `queue_alert_cooldown_min → cooldown_minutes`, `absence_threshold_min →
  threshold_minutes (staff_absence)`, `shift_start_grace_min → only_during_shift grace default`.

## Architectural map

```
GREP first: confirm only settings.py + Settings.jsx read AlertConfig
core/alert_defaults.py   (NEW) RULE_DEFAULTS constants (from the old alert_config values)
api/routers/alerts.py    (+) GET /store/{slug}/alert-rules/defaults  → RULE_DEFAULTS
settings.py              (−) remove AlertConfig endpoints + model import
models/alert_config.py   (DELETE)   ·   alembic 00NN: DROP TABLE alert_config
schema.sql               (−) remove alert_config CREATE
Settings.jsx / api.js    (−) remove the alert config section + getAlertConfig/patchAlertConfig
```

## Read before implementing

- [settings.py:15,43-74](../../services/eep/app/api/routers/settings.py#L43) and the rest of its alert-config handlers
- [models/alert_config.py](../../services/eep/app/models/alert_config.py)
- [Settings.jsx:101-160](../../frontend/src/pages/Settings.jsx#L101)
- Grep the whole repo for `AlertConfig` / `alert_config` (esp. `services/iep4_alerts`,
  `core/shift_closer.py`, `core/iep4_manager.py`) — list every reader in the PR.

## Rules (verifiable)

1. **Verify-then-drop**: grep confirms only the EEP settings router + frontend read `alert_config`.
   If IEP4 / shift_closer / iep4_manager still read it, migrate those first (they should already use
   `alert_rules`). Do not drop the table until no runtime reader remains.
2. **Defaults as constants**: `core/alert_defaults.py` holds `RULE_DEFAULTS` (per-type default
   minutes/thresholds, seeded from the old `alert_config` defaults). Expose
   `GET /store/{slug}/alert-rules/defaults` so the create form pre-fills. No per-store stored config.
3. **Remove** the `/alert-config` `GET`/`PATCH` endpoints + `AlertConfigResponse`/`PatchAlertConfigRequest`
   from settings.py and the `AlertConfig` model import.
4. **Migration** `DROP TABLE IF EXISTS alert_config;` and remove its `CREATE` from `schema.sql`.
   Forward-only.
5. **Frontend**: remove the alert config section from Settings.jsx (and its save handler) and
   `getAlertConfig`/`patchAlertConfig` from api.js. Settings keeps only its non-alert settings.
6. No new audit action — deleting a table is a migration, and the endpoints are gone.

## Acceptance

- `GET`/`PATCH /alert-config` return 404 (routes gone); `alert_config` table no longer exists.
- The rule create form pre-fills thresholds from `GET /alert-rules/defaults`.
- Settings page no longer shows an alerts panel; nothing in the app calls `getAlertConfig`.
- IEP4 still fires correctly (it was already on `alert_rules`).
- Fresh DB (`schema.sql`) and migrated DB converge — neither has `alert_config`.

## Hard constraints & anti-patterns

- **Do NOT** drop the table while any service still reads it — verify first (Rule 1).
- **Do NOT** keep a second, store-wide config path alongside `alert_rules` — that is the duplication
  this removes (your locked D5).
- **Do NOT** silently lose the old numbers — preserve them as `RULE_DEFAULTS`.

## Pinned versions

`fastapi==0.115.0` · `sqlalchemy[asyncio]==2.0.30` · `alembic==1.13.1` · `react@^18.2.0`.
