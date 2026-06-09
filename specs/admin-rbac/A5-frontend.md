# A5 — Frontend: admin in auth store, route guards, all-stores dashboard

_The SPA already knows everything it needs the moment the user logs in — the role is sitting
in the JWT it decodes. Surface it, guard two screens with it, un-gate the pipeline tester for
it, and let the existing dashboard render the fleet the API now returns._

## Non-obvious tooling / facts

- The auth store decodes the JWT client-side to populate `user`
  ([store.js:44-47](../../frontend/src/store.js#L44)) — add `is_super_admin` there; no `/me`
  round-trip needed.
- `PrivateRoute` only checks `tokens` ([PrivateRoute.jsx](../../frontend/src/components/PrivateRoute.jsx));
  there is no role guard yet.
- DevE2E ("Main Vision Debug", `dev/e2e`) and VisionDebugConsole ("Vision Debug", `dev/vision`)
  are gated by `import.meta.env.DEV` in [App.jsx:5-10,64-76](../../frontend/src/App.jsx#L64) and
  [Sidebar.jsx:117-148](../../frontend/src/components/Sidebar.jsx#L117). VisionDebugConsole is
  being **deleted** in B4 — do not re-gate it; only DevE2E survives, admin-gated.
- Sidebar shows "All Stores" only for `account_type === 'owner'`
  ([Sidebar.jsx:153](../../frontend/src/components/Sidebar.jsx#L153)).
- OwnerDashboard already lists whatever `GET /api/stores` returns, so admin all-stores is mostly
  a backend concern (A2) — the dashboard just needs to be reachable by admin and labeled.

## Architectural map

```
store.js        user = { user_id, account_type, is_super_admin }   ← read from JWT payload
PrivateRoute.jsx  add optional `adminOnly` prop → redirect non-admin
App.jsx          Settings route + dev/e2e route wrapped admin-only; dev/e2e no longer
                 import.meta.env.DEV-gated (ships in prod, admin-guarded)
Sidebar.jsx      Settings + "Main Vision Debug" items shown only to admin; "All Stores"
                 also shown to admin
OwnerDashboard   admin sees full fleet (from A2) with an "All stores (admin)" heading
```

## Read before implementing

- [store.js](../../frontend/src/store.js) · [PrivateRoute.jsx](../../frontend/src/components/PrivateRoute.jsx)
- [App.jsx](../../frontend/src/App.jsx) · [Sidebar.jsx](../../frontend/src/components/Sidebar.jsx)
- [OwnerDashboard.jsx](../../frontend/src/pages/OwnerDashboard.jsx)

## Rules (verifiable)

1. **`store.js`**: in the `INIT` and `LOGIN` paths, include `is_super_admin: !!payload.is_super_admin`
   in `user`. Update the `user` shape comment ([store.js:9](../../frontend/src/store.js#L9)).
2. **`PrivateRoute`** gains an optional `adminOnly` prop: if `adminOnly` and not
   `state.user?.is_super_admin`, `<Navigate>` to the store's default page (`live`) or `/dashboard`
   — never render the guarded child. Keep the existing token check.
3. **`App.jsx`**:
   - Wrap the **Settings** route in `adminOnly`.
   - Move **DevE2E** (`dev/e2e`) out of the `import.meta.env.DEV` block so it is compiled into
     production, and guard it with `adminOnly`. Drop the `lazy(import.meta.env.DEV ? ...)`
     pattern for DevE2E — import it normally (still `lazy` for bundle size is fine).
   - VisionDebugConsole (`dev/vision`) is removed entirely (B4) — delete its route here.
4. **`Sidebar.jsx`**:
   - Show **Settings** only when `state.user?.is_super_admin`.
   - Replace the `import.meta.env.DEV` dev-nav block with an `is_super_admin` block containing
     only **Main Vision Debug** (DevE2E); remove the Vision Debug entry (B4).
   - Show "All Stores" when `account_type === 'owner' || is_super_admin`.
5. **OwnerDashboard**: when `is_super_admin`, render the (now fleet-wide) list with a heading/badge
   that makes it obvious this is the admin view (e.g. "All Stores — Admin"). No new fetch logic —
   it already calls the stores list.
6. **Defense in depth**: route guards are UX, not security. The real enforcement is the backend
   (A1/A2/A4). Do not rely on hiding nav items alone.

## Acceptance

- Logged in as admin: Settings and "Main Vision Debug" appear in the sidebar and render;
  navigating directly to `/store/<slug>/settings` works.
- Logged in as a normal owner/member: Settings and Main Vision Debug are absent; direct
  navigation to those routes redirects away.
- Admin dashboard shows stores from multiple owners; clicking into any store loads it (backend
  bypass from A1).
- Production build (`vite build`) contains DevE2E (admin-gated) and does NOT contain
  VisionDebugConsole.

## Hard constraints & anti-patterns

- **Do NOT** treat hidden nav as access control — every admin-only screen must also be useless
  without backend admin (which A1/A2/A4 guarantee).
- **Do NOT** leave DevE2E behind `import.meta.env.DEV` (it would vanish in prod, defeating the
  feature) nor fully ungated (it would ship open).
- **Do NOT** read role from a separate decoded source than `account_type` — both come from the
  same JWT payload; keep one decode site in `store.js`.
- Keep `is_super_admin` naming consistent across JWT, API, and store.

## Pinned versions

`react@^18.2.0` · `react-router-dom@^6.23.0` · `vite` (current frontend toolchain) — no new deps.
