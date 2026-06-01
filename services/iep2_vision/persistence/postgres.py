"""PostgreSQL persistence — sole owner of the DB connection and tracking_history writes.

No identity logic, no embedding logic — pure DB I/O.
"""
import logging
import os
import re

import psycopg2
from dotenv import load_dotenv

log = logging.getLogger("iep2.persistence")

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS tracking_history (
    id          SERIAL PRIMARY KEY,
    local_id    INTEGER NOT NULL,
    track_id    INTEGER NOT NULL,
    camera_id   TEXT NOT NULL,
    frame_index INTEGER NOT NULL,
    x1          INTEGER NOT NULL,
    y1          INTEGER NOT NULL,
    x2          INTEGER NOT NULL,
    y2          INTEGER NOT NULL,
    confidence  REAL NOT NULL
);
"""

_INSERT_SQL = """
INSERT INTO tracking_history
    (local_id, track_id, camera_id, frame_index, x1, y1, x2, y2, confidence)
VALUES
    (%s, %s, %s, %s, %s, %s, %s, %s, %s);
"""


def _redact(dsn: str) -> str:
    """Replace password in a DSN with *** for safe logging."""
    return re.sub(r"(:)[^:@]+(@)", r"\1***\2", dsn)


class TrackingPersistence:
    def __init__(self, connection_string: str, camera_id: str):
        """Load .env if present, then open a synchronous psycopg2 connection."""
        load_dotenv()
        self._camera_id = camera_id
        log.info("Connecting to DB  camera=%s  dsn=%s", camera_id, _redact(connection_string))
        self._conn = psycopg2.connect(connection_string)
        log.info("DB connected.")

    def create_table(self) -> None:
        """Create tracking_history if it does not exist. Idempotent."""
        with self._conn.cursor() as cur:
            cur.execute(_CREATE_TABLE_SQL)
        self._conn.commit()
        log.info("Table tracking_history ready.")

    def write_detection(
        self,
        local_id: int,
        track_id: int,
        frame_index: int,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        confidence: float,
    ) -> None:
        """Insert one detection row and commit immediately."""
        with self._conn.cursor() as cur:
            cur.execute(
                _INSERT_SQL,
                (local_id, track_id, self._camera_id, frame_index,
                 x1, y1, x2, y2, confidence),
            )
        self._conn.commit()
        log.debug(
            "DB write  local_id=%d  track_id=%d  frame=%d  bbox=[%d,%d,%d,%d]  conf=%.2f",
            local_id, track_id, frame_index, x1, y1, x2, y2, confidence,
        )

    def close(self) -> None:
        """Close the connection cleanly."""
        self._conn.close()
        log.info("DB connection closed  camera=%s", self._camera_id)


# ---------------------------------------------------------------------------
# Standalone smoke test: python persistence/postgres.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level="INFO", format="%(asctime)s  %(levelname)-8s  %(message)s")
    load_dotenv()
    url = os.environ["DATABASE_URL"]

    db = TrackingPersistence(url, camera_id="cam-smoke-test")
    db.create_table()

    # Clean up any leftover rows from previous runs so count is always 3.
    with db._conn.cursor() as cur:
        cur.execute("DELETE FROM tracking_history WHERE camera_id = 'cam-smoke-test';")
    db._conn.commit()

    # Insert 3 fake rows.
    for i in range(3):
        db.write_detection(
            local_id=i + 1,
            track_id=i + 10,
            frame_index=i,
            x1=10 * i, y1=10 * i,
            x2=10 * i + 50, y2=10 * i + 80,
            confidence=0.9,
        )

    # Query back and print count.
    with db._conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM tracking_history WHERE camera_id = 'cam-smoke-test';"
        )
        count = cur.fetchone()[0]

    print(count)  # must print 3
    assert count == 3, f"expected 3 rows, got {count}"

    db.close()
    print("smoke test passed")
