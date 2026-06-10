"""staff_absence_employee evaluator.

Condition met when the targeted employee has not been seen for threshold_minutes
(or is absent entirely). When only_during_shift is TRUE and the employee has no
shift_instance with status='active' covering now, the rule is SKIPPED.

Presence is looked up via active_person_state.employee_id when rule.employee_id
is set (specific employee, requires the punch-in link to have fired for that
person). Falls back to any-staff presence when rule.employee_id is None.
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
    if rule.employee_id is not None:
        last_seen = await repo.latest_presence_for_employee(rule.employee_id)
    else:
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
