"""Alert-rule create-form defaults (D5).

The retired store-wide `alert_configs` table is gone; its sensible numbers live on
here as the defaults a NEW rule starts from. There is no per-store stored config —
these are constants served by GET /store/{slug}/alert-rules/defaults so the create
form can pre-fill. Values seeded from the old alert_configs column defaults.
"""

# Common defaults + per-type overrides. Per-type threshold/cooldown come from the
# old alert_configs (queue_wait_min_threshold=7, queue_alert_cooldown_min=15,
# absence_threshold_min=15, queue_people_threshold=10); shift_start_grace_min=15
# is retained informationally.
RULE_DEFAULTS = {
    "severity": "medium",
    "followup_interval_minutes": 5,
    "only_during_shift": True,
    "shift_start_grace_min": 15,
    "by_type": {
        "queue_buildup": {
            "threshold_minutes": 7,
            "cooldown_minutes": 15,
            "people_threshold": 10,
        },
        "staff_absence_zone": {
            "threshold_minutes": 15,
            "cooldown_minutes": 30,
            "min_employees": 1,
        },
        "staff_absence_employee": {
            "threshold_minutes": 15,
            "cooldown_minutes": 30,
        },
    },
}
