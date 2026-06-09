# Store Setup (formerly "Store Config") — Design Agreement

_The old page conflated viewing and editing and force-launched a 9-step wizard for any change.
Split it: a read-only "Store Setup" dashboard that shows the whole store at a glance — cameras,
zones, schedule, punch machine, floor map — and an Edit menu that routes each kind of change to the
right-sized flow. Edits always go through versioning; the view never mutates state._

---

## Decisions (locked)

| Decision | Choice |
|---|---|
| Name | **"Store Setup"** (was "Store Config"). |
| View | **Read-only split view**: 2D map centerpiece + Cameras + Zones panels (expandable detail) + Schedule + Punch-in panels + collapsible version history. |
| Edits | **Everything requires versioning** — the view has no inline edits; all changes go through the Edit menu. |
| Edit menu | A dropdown/modal with **three paths**: Edit Schedule (live), Edit Punch Machine (versioned mini-editor), Edit Floor/Zones/Cameras (the existing 9-step wizard, unchanged). |
| Draft behavior | Even with a draft in progress, land on the menu — never auto-enter the wizard. |
| Schedule | **Live, non-versioned** — C2 `PUT /operating-hours`. |
| Punch machine | **Versioned** — a focused mini-editor that clones the active version into a draft, edits only the punch marker (reusing employee-linking S2), and activates immediately. |
| Camera details | Show config fields **plus live online/offline** from F2 camera-health. |
| Zone details | Name, type, **computed area**, and **count of alert rules** targeting the zone (CAT D). |
| Map | Zoom/pan + layer toggles (zones/cameras/obstacles/punch); punch shown as point + radius. |

## Coordinate convention (now confirmed)

The authoritative world↔pixel mapping is `px = world * pixels_per_meter + origin`
(helpers `_px_to_world`/`_world_to_px` in [draft.py](../../services/eep/app/api/routers/draft.py),
documented in [employee-linking S2](../employee-linking/S2-station-config-api.md#L19)). The shared
frontend `worldToPixel` helper (used by zones, heatmap [E3], live persons [F]) MUST use this exact
formula. `origin` is a pixel offset; `pixels_per_meter` is the scale.

## Subpart map

| Spec | Scope | Status |
|---|---|---|
| [C2-store-operating-hours.md](C2-store-operating-hours.md) | Store hours data model + scheduler + API. | done (foundation) |
| [C3-shell-edit-menu.md](C3-shell-edit-menu.md) | Rename, Store Setup shell, routing, the Edit menu, read-only enforcement. | the backbone |
| [C1-split-view.md](C1-split-view.md) | The read-only dashboard content: cameras/zones/schedule/punch/map panels. | |
| [C4-punch-mini-editor.md](C4-punch-mini-editor.md) | Focused punch-in editor reusing S2 draft endpoints + clone + activate. | |

## Dependencies (degrade gracefully)

- **C2** (operating hours API) for the Schedule panel + Edit Schedule.
- **S2** (employee-linking punch-station draft API) for C4 — already specced.
- **F2** (camera health) for live camera status in C1 — if absent, omit the live dot.
- **CAT D** (alert rules) for per-zone rule counts in C1 — if absent, omit the count.
- **Shared `worldToPixel`** helper (E-frontend) for the map.

## Auth

Store Setup view: any store member (read). Edit paths (schedule / punch / onboarding):
`require_owner_or_manager`; admin via [A1](../admin-rbac/A1-authz-core.md).

## Implementation order

C2 (done) → C3 → C1 → C4. C1 depends on the C3 shell; C4 depends on S2 + the draft clone/activate
flow that already exists.
