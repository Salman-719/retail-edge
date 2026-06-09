# A4 — Dev/Debug Router Gating: super-admin in production

_The end-to-end pipeline tester is too useful to be dev-only and too dangerous to be open.
Ship it in production, but behind the super-admin gate — and keep the local `DEBUG_MODE`
fast-path so day-to-day dev doesn't need to log in as admin._

## Non-obvious tooling / facts

- `dev_pipeline` (`/api/debug/dev/...`, [dev_pipeline.py:28](../../services/eep/app/api/routers/dev_pipeline.py#L28))
  and `debug` (`/api/debug`, [debug.py:9](../../services/eep/app/api/routers/debug.py#L9)) are
  **registered only when `settings.DEBUG_MODE`** ([api/__init__.py:31-36](../../services/eep/app/api/__init__.py#L31)).
  In production (`DEBUG_MODE=false`) they do not exist, so DevE2E ("Main Vision Debug") is dead
  there.
- These routes are **not** store-membership-scoped the way `/store/{slug}` routes are; some take
  a store/slug as a param. They need their own admin gate, not `get_store_context`.
- The frontend DevE2E page drives these routes through the `/api` proxy, so once the routes
  exist in prod + the SPA un-gates the page for admin ([A5](A5-frontend.md)), it works through
  nginx with no new wiring.

## Architectural map

```
core/auth.py (or middleware)  require_super_admin(payload)  ← NEW dependency
api/__init__.py  register dev_pipeline + debug ALWAYS, with router-level dependency:
                 allow if payload.is_super_admin  OR  settings.DEBUG_MODE
```

## Read before implementing

- [api/__init__.py](../../services/eep/app/api/__init__.py)
- [core/auth.py:49-55](../../services/eep/app/core/auth.py#L49) (`get_current_user_payload` — reuse it)
- [routers/dev_pipeline.py:1-30](../../services/eep/app/api/routers/dev_pipeline.py#L1)
- [routers/debug.py:1-12](../../services/eep/app/api/routers/debug.py#L1)

## Rules (verifiable)

1. **New dependency `require_super_admin`** (in `core/auth.py` next to
   `get_current_user_payload`):
   - Decode the JWT (reuse `get_current_user_payload`).
   - Allow if `payload.get("is_super_admin")` is true.
   - Else, allow if `settings.DEBUG_MODE` is true (local dev convenience).
   - Else raise `403 {"error": "Super-admin required", "code": "ADMIN_REQUIRED"}`.
2. **Register dev/debug routers unconditionally** in `register_routers`, attaching
   `dependencies=[Depends(require_super_admin)]` at `include_router` (router-level gate covers
   every route). Remove the `if settings.DEBUG_MODE:` guard around registration.
3. **Keep route prefixes identical** (`/api/debug/dev`, `/api/debug`) so existing DevE2E calls
   and Postman collections keep working.
4. **No behavior change in local dev**: with `DEBUG_MODE=true`, the gate passes for everyone,
   exactly as today.
5. If any dev route writes audit entries, ensure its action is in `AUDIT_ACTIONS`
   ([B1](../bugfixes-cleanup/B1-audit-action-validation.md)).

## Acceptance

- With `DEBUG_MODE=false`: a non-admin token → `403 ADMIN_REQUIRED` on `/api/debug/dev/*`;
  an admin token → routes work.
- With `DEBUG_MODE=true`: routes work for any authenticated user (unchanged dev experience).
- The OpenAPI schema in production now lists the dev routes (previously absent) — acceptable,
  they are gated.

## Hard constraints & anti-patterns

- **Do NOT** leave these routes open in production. The gate is mandatory; the only bypass is
  `DEBUG_MODE`, which must default `False` ([config.py:67](../../services/eep/app/core/config.py#L67)).
- **Do NOT** route these through `get_store_context` (they aren't pure store-membership routes);
  use `require_super_admin`.
- **Do NOT** duplicate the admin check inside each handler — the router-level dependency is the
  single gate.
- Confirm production `.env` does not accidentally set `DEBUG_MODE=true` (that would open the
  routes to all authed users). Flag in the deploy checklist.

## Pinned versions

`fastapi==0.115.0` · `python-jose[cryptography]==3.3.0`.
