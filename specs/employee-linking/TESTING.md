# Employee Linking — Testing Commands

Dev box: EEP on `http://localhost:8000`, postgres container `retail-edge-postgres-1`,
db `retailvision` (user `retailvision`).

> PowerShell note: `curl` is an alias for `Invoke-WebRequest`. Use **`curl.exe`** for the
> commands below, or run them in Git Bash / cmd.

---

## Step 0 — Recover the stack (REQUIRED FIRST — DB was several versions behind)

The dev DB volume was stale (pre-"sections-removal" era, alembic 0008) and postgres was on the
old `postgres:16-alpine` image, so EEP's `alembic upgrade head` crashed at migration 0009/0010.
Fix: recreate postgres on the TimescaleDB image (already in compose) with a **fresh volume** —
`initdb` runs the current `schema.sql`, then EEP applies 0009–0013 cleanly.

> ⚠️ This WIPES the dev database (store, users, config, tracking data). You re-onboard afterward.

Run from `C:\Users\user\Desktop\RetailVision\retail-edge`:
```powershell
docker compose build eep            # ensure the image has S1–S4 code
docker compose down                 # stop+remove containers (keeps volumes)
docker volume rm retail-edge_postgres_data
docker compose up -d                # postgres fresh-inits from schema.sql; eep migrates + boots
```
Watch EEP come up clean (migrations 0009→0013, then "punch_resolver started"):
```powershell
docker compose logs -f eep
```
Verify schema is fully current:
```powershell
docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision ^
  -c "SELECT version_num FROM alembic_version;" ^
  -c "SELECT extname FROM pg_extension WHERE extname='timescaledb';" ^
  -c "SELECT column_name FROM information_schema.columns WHERE table_name='global_identities' AND column_name IN ('is_employee','employee_id');" ^
  -c "\dt punch_events" ^
  -c "SELECT column_name FROM information_schema.columns WHERE table_name='active_person_state' AND column_name='employee_id';"
```
Expect `alembic = 0013`, `timescaledb` present, both `global_identities` link columns, the
`punch_events` table, and `active_person_state.employee_id`.

**After this, the punch schema is already present** — you do NOT need the `devdb_apply_s1.sql`
helper (that was only for the old non-migratable DB). Verify the routes:
```powershell
curl.exe http://localhost:8000/openapi.json | findstr /C:"punch-events" /C:"punch-station" /C:"dev/punch"
```

---

## Step 1 — Find your store id (you re-onboarded after the wipe)

```powershell
docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -c "SELECT id, slug FROM stores;"
```
Use the `id` as `<STORE_ID>` and `slug` as `<SLUG>` below.

---

## (Legacy) Step 2 — Apply S1 schema manually — ONLY if you skipped Step 0

If for some reason you are NOT doing the fresh recreate (DB still old), apply S1 additively:

```powershell
docker cp specs\employee-linking\devdb_apply_s1.sql retail-edge-postgres-1:/tmp/s1.sql
docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -f /tmp/s1.sql
```
Expected tail:
```
 global_identities link cols | employee_id, is_employee
 punch tables                | punch_events, punch_in_stations
```
(You'll also see `NOTICE: active_person_state absent (DB < 0010) — skipped` — expected.)

> Full path (recommended before S4/S5): switch postgres to a TimescaleDB image and run
> `alembic upgrade head` so 0009–0013 + the analytics/alerts tables exist. The helper above
> is only to exercise S2/S3 on the current 0008 box.

---

## Step 3 — Create a test employee (none exist yet)

```powershell
docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -c "INSERT INTO employees (store_id, name, employee_code) VALUES ('<STORE_ID>','Test Worker','EMP-001') RETURNING id;"
```
Copy the returned `id` → call it `<EMP_ID>` below.

---

## Step 4 — S3: dev punch trigger (no auth) + verify

```powershell
curl.exe -X POST http://localhost:8000/api/debug/dev/punch -H "Content-Type: application/json" -d "{\"store_id\":\"<STORE_ID>\",\"employee_id\":\"<EMP_ID>\"}"
```
Expect `200` JSON with `"source":"simulated","status":"pending"`.

Verify the row landed:
```powershell
docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -c "SELECT id, employee_id, punched_at_ms, source, status FROM punch_events ORDER BY created_at DESC LIMIT 5;"
```

---

## Step 5 — S3: production webhook (needs auth)

Log in as your dev owner/manager to get a JWT (replace credentials):
```powershell
curl.exe -X POST http://localhost:8000/api/auth/login -H "Content-Type: application/json" -d "{\"email\":\"YOUR_EMAIL\",\"password\":\"YOUR_PASSWORD\"}"
```
Copy `access_token` → `<TOKEN>`. Then record a punch by badge code:
```powershell
curl.exe -X POST http://localhost:8000/api/store/<SLUG>/punch-events -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" -d "{\"employee_code\":\"EMP-001\"}"
```
Expect `201` with `"source":"device","status":"pending"`. Negative checks:
```powershell
# unknown employee -> 404
curl.exe -X POST http://localhost:8000/api/store/<SLUG>/punch-events -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" -d "{\"employee_code\":\"NOPE\"}"
# future timestamp -> 422
curl.exe -X POST http://localhost:8000/api/store/<SLUG>/punch-events -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" -d "{\"employee_code\":\"EMP-001\",\"punched_at\":\"2099-01-01T00:00:00Z\"}"
```
Read back:
```powershell
curl.exe "http://localhost:8000/api/store/<SLUG>/punch-events?limit=10" -H "Authorization: Bearer <TOKEN>"
```

---

## Step 6 — S2: punch-station config (needs auth + a draft)

Prerequisites: a **draft** version with floor-plan **scale defined** and a **calibrated**
camera config. If you have a draft with a calibrated camera, get its config id:
```powershell
docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -c "SELECT cc.id, cc.status FROM camera_configs cc JOIN store_config_versions v ON v.id=cc.version_id WHERE v.store_id='<STORE_ID>' AND v.status='draft';"
```
Set the station (canvas-pixel coords; converted to metres on save):
```powershell
curl.exe -X PUT http://localhost:8000/api/store/<SLUG>/draft/punch-station -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" -d "{\"camera_config_id\":\"<CC_ID>\",\"position_x\":640,\"position_y\":360,\"radius_m\":1.5}"
```
Read it back (returns pixel coords again) and delete:
```powershell
curl.exe http://localhost:8000/api/store/<SLUG>/draft/punch-station -H "Authorization: Bearer <TOKEN>"
curl.exe -X DELETE http://localhost:8000/api/store/<SLUG>/draft/punch-station -H "Authorization: Bearer <TOKEN>"
```
Expected validation errors: no draft → 404 `NO_DRAFT`; scale not set → 422 `SCALE_NOT_DEFINED`;
uncalibrated camera → 422 `CAMERA_NOT_CALIBRATED`; point outside floor → 422 `POINT_OUT_OF_BOUNDS`.

---

---

## Step 7 — S4: resolver (synthetic integration test)

The resolver runs as a background tick inside EEP (started in lifespan). Full e2e needs the
live IEP1–3 pipeline producing tracks near the station; the script below instead seeds a
controlled scenario so you can watch the resolver link it.

Confirm the resolver started:
```powershell
docker logs retail-edge-eep-1 2>&1 | findstr /C:"punch_resolver started"
```

Run the synthetic scenario (seeds station + a global track ~0.5m away + a pending punch dated
95s ago, just past the 90s settle window):
```powershell
docker cp specs\employee-linking\devdb_s4_synthetic_test.sql retail-edge-postgres-1:/tmp/s4.sql
docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -f /tmp/s4.sql
```
Wait ~30s (one tick), then re-run the CHECK query:
```powershell
docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -c "SELECT pe.status, pe.match_distance_m, gi.is_employee, gi.employee_id FROM punch_events pe JOIN employees e ON e.id=pe.employee_id AND e.employee_code='S4-TEST' LEFT JOIN global_identities gi ON gi.global_id=pe.linked_global_id;"
```
Expected: `status = linked`, `match_distance_m ≈ 0.5`, `is_employee = t`, `employee_id` set.
(`punch_in_embeddings` will be 0 — the synthetic scenario seeds no `global_embeddings`; centroid
capture is best-effort and only runs when IEP3 has written embeddings for that global_id.)

Watch the resolver decision in logs:
```powershell
docker logs retail-edge-eep-1 2>&1 | findstr /C:"punch_resolver: linked"
```

> Note: on the 0008 dev DB the `active_person_state` mirror is skipped (table absent until
> migration 0010) — logged at debug level; the core link still succeeds. The full S4/S5 path
> needs a TimescaleDB Postgres image so 0009–0013 + the analytics/alerts tables exist.

## Cleanup (optional)

```powershell
docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -c "DELETE FROM punch_events; DELETE FROM employees WHERE employee_code IN ('EMP-001','S4-TEST');"
```
