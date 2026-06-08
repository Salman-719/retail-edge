"""Alert evaluation orchestrator.

Runs every cycle AFTER active_person_state is fully updated. Loads active rules
and their state, evaluates each in fixed order (queue_buildup,
staff_absence_zone, staff_absence_employee), drives the cooldown machine, and
upserts the resulting alert_state. All rules are evaluated every cycle.
"""
from __future__ import annotations

import logging

from app.alerts import queue_buildup, staff_employee, staff_zone
from app.alerts.cooldown import CooldownMachine
from app.models import AlertState

logger = logging.getLogger(__name__)

_EVALUATORS = {
    "queue_buildup":          queue_buildup.evaluate,
    "staff_absence_zone":     staff_zone.evaluate,
    "staff_absence_employee": staff_employee.evaluate,
}
_ORDER = {"queue_buildup": 0, "staff_absence_zone": 1, "staff_absence_employee": 2}


class AlertEvaluator:
    def __init__(self, repo, settings, delivery) -> None:
        self._repo = repo
        self._settings = settings
        self._machine = CooldownMachine(repo, delivery)

    async def run(self, now_ms: int) -> None:
        rules = await self._repo.load_rules()
        if not rules:
            return
        rules.sort(key=lambda r: _ORDER.get(r.type, 99))

        states = await self._repo.load_alert_states([r.id for r in rules])
        recipients: list[str] | None = None

        for rule in rules:
            fn = _EVALUATORS.get(rule.type)
            if fn is None:
                continue
            result = await fn(self._repo, rule, now_ms)
            if result is None:
                continue  # rule skipped this cycle (e.g. employee off-shift)

            condition_met, ctx = result
            state = states.get(rule.id) or AlertState()

            if recipients is None:
                recipients = await self._repo.get_recipients()
            ctx.recipients = recipients

            await self._machine.step(rule, state, condition_met, now_ms, ctx)
            await self._repo.upsert_alert_state(rule.id, state)
