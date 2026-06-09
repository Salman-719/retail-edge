# A1 — Authz Core: JWT claim, chokepoint bypass, gate helpers

_One claim in the token, one branch in one dependency, three one-line helper edits. After
this, "admin can reach everything" is true everywhere by construction — not re-checked in
every router._

## Non-obvious tooling / facts

- JWT lib is `python-jose`; tokens are `{sub, account_type, exp}` today. Adding a claim is
  backward-compatible — old tokens simply lack it, and `payload.get("is_super_admin")` is
  falsy, so they behave as non-admin until the user re-logs in or refreshes.
- `get_store_context` is the ONLY store-scoped auth dependency. Every `/store/{slug}/...`
  route depends on it. This is the single bypass point.
- Access token TTL is 30 min; the **refresh** path (auth.py:153) already has the `user` row
  loaded, so re-mint with `user.is_super_admin` to pick up promotions/demotions each cycle.

## Architectural map

```
core/auth.py
  create_access_token(user_id, account_type, is_super_admin=False)  ← add claim
middleware/store_auth.py
  StoreContext  ← add  is_admin: bool = False
  get_store_context  ← if claim is_super_admin: bypass membership, build admin ctx
  require_owner / require_owner_or_manager / require_permission  ← short-circuit on is_admin
routers/auth.py
  login + refresh  ← pass user.is_super_admin into create_access_token
```

## Read before implementing

- [core/auth.py:25-46](../../services/eep/app/core/auth.py#L25)
- [middleware/store_auth.py:32-164](../../services/eep/app/middleware/store_auth.py#L32)
- [routers/auth.py:44-55, 145-156](../../services/eep/app/api/routers/auth.py#L44)

## Rules (verifiable)

1. **`create_access_token`** gains a third param `is_super_admin: bool = False` and adds
   `"is_super_admin": is_super_admin` to the payload. Default `False` keeps all other callers
   correct without edits.
2. **Every mint of an access token passes the real value**: login (`_create_tokens`/
   `_build_login_response`) and refresh (auth.py:153) pass `user.is_super_admin`. Grep for
   `create_access_token(` and confirm no caller omits it for a known user.
3. **`StoreContext`** gains `is_admin: bool = False` (dataclass field, defaulted).
4. **`get_store_context`**: after decoding the JWT, read `is_admin = bool(payload.get("is_super_admin"))`.
   If `is_admin`:
   - Resolve slug → store as normal (admin still gets a real `store`; a 404 for a missing
     store is still correct).
   - **Skip** the Step-3 membership block (the `NOT_MEMBER` 403). Set `is_owner=False`,
     `member=None`, `role=None`, `permissions=set()`, `is_admin=True`.
   - Do NOT consult `store_members` for an admin (they may not be a member at all).
5. **Gate helpers short-circuit on admin** — each returns immediately when `ctx.is_admin`:
   - `require_owner`: `if ctx.is_admin or ctx.is_owner: return`
   - `require_owner_or_manager`: `if ctx.is_admin or ctx.is_owner or ctx.role == "manager": return`
   - `require_permission`: `if ctx.is_admin or ctx.is_owner: return`
6. **No new audit action needed here**; admin mutations reuse the existing per-route audit
   calls, which already record `ctx.user_id` (the admin). Confirm routers pass `ctx.user_id`,
   not an owner id.

## Acceptance

- Decode an admin's access token (e.g. jwt.io) → contains `"is_super_admin": true`.
- An admin calling `GET /api/store/{slug}/me` for a store they do not own/belong to returns
  `200` with `is_owner=false` (no `NOT_MEMBER` 403).
- A non-admin sub_account calling the same store they don't belong to still returns `403 NOT_MEMBER`.
- Unit test: `get_store_context` with an admin payload and a non-member store returns a
  `StoreContext(is_admin=True)`; with a non-admin payload it still raises 403.

## Hard constraints & anti-patterns

- **Do NOT** make admin a value of `account_type`. It is an orthogonal boolean — code that
  branches on `account_type == "owner"` must NOT start treating admin as owner implicitly,
  except where this spec says so explicitly.
- **Do NOT** add per-router admin checks. The whole point is one chokepoint + helper
  short-circuits. If a route needs admin-only (not store-scoped), use `require_super_admin`
  from [A4](A4-devtools-gating.md), not an inline check.
- **Do NOT** grant admin by populating a wildcard permission set — keep `permissions` empty
  and let the helpers short-circuit, so audit/debug never shows fabricated permissions.
- Keep the JWT claim name exactly `is_super_admin` (matches the DB column and the frontend reader).

## Pinned versions

Python 3.11 · `fastapi==0.115.0` · `python-jose[cryptography]==3.3.0` ·
`passlib[bcrypt]==1.7.4` · `bcrypt==3.2.2` · `sqlalchemy[asyncio]==2.0.30`.
