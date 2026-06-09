# B3 + B4 — Delete LiveView & VisionDebugConsole

_Two pages are dead weight: "Live View" is superseded by Live Monitoring, and "Vision Debug" (the
single-camera IEP2 console) is replaced by the admin-gated end-to-end tester. Remove them cleanly —
pages, routes, nav, the dev-only env var, and the dev-only backend service that existed only to feed
the deleted console — so nothing dangling ships._

## Scope

- **B3**: delete **LiveView** (page `live-view`).
- **B4**: delete **VisionDebugConsole** (page `dev/vision`) + its env var `VITE_IEP2_DEV_API_URL` +
  the `iep2_dev` compose service.
- **Keep** DevE2E ("Main Vision Debug") — it survives and is admin-gated by
  [A5](../admin-rbac/A5-frontend.md). Do not touch it here beyond not deleting it.

## Non-obvious tooling / facts (verified refs)

- LiveView is referenced only in: [App.jsx:32,55](../../frontend/src/App.jsx#L32) (import + route),
  [Sidebar.jsx:15](../../frontend/src/components/Sidebar.jsx#L15) (nav), and the page file. The store
  index redirects to `live` (LiveMonitoring), **not** `live-view` — removal breaks no default route.
- LiveView uses `VITE_LIVE_BRIDGE_URL` — but **DevE2E also uses it**
  ([DevE2E.jsx:19](../../frontend/src/pages/DevE2E.jsx#L19)). So `VITE_LIVE_BRIDGE_URL` **stays**;
  only the LiveView page goes.
- VisionDebugConsole is referenced in: [App.jsx:5-7,63-68](../../frontend/src/App.jsx#L63) (lazy
  import + route), [Sidebar.jsx:116-134](../../frontend/src/components/Sidebar.jsx#L116) (the "Vision
  Debug" entry inside the dev-nav block), the page file, and it is the **only** consumer of
  `VITE_IEP2_DEV_API_URL` ([VisionDebugConsole.jsx:12](../../frontend/src/pages/VisionDebugConsole.jsx#L12)).
- The `iep2_dev` compose service (port 8002, `--profile dev`,
  [docker-compose.yml:413](../../docker-compose.yml#L413)) exists **only** to serve VisionDebugConsole.
  DevE2E uses `live_bridge` (8010) + `dev_pipeline` (`/api/debug/dev`), not `iep2_dev`.
- The Sidebar dev-nav block (lines 116-149) contains BOTH "Vision Debug" (delete) and "Main Vision
  Debug" (keep). [A5](../admin-rbac/A5-frontend.md) rewrites this block to an admin-gated block with
  only Main Vision Debug — **coordinate**: B4 removes the Vision Debug entry; A5 handles the gate.

## Read before implementing

- [App.jsx](../../frontend/src/App.jsx), [Sidebar.jsx](../../frontend/src/components/Sidebar.jsx)
- [docker-compose.yml:405-430](../../docker-compose.yml#L405) (`iep2_dev`)
- [frontend/.env.example](../../frontend/.env.example) (the `VITE_IEP2_DEV_API_URL` block)

## Rules (verifiable)

1. **B3**: delete `frontend/src/pages/LiveView.jsx`; remove its import + `live-view` route from
   App.jsx; remove the "Live View" nav item from Sidebar.jsx. Grep `live-view`/`LiveView` → zero hits.
2. **B4**: delete `frontend/src/pages/VisionDebugConsole.jsx`; remove the lazy import + `dev/vision`
   route from App.jsx; remove the "Vision Debug" entry from the Sidebar dev-nav block (leave Main
   Vision Debug for A5).
3. **B4 env**: remove `VITE_IEP2_DEV_API_URL` from `frontend/.env` and `frontend/.env.example` (and
   the explanatory comment). Confirm no other file reads it.
4. **B4 compose**: remove the `iep2_dev` service (and its comment block) from `docker-compose.yml`.
   Confirm nothing else `depends_on` it.
5. **Coordination**: if A5 has not yet landed, leave the dev-nav block compiling (Main Vision Debug
   still present); B4 must not delete Main Vision Debug.

## Acceptance

- App builds; no broken imports. `grep -ri "LiveView\|live-view\|VisionDebugConsole\|dev/vision\|VITE_IEP2_DEV_API_URL\|iep2_dev"` returns nothing in `frontend/src`, `frontend/.env*`, and `docker-compose.yml`.
- Navigating to `/store/<slug>/live-view` or `/dev/vision` no longer resolves (falls through to the catch-all).
- DevE2E ("Main Vision Debug") still works and still uses `VITE_LIVE_BRIDGE_URL`.
- `docker compose --profile dev up` no longer references `iep2_dev`.

## Hard constraints & anti-patterns

- **Do NOT** remove `VITE_LIVE_BRIDGE_URL` — DevE2E (and future live wiring) needs it.
- **Do NOT** delete DevE2E or the live_bridge service — only LiveView, VisionDebugConsole, and iep2_dev.
- **Do NOT** delete the whole Sidebar dev-nav block — only the Vision Debug entry (A5 owns the rest).
- Leave `services/iep2_vision` intact — only the **dev wrapper service** in compose is removed, not
  the IEP2 vision service itself.

## Pinned versions

`react@^18.2.0` · `react-router-dom@^6.23.0` · Docker Compose v2 — no version changes.
