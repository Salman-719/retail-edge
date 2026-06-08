"""staff_absence_employee evaluator.

Condition met when the targeted employee has not been seen for
threshold_minutes (or is absent entirely). When only_during_shift is TRUE and
the employee has no shift_instance with status='active' covering now, the rule
is SKIPPED (returns None) — never read employees.is_on_shift.

LIMITATION: the schema has no employee_id <-> global_id link (the Employee
ReID flow that would populate it is not implemented). So presence is derived
from the most recently seen *employee* (global_identities.is_employee = TRUE),
not the specific rule.employee_id. Until the ReID linkage exists this rule
reflects "any staff member" presence. Documented as a known deviation.
"""
from __future__ import annotations

from app.alerts.cooldown import FireContext
from app.models import AlertRule


async def evaluate(repo, rule: AlertRule, now_ms: int):
    # only_during_shift gating — derive from shift_instances, never is_on_shift.
    if rule.only_during_shift:
        if rule.employee_id is None or not await repo.has_active_shift(rule.employee_id):
            return None  # skip this rule entirely this cycle

    threshold_ms = rule.threshold_minutes * 60_000
    last_seen = await repo.latest_employee_presence()
    condition_met = last_seen is None or (now_ms - last_seen) >= threshold_ms

    minutes_absent = None if last_seen is None else round((now_ms - last_seen) / 60_000, 1)
    details = {
        "rule": rule.name,
        "type": rule.type,
        "employee_id": str(rule.employee_id) if rule.employee_id else None,
        "threshold_minutes": rule.threshold_minutes,
        "minutes_since_last_seen": minutes_absent,
    }
    body = (
        f"Alert: Staff absence (employee)\n"
        f"Rule: {rule.name}\n"
        f"Threshold: {rule.threshold_minutes} min\n"
        f"Minutes since staff last seen: "
        f"{'never' if minutes_absent is None else minutes_absent}\n"
    )
    ctx = FireContext(
        zone_id=None,
        details=details,
        email_subject=f"[RetailVision] Staff absence — {rule.name}",
        email_body=body,
    )
    return condition_met, ctx
