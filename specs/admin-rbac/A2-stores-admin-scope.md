# A2 — Stores Admin Scope: all-stores listing + login payload

_Owner sees their stores; admin sees the whole fleet. Same endpoints, one extra branch each.
This is what makes the admin dashboard real instead of empty._

## Non-obvious tooling / facts

- `GET /api/stores` ([stores.py:21](../../services/eep/app/api/routers/stores.py#L21)) is
  owner-only today (`403` unless `account_type == "owner"`) and filters
  `Store.created_by == user_id`. The frontend OwnerDashboard renders exactly this list.
- The login response is built in `_build_login_response`
  ([auth.py:57](../../services/eep/app/api/routers/auth.py#L57)) and branches on
  `account_type`. Admin must be handled **before** that branch.
- `StoreListItem` / `LoginResponse` schemas live in `schemas/auth.py`
  ([LoginResponse:36](../../services/eep/app/schemas/auth.py#L36)).

## Architectural map

```
routers/stores.py :: list_stores   ← admin → all stores; owner → created_by; else 403
routers/auth.py   :: _build_login_response  ← admin → all stores + no redirect_slug
schemas/auth.py   :: LoginResponse / RegisterResponse  ← add is_super_admin: bool
```

## Read before implementing

- [routers/stores.py:21-46](../../services/eep/app/api/routers/stores.py#L21)
- [routers/auth.py:57-87](../../services/eep/app/api/routers/auth.py#L57)
- [schemas/auth.py](../../services/eep/app/schemas/auth.py)

## Rules (verifiable)

1. **`list_stores`**: replace the owner-only guard with a three-way branch using
   `payload.get("is_super_admin")`:
   - admin → `select(Store)` (ALL stores, no `created_by` filter).
   - `account_type == "owner"` → existing `created_by == user_id` query.
   - else → `403 OWNER_REQUIRED` (unchanged).
   Ordering: sort by `name` (or `created_at`) so the admin fleet list is stable.
2. **`POST /api/stores` (create) stays owner-only.** Admins manage, they do not own stores.
   Do not relax the create guard. (An admin who needs a store creates it as an owner account,
   or we add an explicit admin-create later — out of scope here.)
3. **`_build_login_response`**: add a first branch `if user.is_super_admin:` returning ALL
   stores as `StoreRef[]`, `account_type=user.account_type`, `is_super_admin=True`,
   `redirect_slug=None` (admin lands on the all-stores dashboard, not a single store).
4. **`LoginResponse` and `RegisterResponse`** gain `is_super_admin: bool = False` so the SPA
   can read it from the response too (defense in depth alongside the JWT claim).
5. **Performance note**: the admin all-stores query is unbounded. For now a plain ordered
   select is fine (fleet is small). Leave a `# TODO pagination` marker; do not build paging yet.

## Acceptance

- Admin `GET /api/stores` returns every store in the DB regardless of `created_by`.
- Owner `GET /api/stores` returns only their own (unchanged).
- Admin login response lists all stores and `redirect_slug` is null.
- `LoginResponse.is_super_admin` is `true` for admin, `false`/absent for others.

## Hard constraints & anti-patterns

- **Do NOT** leak the admin all-stores query into the owner/sub_account paths — a regression
  here exposes cross-tenant data. Add a test asserting a non-admin owner sees only their stores.
- **Do NOT** populate `camera_count`/`active_version_label` here (still `Phase 2` placeholders);
  scope this strictly to the admin-visibility branch.
- Keep `is_super_admin` default `False` in schemas so existing clients deserialize cleanly.

## Pinned versions

`fastapi==0.115.0` · `pydantic-settings==2.2.1` (Pydantic v2) · `sqlalchemy[asyncio]==2.0.30`.
