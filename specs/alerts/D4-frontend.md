# D4 — Alerts Page (feed + history + rule management)

_One page where an owner watches what's firing, reviews what fired, and configures the rules that
decide. No mock, no Settings detour — the alert lives here, end to end._

## Non-obvious tooling / facts

- The sidebar already polls `getActiveAlerts` for its badge ([Sidebar.jsx:47](../../frontend/src/components/Sidebar.jsx#L47))
  and `api.js` already has `getActiveAlerts`/`resolveAlert` stubs pointing at the right paths.
- There is **no Alerts page or nav item yet** — add both. (LiveMonitoring's mock alert panel is CAT F;
  it will reuse the same `/alerts/active` this page uses.)
- Skeletons exist ([Skeletons.jsx](../../frontend/src/components/Skeletons.jsx)); icons via lucide.
- Severity is a real field now (D3) — color it (low→gray, medium→amber, high→orange, critical→red).
- Delivery is **polling** (locked) — no websocket.

## Architectural map

```
pages/Alerts.jsx              (NEW)  tabs: Active feed | History | Rules
components/alerts/
  AlertCard.jsx               active alert card (type, severity, zone/employee, details, dismiss)
  AlertHistoryTable.jsx       paginated resolved alerts + filters
  RuleList.jsx / RuleForm.jsx per-type create/edit form
App.jsx / Sidebar.jsx         add /store/:slug/alerts route + nav item
api.js                        + listAlertRules, getAlertRule, createAlertRule, updateAlertRule,
                              deleteAlertRule, getAlertRuleDefaults, getAlertHistory, getAlertTimeseries
                              (keep getActiveAlerts, resolveAlert)
```

## Read before implementing

- [D3-rules-crud.md](D3-rules-crud.md), [D1-D2-read-resolve.md](D1-D2-read-resolve.md) (the contracts)
- [api.js:296-406](../../frontend/src/api.js#L296) (existing stubs + where to add)
- [Sidebar.jsx](../../frontend/src/components/Sidebar.jsx), [App.jsx](../../frontend/src/App.jsx) (nav + route)

## Rules (verifiable)

1. **Route + nav**: add `/store/:slug/alerts` (route in App.jsx) and an "Alerts" nav item in the
   first sidebar group (near Analytics). The badge count can move here or stay on the sidebar.
2. **Active feed tab**: list `getActiveAlerts` as cards (type label, severity color, zone/employee
   name, human-readable `details`, age). Each card has a **Dismiss** button → `resolveAlert` →
   optimistic remove → refetch. **Poll every ~20s** (clear on unmount).
3. **History tab**: `getAlertHistory` with filters (date range, type, severity, resolution) +
   pagination; show how each ended (`auto_detected` vs `manual_dismiss` + who).
4. **Rules tab**: `listAlertRules` as a table (name, type, severity, zones, active toggle, edit,
   delete). Toggle → `updateAlertRule {is_active}`. Delete → confirm → `deleteAlertRule`.
5. **RuleForm** (create/edit), **type-driven fields**:
   - common: name, severity, threshold_minutes, cooldown_minutes (≥ threshold — validate client-side
     too), followup_interval_minutes, only_during_shift.
   - `queue_buildup`: people_threshold + zone multi-select (≥1).
   - `staff_absence_zone`: min_employees + zone multi-select (≥1).
   - `staff_absence_employee`: employee picker (no zones).
   - Pre-fill new rules from `getAlertRuleDefaults`. Surface server 422s inline.
6. **No mock anywhere**; loading→skeletons, empty active→"No active alerts", errors inline.
7. **`details` rendering**: render per-type from the JSONB (e.g. queue: "{n} people in {zone} for
   {mins}m"); fall back to a generic key/value list for unknown types (so camera alerts render too).

## Acceptance

- Creating a rule of each type via the form persists and appears in the Rules tab; invalid input
  (cooldown<threshold, missing zone) is blocked client-side and server-side.
- A live alert appears in the Active feed within one poll; dismissing it moves it to History as
  `manual_dismiss`.
- Toggling a rule inactive stops new alerts for it.
- Severity colors render; history filters + pagination work.
- The page contains no mock/demo data.

## Hard constraints & anti-patterns

- **Do NOT** reintroduce store-wide alert config UI (it's retired in D5) — configuration is per-rule.
- **Do NOT** hardcode the type→fields mapping in three places — drive the form from a single
  per-type field schema.
- **Do NOT** websocket — poll (locked). Keep the interval modest (~20s) and cleared on unmount.
- **Do NOT** special-case rendering so camera alerts break — unknown types fall back to generic.

## Pinned versions

`react@^18.2.0` · `react-router-dom@^6.23.0` · `lucide-react@^1.17.0` · `axios@^1.7.2` —
all already present. No new deps.
