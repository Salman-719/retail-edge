"""End-to-end integration test for the full RetailVision pipeline.

Prerequisites (must be satisfied before running):
  - Full stack running: postgres, redis, minio, eep (DEBUG_MODE=true, docker socket mounted)
  - Edge agent running and connected (status=online in edge_agents table)
  - IEP1 and IEP2 Docker images built
  - A test video with at least one visible person was processed for at least 60 s

Required env vars:
  DATABASE_URL    postgresql+asyncpg://... (rewritten to asyncpg:// internally)
  REDIS_URL       redis://localhost:6379/0
  S3_ENDPOINT_URL http://localhost:9000
  S3_ACCESS_KEY
  S3_SECRET_KEY
  S3_BUCKET
  E2E_CAMERA_ID   physical_camera.id UUID (NOT camera_config.id)
  E2E_STORE_ID    store.id UUID

Run:
  pytest tests/e2e/test_full_pipeline.py -v
"""
import asyncio
import os
import uuid

import pytest
import asyncpg
import redis.asyncio as aioredis

DATABASE_URL = os.environ.get("DATABASE_URL", "").replace(
    "postgresql+asyncpg://", "postgresql://"
)
REDIS_URL  = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CAMERA_ID  = os.environ.get("E2E_CAMERA_ID", "")
STORE_ID   = os.environ.get("E2E_STORE_ID", "")


# Fixtures are function-scoped (the default). pytest-asyncio 0.23.6 creates one
# event loop per test function; keeping fixtures at function scope ensures each
# connection is opened and closed in the same loop as the test that uses it,
# avoiding "Future attached to a different loop" errors.

@pytest.fixture
async def pg():
    conn = await asyncpg.connect(DATABASE_URL)
    yield conn
    await conn.close()


@pytest.fixture
async def redis_client():
    r = aioredis.Redis.from_url(REDIS_URL)
    yield r
    await r.aclose()


# ── tracking_history assertions ───────────────────────────────────────────────

async def test_rows_exist(pg):
    count = await pg.fetchval(
        "SELECT COUNT(*) FROM tracking_history WHERE camera_id = $1",
        CAMERA_ID,
    )
    assert count > 0, "No rows written to tracking_history"


async def test_local_id_is_uuid(pg):
    row = await pg.fetchrow(
        "SELECT local_id FROM tracking_history WHERE camera_id = $1 LIMIT 1",
        CAMERA_ID,
    )
    assert row is not None
    assert isinstance(row["local_id"], uuid.UUID), (
        f"local_id is not UUID: {type(row['local_id'])}"
    )


async def test_store_id_matches(pg):
    bad = await pg.fetchval(
        "SELECT COUNT(*) FROM tracking_history "
        "WHERE camera_id = $1 AND store_id != $2::uuid",
        CAMERA_ID,
        STORE_ID,
    )
    assert bad == 0, f"{bad} rows have wrong store_id"


async def test_timestamp_ms_populated(pg):
    # Parentheses required: AND binds tighter than OR without them.
    bad = await pg.fetchval(
        "SELECT COUNT(*) FROM tracking_history "
        "WHERE camera_id = $1 AND (timestamp_ms IS NULL OR timestamp_ms <= 0)",
        CAMERA_ID,
    )
    assert bad == 0, "Some rows have NULL or zero timestamp_ms"


async def test_floor_coords_populated(pg):
    total = await pg.fetchval(
        "SELECT COUNT(*) FROM tracking_history WHERE camera_id = $1",
        CAMERA_ID,
    )
    with_floor = await pg.fetchval(
        "SELECT COUNT(*) FROM tracking_history "
        "WHERE camera_id = $1 AND floor_x IS NOT NULL AND floor_y IS NOT NULL",
        CAMERA_ID,
    )
    assert with_floor > 0, (
        f"No rows have floor coords. total={total}, with_floor={with_floor}"
    )


async def test_bbox_area_positive(pg):
    bad = await pg.fetchval(
        "SELECT COUNT(*) FROM tracking_history "
        "WHERE camera_id = $1 AND bbox_area <= 0",
        CAMERA_ID,
    )
    assert bad == 0, f"{bad} rows have non-positive bbox_area"


async def test_bbox_confidence_range(pg):
    bad = await pg.fetchval(
        "SELECT COUNT(*) FROM tracking_history "
        "WHERE camera_id = $1 AND (bbox_confidence < 0 OR bbox_confidence > 1)",
        CAMERA_ID,
    )
    assert bad == 0, f"{bad} rows have out-of-range bbox_confidence"


# ── Redis consumer group assertions ──────────────────────────────────────────

async def test_consumer_group_exists(redis_client):
    stream = f"stream:iep1:{CAMERA_ID}"
    try:
        info = await redis_client.xinfo_groups(stream)
    except Exception:
        pytest.fail(f"Stream {stream} does not exist")
    names = [
        g["name"].decode() if isinstance(g["name"], bytes) else g["name"]
        for g in info
    ]
    assert "iep2_workers" in names, (
        f"Consumer group iep2_workers not found. Groups: {names}"
    )


async def test_no_pending_messages(redis_client):
    """
    Retry for up to 30 s. IEP2 may have a message in-flight (picked up via
    XREADGROUP but not yet ACKed) if the batch window is still open. Retrying
    gives the current batch time to complete and ACK.
    """
    stream = f"stream:iep1:{CAMERA_ID}"
    count = None
    for _ in range(6):
        pending = await redis_client.xpending(stream, "iep2_workers")
        count = pending["pending"]
        if count == 0:
            break
        await asyncio.sleep(5)
    assert count == 0, (
        f"{count} messages still pending (not ACKed) in iep2_workers"
    )


# ── S3 assertions ─────────────────────────────────────────────────────────────

async def test_frames_uploaded_to_s3():
    import boto3

    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_ENDPOINT_URL"),
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY"),
        aws_secret_access_key=os.environ.get("S3_SECRET_KEY"),
    )
    bucket = os.environ.get("S3_BUCKET", "retailvision")
    prefix = f"frames/{CAMERA_ID}/"
    resp   = s3.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=5)
    count  = resp.get("KeyCount", 0)
    assert count > 0, f"No frames found in S3 under {prefix}"
