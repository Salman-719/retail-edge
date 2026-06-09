# Admin / RBAC — Cross-Store Super-Admin for the Dev Team

_Give the dev/ops team one account that can walk into any store across every owner, run
the end-to-end pipeline tester in production, and reach dev/admin-only screens — without
weakening the per-store membership model that protects real tenants. Build it on the
`is_super_admin` flag that already exists, change exactly one authorization chokepoint,
and audit every cross-store action so the power is observable._

---

## The idea

A **super-admin** is a user with `users.is_super_admin = TRUE` (the column already exists,
[user.py:19](../../services/eep/app/models/user.py#L19)). It is orthogonal to
`account_type` (`owner` / `sub_account`). Super-admins:

- See and enter **all stores across all owners** (not just `created_by` / membership).
- Bypass the store-membership `403` in the single auth dependency.
- Reach admin-only frontend screens: **Settings** and **Main Vision Debug** (DevE2E).
- Drive the **dev pipeline / debug** backend routers in production (today gated by
  `DEBUG_MODE` only).
- Have every cross-store action written to the audit log.

## Design decisions (locked)

| Decision | Choice |
|---|---|
| Admin identity | `users.is_super_admin = TRUE`. NOT a new `account_type`. |
| Where access is granted | The one existing chokepoint `get_store_context` ([store_auth.py:86](../../services/eep/app/middleware/store_auth.py#L86)). No per-router edits. |
| How admin is known per request | A `is_super_admin` **claim in the access JWT**, minted from the DB at login/refresh. Access tokens are short-lived (`ACCESS_TOKEN_EXPIRE_MINUTES=30`), so a demotion takes effect within one token lifetime (refresh re-reads the DB). |
| Admin provisioning | A **management CLI** (`python -m app.cli create-admin`), idempotent, bcrypt. Optional env-bootstrap in the EEP lifespan. **No public endpoint** — that is the production-grade answer. |
| Dev/debug routers in prod | **Always registered**, but every route requires super-admin (or `DEBUG_MODE` for local convenience). Replaces the current "registered only if `DEBUG_MODE`". |
| Frontend role source | The SPA already decodes the JWT client-side ([store.js:44](../../frontend/src/store.js#L44)); read `is_super_admin` from the same payload — no extra `/me` call. |

## What already exists (do not re-derive)

- `users.is_super_admin BOOLEAN DEFAULT FALSE` — modeled but **unused** today.
- `get_store_context` is the sole store-scoped auth dependency; `require_owner`,
  `require_owner_or_manager`, `require_permission` are the only gate helpers
  ([store_auth.py:143-163](../../services/eep/app/middleware/store_auth.py#L143)).
- `create_access_token(user_id, account_type)` mints `{sub, account_type, exp}`
  ([auth.py:25](../../services/eep/app/core/auth.py#L25)). Refresh re-mints at
  [auth.py:153](../../services/eep/app/api/routers/auth.py#L153) with the loaded `user`.
- `AsyncSessionLocal` ([database.py:18](../../services/eep/app/core/database.py#L18)) is a
  standalone session maker usable from a CLI.
- EEP runs `alembic upgrade head` in its own lifespan
  ([main.py:68](../../services/eep/app/main.py#L68)) — the env-bootstrap can hook there.
- Dev/debug routers registered only under `DEBUG_MODE`
  ([api/__init__.py:31-36](../../services/eep/app/api/__init__.py#L31)).
- New audited actions just extend `AUDIT_ACTIONS` (per spec
  [B1](../bugfixes-cleanup/B1-audit-action-validation.md)) — no migration.

## ⚠️ Note

`is_super_admin` is **not nullable / already defaulted**, so no migration is needed for the
column itself — confirm with `\d users` against the running DB before assuming. This CAT adds
**no new tables**; it adds one JWT claim, one CLI, and authz bypass logic.

## Subparts

| Spec | Subpart | Touches |
|---|---|---|
| [A1-authz-core.md](A1-authz-core.md) | JWT claim + chokepoint bypass + gate helpers | `core/auth.py`, `middleware/store_auth.py`, `routers/auth.py` |
| [A2-stores-admin-scope.md](A2-stores-admin-scope.md) | All-stores listing + login payload for admin | `routers/stores.py`, `routers/auth.py`, `schemas/auth.py` |
| [A3-provisioning.md](A3-provisioning.md) | `create-admin` CLI + optional env-bootstrap | new `app/cli.py`, `core/config.py`, `main.py` |
| [A4-devtools-gating.md](A4-devtools-gating.md) | Re-gate dev_pipeline/debug behind super-admin | `api/__init__.py`, `routers/dev_pipeline.py`, `routers/debug.py`, new `require_super_admin` |
| [A5-frontend.md](A5-frontend.md) | Admin in auth store, route guards, all-stores dashboard | `store.js`, `PrivateRoute.jsx`, `App.jsx`, `Sidebar.jsx`, `OwnerDashboard.jsx` |

## Implementation order

A1 → A2 → (A3, A4 in parallel) → A5. A5 depends on A1 (claim in JWT) and A2 (all-stores API).
Each subpart lists "Read before implementing" — honor the repo rule: read the target file
first, report any deviation from this spec before coding.

## Data-flow summary

```
login / refresh ──create_access_token(user)──▶ JWT { sub, account_type, is_super_admin, exp }
                                                       │
                       every store-scoped request ─────┤
                                                       ▼
                                          get_store_context(slug, jwt)
                                  is_super_admin? ── yes ─▶ skip membership 403,
                                                            StoreContext(is_admin=True, full access)
                                                no ─▶ existing owner/member checks
                                                       │
              require_owner / require_owner_or_manager / require_permission
                                  short-circuit return when ctx.is_admin
                                                       │
                              cross-store write ──▶ audit_logs (admin user_id recorded)
```

## Acceptance (whole CAT)

- A super-admin created via CLI can `GET /api/stores` and receive **every** store, and can
  call any `/api/store/{slug}/...` route for a store they neither own nor are a member of.
- A normal owner/member is **unchanged** — still 403 on stores they don't belong to.
- DevE2E ("Main Vision Debug") and Settings render for admin, are hidden/blocked for non-admin.
- `dev_pipeline` routes return 403 for non-admin in production, work for admin.
- Every admin cross-store mutation appears in `audit_logs` with the admin's `user_id`.
