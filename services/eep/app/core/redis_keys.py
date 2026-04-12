"""Redis key naming conventions.

All Redis keys MUST use these helpers to ensure consistency.
Keys are prefixed by domain and use colon-separated segments.

Domains:
  tracking:*       — IEP2 tracking job state
  person:*         — Real-time person records (M4)
  carryover:*      — Chunk overlap carryover (M4)
  alert:*          — Active alerts (M4)
  analytics:*      — Cached analytics (M5)
  enrollment:*     — ReID enrollment state (M3)
"""


def tracking_job(camera_id: str) -> str:
    """State of a running/completed tracking job."""
    return f"tracking:job:{camera_id}"


def person_record(store_id: str, person_id: str) -> str:
    """Real-time person record with TTL."""
    return f"person:store:{store_id}:{person_id}"


def carryover(camera_id: str) -> str:
    """Chunk overlap carryover payload."""
    return f"carryover:{camera_id}"


def alert_active(store_id: str, alert_id: str) -> str:
    """Active alert record."""
    return f"alert:store:{store_id}:{alert_id}"


def analytics_cache(store_id: str, key: str) -> str:
    """Cached analytics result."""
    return f"analytics:cache:{store_id}:{key}"


def enrollment_state(employee_id: str) -> str:
    """ReID enrollment in-progress state."""
    return f"enrollment:{employee_id}"
