"""staff_absence_zone evaluator.

Counts employees currently in ANY of the rule's zones. Condition met when that
count < min_employees (a zone is understaffed).
"""
from __future__ import annotations

from app.alerts.cooldown import FireContext
from app.models import AlertRule


async def evaluate(repo, rule: AlertRule, now_ms: int) -> tuple[bool, FireContext]:
    count = await repo.count_staff_in_zones(rule.zone_ids)
    condition_met = rule.min_employees is not None and count < rule.min_employees

    zone_names = list((await repo.get_zone_names(rule.zone_ids)).values())
    details = {
        "rule": rule.name,
        "type": rule.type,
        "employees_present": count,
        "min_employees": rule.min_employees,
        "zones": zone_names,
    }
    body = (
        f"Alert: Staff absence (zone)\n"
        f"Rule: {rule.name}\n"
        f"Zones: {', '.join(zone_names) or '(none)'}\n"
        f"Employees present: {count} (minimum {rule.min_employees})\n"
    )
    ctx = FireContext(
        zone_id=rule.zone_ids[0] if rule.zone_ids else None,
        details=details,
        email_subject=f"[RetailVision] Staff absence — {rule.name}",
        email_body=body,
    )
    return condition_met, ctx
