# Alerts (IEP4 → EEP → Frontend) — Design Agreement

_IEP4 already evaluates rules and writes alerts; it even auto-resolves them when the condition
clears. What's missing is everything a human touches: no API to read alerts, no API to configure
the rules, no page to do either. This CAT adds the rule-CRUD, the read/resolve API, a dedicated
Alerts page, retires the legacy `alert_config`, and feeds an alerts-over-time widget into Analytics._

---

## How it works today (grounded)

- **Rules** live in `alert_rules` (+ `alert_rule_zones` m2m). Three types, locked by DB CHECK:
  `queue_buildup` (needs `people_threshold`), `staff_absence_zone` (needs `min_employees`),
  `staff_absence_employee` (needs `employee_id`). Shared fields: `name`, `is_active`,
  `threshold_minutes`, `cooldown_minutes` (≥ threshold), `followup_interval_minutes`,
  `only_during_shift`, zones.
- **Fired alerts** are rows in `alerts`: `type` (`staff_absence` | `queue_buildup` |
  `camera_offline` | `camera_degraded`), `zone_id`, `employee_id`, `details` JSONB, `created_at`,
  and `resolved_at`/`resolution` (`auto_detected` | `manual_dismiss`)/`resolved_by`.
- **Active = `resolved_at IS NULL`.** IEP4 auto-resolves (`auto_detected`) when the condition
  clears ([queries.py:236](../../services/iep4_alerts/app/persistence/queries.py#L236)). Manual
  dismiss = `manual_dismiss` + `resolved_by`.
- `alert_state` is IEP4's internal cooldown machine — **not** user-facing.
- `staff_absence_zone`/`_employee` rules both emit `alerts.type='staff_absence'`.
- `camera_offline`/`camera_degraded` are allowed by the `alerts` CHECK but **nothing produces them
  yet** — they arrive with camera-health in CAT F. The read API is generic over all four types so
  they light up for free later.

## Decisions (locked)

| Decision | Choice |
|---|---|
| Rule types in v1 | The existing **three** only. No new evaluator types (occupancy-limit / dwell would be new IEP4 work — out of scope). |
| Severity | **New `severity` column** (`low/medium/high/critical`) on `alert_rules` (configured) and copied onto `alerts` at fire time. |
| `alert_config` | Retire it. Its numbers become **create-form defaults** only; no auto-seeded starter rules. |
| Delivery | **Polling** (the sidebar already polls active alerts). No websocket in v1. |
| Alerts-over-time | Endpoint in the **alerts** router; rendered as a widget on the **Analytics** page. |
| Alerts UI | A **dedicated Alerts page** (feed + history + rule management). Removed from Settings. |

## Subpart map

| Spec | Scope |
|---|---|
| [D3-rules-crud.md](D3-rules-crud.md) | `alert_rules`/`alert_rule_zones` CRUD + the `severity` migration. The foundation. |
| [D1-D2-read-resolve.md](D1-D2-read-resolve.md) | Read (active/history/detail) + manual resolve. |
| [D5-retire-alert-config.md](D5-retire-alert-config.md) | Drop `alert_config` + its Settings UI; defaults as constants. |
| [D7-alerts-over-time.md](D7-alerts-over-time.md) | Counts-by-bucket-and-type endpoint (Analytics widget). |
| [D4-frontend.md](D4-frontend.md) | Alerts page: feed, history, rule management, polling (D6). |

## Auth

Store-scoped via `get_store_context` (admin bypass [A1](../admin-rbac/A1-authz-core.md)). Rule CRUD
and dismiss require owner/manager; reads allow any store member. New audit actions
(`alert_rule_created/updated/deleted`, `alert_dismissed`) are one-line additions to `AUDIT_ACTIONS`
([B1](../bugfixes-cleanup/B1-audit-action-validation.md)).

## Implementation order

D3 → (D1/D2, D5, D7 in parallel) → D4. D4 depends on all the endpoints. The active-alerts read API
(D1) is **shared** with LiveMonitoring (CAT F) — build it once here.

## Cross-service note (severity)

Adding `severity` to `alerts` means **IEP4's alert INSERT must copy `rule.severity`** onto the
fired row. That is a small IEP4 change called out in D3 — not pure EEP, but required for history to
retain severity.
