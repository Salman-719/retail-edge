# IEP6 — AI Analytics Agent

Cloud service (`services/iep6_agent`, FastAPI :8006) that answers natural-language
questions over the retail data, produces scheduled insight reports, raises
proactive alerts, and can take guarded actions via EEP. Backed by **OpenAI**.

## Capabilities
1. **NL Q&A** — `POST /api/agent/query` `{store_id, question}` → grounded answer.
2. **Scheduled insights** — daily summary per store → `agent_insights` (+ email).
3. **Proactive alerts** — threshold/anomaly checks → `agent_alerts` (+ email).
4. **Actions via EEP** — `eep_action` tool (gated) calls EEP REST with a service JWT.

## API
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/agent/query` | NL Q&A (`{store_id, question}`) |
| GET  | `/api/agent/insights?store_id=` | latest stored insight reports |
| GET  | `/api/agent/alerts?store_id=` | proactive alerts |
| GET  | `/health` | liveness |

Routed publicly at `/api/agent` by the chart Ingress.

## Agent tools (OpenAI function calling)
- `get_metrics(metric, window_hours)` — curated, parameterized analytics over
  `global_identities` / `global_tracking_history` / `tracking_history` / `zones`:
  `footfall`, `active_visitors`, `avg_dwell_seconds`, `zone_breakdown`,
  `camera_activity`. **Preferred** (safe).
- `run_readonly_sql(sql)` — ad-hoc SELECT escape hatch. **Off by default**
  (`ENABLE_RAW_SQL`); SELECT/WITH-only + `statement_timeout`.
- `eep_action(action, args)` — state changes via EEP. **Off by default**
  (`ENABLE_EEP_ACTIONS`); allowlisted (`start_camera`/`stop_camera`); the model
  must confirm before calling.

## Config (env, from `retailvision-secrets` / values)
`DATABASE_URL_AGENT`, `REDIS_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `JWT_SECRET`,
`EEP_BASE_URL`, `SMTP_*`, `ENABLE_RAW_SQL`, `ENABLE_EEP_ACTIONS`,
`SQL_STATEMENT_TIMEOUT_MS`, `INSIGHTS_CRON_HOUR`, `ALERT_POLL_INTERVAL_S`.

## Data (alembic `0006`, also in `schema.sql`)
- `agent_insights(store_id, kind, title, body, metrics, created_at)`
- `agent_alerts(store_id, kind, severity, message, details, resolved_at, created_at)`

## Safety / cost
- Curated metrics preferred; raw SQL + EEP actions are **opt-in** flags.
- `AGENT_MAX_TOOL_STEPS` + `OPENAI_MAX_TOKENS` cap cost per request.
- No raw PII is sent (data is trajectories/IDs); key lives in Secrets Manager.
- Hardening (future): a dedicated read-only Postgres role for the SQL tool; an
  EEP service principal + `audit_logs` write for every `eep_action`.

## Deploy
Ships with the cloud Helm chart (`iep6.enabled`, default on). Prereq: seed
`retailvision/openai-api-key` in AWS Secrets Manager. Image `iep6` is built
multi-arch by CI. See DEPLOYMENT_GUIDE.
