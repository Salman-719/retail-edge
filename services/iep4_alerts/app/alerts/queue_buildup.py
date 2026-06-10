"""queue_buildup evaluator.

Counts non-employees who have dwelled in ANY of the rule's zones for at least
threshold_minutes. Condition met when that count >= people_threshold.
"""
from __future__ import annotations

from app.alerts.cooldown import FireContext
from app.models import AlertRule


async def evaluate(repo, rule: AlertRule, now_ms: int) -> tuple[bool, FireContext]:
    threshold_ms = rule.threshold_minutes * 60_000
    count = await repo.count_queue_buildup(rule.zone_ids, threshold_ms)
    condition_met = rule.people_threshold is not None and count >= rule.people_threshold

    zone_names = list((await repo.get_zone_names(rule.zone_ids)).values())
    details = {
        "rule": rule.name,
        "type": rule.type,
        "count": count,
        "people_threshold": rule.people_threshold,
        "threshold_minutes": rule.threshold_minutes,
        "zones": zone_names,
    }
    body = (
        f"Alert: Queue buildup\n"
        f"Rule: {rule.name}\n"
        f"Zones: {', '.join(zone_names) or '(none)'}\n"
        f"People waiting >= {rule.threshold_minutes} min: {count} "
        f"(threshold {rule.people_threshold})\n"
    )
    ctx = FireContext(
        zone_id=rule.zone_ids[0] if rule.zone_ids else None,
        details=details,
        email_subject=f"[RetailVision] Queue buildup — {rule.name}",
        email_body=body,
    )
    return condition_met, ctx
