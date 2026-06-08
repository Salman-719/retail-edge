# IEP4 — alert evaluation service

**Location:** `services/iep4_alerts/`
**Runs on:** Cloud (one long-running daemon per store)
**Depends on:** PostgreSQL (TimescaleDB) — read via asyncpg; SMTP (optional)
**Provisioned by:** EEP (`iep4_manager.apply_iep4`) as a k8s StatefulSet when a
store version is activated; Docker fallback in DEBUG/production-local.

## 1. Role

IEP4 turns the live tracking/zone data IEP3 produces into **alerts**. One process
per store evaluates the store's configured alert rules (`alert_rules` and related
tables, see Alembic `0011`) on a fixed cadence and writes `alerts` rows, delivering
notifications by email when SMTP is configured.

Built-in evaluators (`app/alerts/`):
- **queue_buildup** — too many people dwelling in a checkout/queue zone.
- **staff_zone** — staff absent from / present in a designated zone.
- **staff_employee** — employee-presence rules.
Each evaluator is gated by per-rule **cooldown** (`app/alerts/cooldown.py`) to avoid
alert storms, and state is tracked per person/zone (`app/state/`).

## 2. Lifecycle (no HTTP / no gRPC)

Long-running asyncio daemon (`app/daemon.py`):
1. Load + validate settings, open an asyncpg pool, verify required tables.
2. Every `EVALUATION_BATCHES` windows, evaluate rules over recent batches
   (bounded by `MAX_LOOKBACK_BATCHES` on restart; catches up `CATCHUP_BATCH_SIZE`
   batches/cycle when behind).
3. Persist alerts; deliver email if `email_enabled`.
4. Run until SIGTERM/SIGINT, then shut down gracefully.

## 3. Configuration (env)

| Var | Default | Notes |
|---|---|---|
| `STORE_ID` | — (required) | the store this instance serves |
| `DATABASE_URL_SERVER` | — (required) | **plain** `postgresql://…` (asyncpg; `postgresql+…` is rejected) |
| `WINDOW_SECONDS` | `60` | must match IEP1/IEP2/IEP3 |
| `EVALUATION_BATCHES` | `5` | wake every N batches |
| `MAX_LOOKBACK_BATCHES` | `60` | cap replay on restart |
| `CATCHUP_BATCH_SIZE` | `1` | batches/cycle while behind |
| `ENVIRONMENT` | `production` | `development` skips email |
| `SMTP_HOST/PORT/USER/PASSWORD/FROM` | empty | email disabled when host blank |

In k8s these are set by `iep4_manager._env()` from EEP's own environment (DB URL +
SMTP come from EEP's secret-backed env). The image is `IEP4_IMAGE`
(`{registry}/iep4:{tag}`).

## 4. Deployment

- **Image:** `ghcr.io/<owner>/retailvision/iep4` (multi-arch; CI matrix entry `iep4`).
- **Cloud:** EEP creates `StatefulSet iep4-<short>` (replicas=1, SA `iep4`) on store
  activation — see `DEPLOYMENT_GUIDE.md` Part B. No Service (no inbound port).
- **Metrics:** none exposed today (no `/metrics` port); health is via the pod
  liveness probe.
