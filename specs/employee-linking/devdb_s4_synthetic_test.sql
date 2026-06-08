-- S4 synthetic integration test (employee-linking).
-- Sets up a complete, controlled scenario in the dev DB so the punch_resolver tick
-- links a punch to a global_id WITHOUT needing the live IEP1-3 pipeline.
--
-- Prereqs: Step 1 (deploy EEP) + Step 2 (devdb_apply_s1.sql) from TESTING.md done.
-- Apply:  docker cp specs\employee-linking\devdb_s4_synthetic_test.sql retail-edge-postgres-1:/tmp/s4.sql
--         docker exec retail-edge-postgres-1 psql -U retailvision -d retailvision -f /tmp/s4.sql
-- Then wait ~30s (one resolver tick; punch is dated 95s ago > PUNCH_SETTLE_MS 90s) and run
-- the CHECK query at the bottom (also printed by this script).

DO $$
DECLARE
    v_store   UUID;
    v_user    UUID;
    v_ver     UUID;
    v_pcam    UUID;
    v_cc      UUID;
    v_emp     UUID;
    v_gid     UUID;
    v_t       BIGINT := (extract(epoch from now()) * 1000)::bigint - 95000;  -- 95s ago (settled)
BEGIN
    -- Use any existing store, else synthesize a user + store (works on a fresh DB).
    SELECT id, created_by INTO v_store, v_user FROM stores ORDER BY created_at LIMIT 1;
    IF v_store IS NULL THEN
        INSERT INTO users (account_type, email, password_hash, name)
            VALUES ('owner', 's4-test@example.com', 'x', 'S4 Test User') RETURNING id INTO v_user;
        INSERT INTO stores (name, slug, created_by)
            VALUES ('S4 Test Store', 's4-test-store', v_user) RETURNING id INTO v_store;
    END IF;

    -- Reuse an active version if one exists, else synthesize one.
    SELECT id INTO v_ver FROM store_config_versions
        WHERE store_id = v_store AND status = 'active' LIMIT 1;
    IF v_ver IS NULL THEN
        INSERT INTO store_config_versions (store_id, status, created_by, active_from)
            VALUES (v_store, 'active', v_user, now()) RETURNING id INTO v_ver;
    END IF;

    -- A camera config under that version (calibrated, so config API would accept it).
    SELECT id INTO v_cc FROM camera_configs WHERE version_id = v_ver LIMIT 1;
    IF v_cc IS NULL THEN
        INSERT INTO physical_cameras (store_id, name) VALUES (v_store, 'punch-cam')
            RETURNING id INTO v_pcam;
        INSERT INTO camera_configs (version_id, physical_camera_id, store_id, position_x, position_y, status)
            VALUES (v_ver, v_pcam, v_store, 5.0, 5.0, 'calibrated') RETURNING id INTO v_cc;
    END IF;

    -- Punch station at floor (5,5), radius 2m (replace any existing for this version).
    DELETE FROM punch_in_stations WHERE version_id = v_ver;
    INSERT INTO punch_in_stations (version_id, store_id, camera_config_id, world_x, world_y, radius_m)
        VALUES (v_ver, v_store, v_cc, 5.0, 5.0, 2.0);

    -- Test employee.
    DELETE FROM employees WHERE store_id = v_store AND employee_code = 'S4-TEST';
    INSERT INTO employees (store_id, name, employee_code)
        VALUES (v_store, 'S4 Synthetic', 'S4-TEST') RETURNING id INTO v_emp;

    -- A global identity standing ~0.5m from the station at time T.
    INSERT INTO global_identities (store_id, first_seen_ts, last_seen_ts, last_floor_x, last_floor_y, state)
        VALUES (v_store, v_t - 1000, v_t + 1000, 5.3, 5.4, 'active') RETURNING global_id INTO v_gid;

    INSERT INTO global_tracking_history
        (global_id, store_id, version_id, batch_number, timestamp_ms, floor_x, floor_y,
         source_camera, source_local_id, selection_score)
        VALUES (v_gid, v_store, v_ver, v_t, v_t, 5.3, 5.4,
                'punch-cam', gen_random_uuid(), 1.0);

    -- The punch, dated T (already past the settle window).
    DELETE FROM punch_events WHERE employee_id = v_emp;
    INSERT INTO punch_events (store_id, employee_id, punched_at_ms, source, status)
        VALUES (v_store, v_emp, v_t, 'simulated', 'pending');

    RAISE NOTICE 'S4 scenario ready: employee=% gid=% station=(5,5) r=2 punch_T=%', v_emp, v_gid, v_t;
    RAISE NOTICE 'Wait ~30s for the resolver tick, then run the CHECK query below.';
END $$;

-- CHECK (run again after ~30s): punch should be 'linked', identity should carry the employee.
SELECT pe.status, pe.match_distance_m, pe.linked_global_id,
       gi.is_employee, gi.employee_id,
       (SELECT count(*) FROM employee_embeddings ee WHERE ee.employee_id = pe.employee_id
          AND ee.source = 'punch_in') AS punch_in_embeddings
FROM punch_events pe
JOIN employees e ON e.id = pe.employee_id AND e.employee_code = 'S4-TEST'
LEFT JOIN global_identities gi ON gi.global_id = pe.linked_global_id;
