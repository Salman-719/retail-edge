# C4 — Punch Machine Mini-Editor

_Moving the punch machine shouldn't mean walking the whole 9-step wizard. This is a focused flow:
clone the active config into a draft, place one marker, activate. All the backend already exists
(employee-linking S2 + the draft clone/activate path) — this is the right-sized UI on top of it._

## Non-obvious tooling / facts

- The punch station is **version-scoped** and already has draft endpoints (S2):
  `GET`/`PUT`/`DELETE /store/{slug}/draft/punch-station`, plus clone-into-draft and "activation just
  flips version status" ([S2](../employee-linking/S2-station-config-api.md)). **Reuse all of it** —
  no new punch API.
- A draft is single-instance (clone-when-draft-exists → 409). The mini-editor must branch on whether
  a draft already exists.
- The punch camera must be `calibrated`/`verified` (S2 requirement) to project floor coords.
- Coordinates: the marker is placed in canvas px; S2's `PUT` converts px→world metres. The shared
  `worldToPixel` (`px = world*ppm + origin`) renders it back.

## Architectural map

```
pages/PunchEditor.jsx       route config/punch (from the C3 menu)
  step 1: ensure a draft (clone active OR use existing — with notice)
  step 2: Konva map — floor plan + cameras; pick punch camera; click to drop marker; set radius
  step 3: activate (immediate)
api.js                      reuse createDraft/cloneDraft, getDraftPunchStation, putDraftPunchStation,
                            activateDraft (all existing); no new endpoints
```

## Read before implementing

- [S2-station-config-api.md](../employee-linking/S2-station-config-api.md) (the punch draft endpoints + clone + activation)
- the draft clone + activate endpoints in [draft.py](../../services/eep/app/api/routers/draft.py) and their api.js wrappers
- [StoreConfigEdit.jsx](../../frontend/src/pages/StoreConfigEdit.jsx) (reuse its camera-placement Konva patterns)

## Rules (verifiable)

1. **Entry (draft branch)**:
   - **No draft** → create a draft by cloning the active version (existing clone path; carries the
     existing punch station per S2). The editor works on this draft.
   - **Draft exists** → edit that draft's punch station and show a **clear notice**: "You have a
     configuration draft in progress. Activating here will publish all of its changes, not just the
     punch machine." (Locked decision — edit-existing-with-notice, do not block.)
2. **No calibrated camera** → show a message ("Add and calibrate a camera in full onboarding before
   setting the punch machine") and route to `config/edit`; do not present a broken placement.
3. **Editor**: render the floor plan + placed cameras (Konva). The user (a) picks the punch camera
   (must be calibrated/verified), (b) clicks to drop/move the marker, (c) sets `radius_m` (default
   1.5). Persist via S2 `PUT /draft/punch-station` (px → world handled server-side). Show the radius
   circle (radius_m × ppm).
4. **Activate (immediate only)**: on confirm, call the existing activate endpoint → the draft becomes
   the new active version. No scheduled activation in this flow.
5. **Validation surfaced**: S2's `422`s (`CAMERA_NOT_CALIBRATED`, `POINT_OUT_OF_BOUNDS`, scale
   undefined) render inline.
6. **Auth**: `require_owner_or_manager` (admin via A1).
7. **After activation**: return to the Store Setup view, which now shows the new punch marker (C1).

## Acceptance

- With no draft: editing the punch creates a draft, moves the marker, activates → new active version
  whose punch station reflects the new point (round-trips via S2 px↔metres).
- With an existing draft: the editor edits that draft and shows the "publishes all changes" notice;
  activating publishes the whole draft.
- A store with no calibrated camera shows the guidance message, not a broken canvas.
- Out-of-bounds / uncalibrated-camera attempts surface S2's 422s inline.
- Marker + radius render using the shared projection; the C1 view matches after activation.

## Hard constraints & anti-patterns

- **Do NOT** add a new punch API — reuse S2 + draft clone/activate.
- **Do NOT** edit the active version in place — punch is versioned; edits go through a draft→activate.
- **Do NOT** silently publish an existing draft's other changes — the notice (Rule 1) is mandatory.
- **Do NOT** offer scheduled activation here (immediate only, locked).
- **Do NOT** reimplement camera placement — reuse the wizard's Konva patterns + shared `worldToPixel`.

## Pinned versions

`react@^18.2.0` · `react-router-dom@^6.23.0` · `react-konva@^18.2.10` · `konva@^9.3.2` ·
`axios@^1.7.2` — all present, no additions.
