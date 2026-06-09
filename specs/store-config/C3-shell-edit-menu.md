# C3 — Store Setup Shell, Rename & Edit Menu

_Rename the screen, make it read-only, and replace the one button that always jumped into the
9-step wizard with a menu that sends each kind of change to its right-sized flow. This is the
backbone the split view (C1) and the punch editor (C4) plug into._

## Non-obvious tooling / facts

- The view page is [StoreConfig.jsx](../../frontend/src/pages/StoreConfig.jsx); the wizard is
  [StoreConfigEdit.jsx](../../frontend/src/pages/StoreConfigEdit.jsx) at route `config/edit`. The
  view's header button currently navigates straight to `config/edit` (or "Continue Draft").
- The view currently has **inline camera edits** (height/stream via `patchCamera`/`updateCameraConfig`,
  [StoreConfig.jsx:354-420](../../frontend/src/pages/StoreConfig.jsx#L354)) — these are removed
  (read-only decision).
- Sidebar label is "Store Config" ([Sidebar.jsx:23](../../frontend/src/components/Sidebar.jsx#L23));
  `usePageTitle('Store Config')` at [StoreConfig.jsx:159](../../frontend/src/pages/StoreConfig.jsx#L159).
- Routes live in [App.jsx:52-53](../../frontend/src/App.jsx#L52).
- A draft is single-instance (creating one when a draft exists → 409). The menu must reflect draft
  state without auto-entering it.

## Architectural map

```
pages/StoreSetup.jsx        (rename of StoreConfig.jsx) — read-only shell, renders C1 panels
components/store/EditMenu.jsx  dropdown/modal: Edit Schedule | Edit Punch | Edit Floor/Zones/Cameras
App.jsx                     routes: config (Store Setup) , config/edit (wizard, unchanged),
                            config/punch (C4 mini-editor) ; schedule = modal on the shell
Sidebar.jsx                 label "Store Config" → "Store Setup"
```

## Read before implementing

- [StoreConfig.jsx](../../frontend/src/pages/StoreConfig.jsx) (the page being reshaped)
- [App.jsx](../../frontend/src/App.jsx), [Sidebar.jsx](../../frontend/src/components/Sidebar.jsx)
- [C2-store-operating-hours.md](C2-store-operating-hours.md) (Edit Schedule target), [C4](C4-punch-mini-editor.md)

## Rules (verifiable)

1. **Rename**: nav label, page title, and headings "Store Config"/"Store Configuration" → **"Store
   Setup"**. Keep the route path `config` (minimal churn); only the label/title change. Rename the
   page component file to `StoreSetup.jsx` (update imports).
2. **Read-only view**: remove the inline camera edit form and the `patchCamera`/`updateCameraConfig`
   calls from the view. The view never mutates config. (Operational note: this routes even an
   RTSP/height tweak through the onboarding path — accepted per the versioning principle.)
3. **Edit menu** (`EditMenu.jsx`), opened from a single "Edit" button, three items:
   - **Edit Schedule** → opens the schedule editor (modal/drawer) backed by C2
     `GET`/`PUT /operating-hours` — live, no draft.
   - **Edit Punch Machine** → navigates to `config/punch` (C4).
   - **Edit Floor / Zones / Cameras** → navigates to `config/edit` (the existing wizard, unchanged).
4. **Draft-aware, never auto-enter**: if a draft exists, surface it in the menu/header ("Draft in
   progress — Resume" as an explicit item) but the default landing is always the menu, not the
   wizard. The old "Continue Draft" auto-jump is removed.
5. **No-active-config state**: when there is no active version, the menu's primary action is
   "Start Onboarding" (→ `config/edit`); Schedule/Punch items are disabled until a version exists.
6. **Auth**: the view loads for any store member; the Edit menu actions require owner/manager (admin
   via A1) — hide/disable for viewers.
7. **Routing**: add `config/punch`; keep `config/edit`. Schedule is a modal on the shell (no route)
   unless you prefer `config/schedule` — either is fine, pick one and be consistent.

## Acceptance

- The screen, nav, and title read "Store Setup".
- The view shows no editable fields; there is no way to mutate config without going through the menu.
- The Edit button opens the three-way menu; each item lands on the correct flow.
- With a draft present, the page still lands on the view+menu (not the wizard); a "Resume draft"
  affordance is available but not automatic.
- A viewer (non-owner/manager) sees the read-only view without edit actions; an admin sees everything.

## Hard constraints & anti-patterns

- **Do NOT** keep any inline edit on the view — read-only is the whole point.
- **Do NOT** auto-launch the wizard on load when a draft exists.
- **Do NOT** fork the wizard — the "Edit Floor/Zones/Cameras" path reuses `config/edit` as-is.
- **Do NOT** gate the read view behind owner/manager — members can view; only edits are gated.

## Pinned versions

`react@^18.2.0` · `react-router-dom@^6.23.0` · `lucide-react@^1.17.0` — no new deps.
