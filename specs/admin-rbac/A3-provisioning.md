# A3 — Admin Provisioning: management CLI + optional env-bootstrap

_There is no public "make me admin" button — that would be the single worst endpoint in the
system. Admins are minted out-of-band by whoever controls the deployment: a CLI run by ops,
or a one-time env-seeded bootstrap on first boot. Idempotent, bcrypt, auditable._

## Non-obvious tooling / facts

- No CLI / `__main__` exists in EEP today. `AsyncSessionLocal`
  ([database.py:18](../../services/eep/app/core/database.py#L18)) is a standalone async
  session maker usable outside FastAPI. `hash_password`
  ([core/auth.py:17](../../services/eep/app/core/auth.py#L17)) is bcrypt via passlib.
- EEP already runs migrations in its lifespan (`_run_migrations` →
  [main.py:68](../../services/eep/app/main.py#L68)); the env-bootstrap hooks **after**
  migrations, **before** serving.
- Settings is `pydantic-settings` `BaseSettings` with `.env`
  ([config.py:9,69](../../services/eep/app/core/config.py#L9)); add optional bootstrap fields.

## Architectural map

```
app/cli.py            (NEW)  python -m app.cli create-admin --email .. --password ..
core/config.py        (+)    ADMIN_BOOTSTRAP_EMAIL / ADMIN_BOOTSTRAP_PASSWORD (optional)
app/main.py           (+)    after migrations: if both set and no admin → create one (idempotent)
```

## Read before implementing

- [core/database.py](../../services/eep/app/core/database.py)
- [core/auth.py:17-22](../../services/eep/app/core/auth.py#L17)
- [app/main.py](../../services/eep/app/main.py) (lifespan / `_run_migrations`)
- [models/user.py](../../services/eep/app/models/user.py)

## Rules (verifiable)

1. **`app/cli.py`** with `create-admin` (use `argparse`; no new dependency). Args:
   `--email` (required), `--password` (required), `--name` (optional). Behavior:
   - Open one `AsyncSessionLocal`.
   - Upsert by email: if the user exists, set `is_super_admin=True` (and update password only
     if `--password` given + `--force`); else insert a new user with `account_type="owner"`,
     `is_super_admin=True`, bcrypt-hashed password.
   - Commit, print the resulting `user_id` + email. **Idempotent**: re-running is a no-op
     (or a flag flip), never an error.
   - Exit code 0 on success, non-zero on validation failure.
2. **Optional env-bootstrap** (config + main):
   - Add `ADMIN_BOOTSTRAP_EMAIL: str | None = None` and `ADMIN_BOOTSTRAP_PASSWORD: str | None = None`.
   - In the lifespan, **after** `_run_migrations`: if BOTH are set AND no user with
     `is_super_admin=True` exists yet, create one (same logic as the CLI). Log a single clear
     line. If an admin already exists, do nothing (do not reset password).
   - This makes a fresh `docker compose up` self-seed an admin when those vars are present,
     and is a no-op afterward.
3. **`account_type` for admins is `"owner"`** so owner-shaped UI affordances work; elevation
   comes solely from `is_super_admin`. (See [A1](A1-authz-core.md) constraint.)
4. **Audit**: CLI creation need not write `audit_logs` (it runs out-of-band, no request user),
   but if convenient, write an `admin_created` action — if so, register it in `AUDIT_ACTIONS`
   ([B1](../bugfixes-cleanup/B1-audit-action-validation.md)). Optional, not required.

## Acceptance

- `python -m app.cli create-admin --email a@b.co --password 'x' --name Ops` creates a user
  with `is_super_admin=true`; running it again is a clean no-op.
- With `ADMIN_BOOTSTRAP_EMAIL`/`_PASSWORD` set on a virgin DB, EEP boot creates exactly one
  admin; on the next boot it creates none.
- The created admin can log in and `GET /api/stores` returns the whole fleet (validates A2).

## Hard constraints & anti-patterns

- **NEVER** expose admin creation as an HTTP endpoint, public or authed. CLI/env only.
- **NEVER** log the bootstrap password. Treat `ADMIN_BOOTSTRAP_PASSWORD` like `JWT_SECRET`.
- The bootstrap must be **fail-safe**: a bootstrap error must not crash EEP startup — log and
  continue serving (an admin can still be made via CLI).
- Do not hardcode credentials or a default admin password anywhere in the repo.
- Idempotency is mandatory — no duplicate-email crashes, no password resets on re-run without
  `--force`.

## Pinned versions

Python 3.11 stdlib `argparse` (no new dep) · `passlib[bcrypt]==1.7.4` · `bcrypt==3.2.2` ·
`sqlalchemy[asyncio]==2.0.30` · `pydantic-settings==2.2.1`.
