"""Cooldown state machine: idle -> firing -> cooldown -> idle.

alert_state drives all cooldown decisions; one row per rule, upserted every
cycle by the evaluator. This module mutates the in-memory AlertState and
performs the side effects (insert alert rows, send the first-FIRING email,
auto-resolve on clear). Email is sent ONLY on the first FIRING transition —
never on followups, cooldown, or resolution.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from app.metrics import IEP4_ALERTS_FIRED, IEP4_EMAILS
from app.models import AlertRule, AlertState

logger = logging.getLogger(__name__)


@dataclass
class FireContext:
    """What an alert needs when it fires: the row payload + the email body."""
    zone_id:       uuid.UUID | None
    details:       dict
    email_subject: str
    email_body:    str
    recipients:    list[str] = field(default_factory=list)


class CooldownMachine:
    def __init__(self, repo, delivery) -> None:
        self._repo = repo
        self._delivery = delivery

    async def step(
        self,
        rule: AlertRule,
        state: AlertState,
        condition_met: bool,
        now_ms: int,
        ctx: FireContext,
    ) -> AlertState:
        threshold_ms = rule.threshold_minutes * 60_000
        cooldown_ms  = rule.cooldown_minutes * 60_000
        followup_ms  = rule.followup_interval_minutes * 60_000

        if state.status == "idle":
            if not condition_met:
                state.condition_first_met_at = None
            else:
                if state.condition_first_met_at is None:
                    state.condition_first_met_at = now_ms
                elif now_ms - state.condition_first_met_at >= threshold_ms:
                    await self._fire(rule, state, now_ms, ctx, send_email=True)

        elif state.status == "firing":
            if condition_met:
                if state.last_followup_at is None or (now_ms - state.last_followup_at) >= followup_ms:
                    await self._repo.insert_alert(
                        rule_type=rule.type, zone_id=ctx.zone_id,
                        details={**ctx.details, "followup": True},
                        alert_rule_id=rule.id, is_followup=True,
                        severity=rule.severity,
                    )
                    state.last_followup_at = now_ms
            else:
                await self._resolve(rule, state, now_ms, cooldown_ms)

        elif state.status == "cooldown":
            if condition_met and now_ms >= (state.cooldown_until or 0):
                await self._fire(rule, state, now_ms, ctx, send_email=True)
            elif not condition_met and now_ms >= (state.cooldown_until or 0):
                self._reset(state)
            # else: condition met but still cooling, or clear but still cooling —
            # stay in cooldown.

        state.last_evaluated_at = now_ms
        return state

    async def _fire(self, rule, state, now_ms, ctx, send_email: bool) -> None:
        await self._repo.insert_alert(
            rule_type=rule.type, zone_id=ctx.zone_id,
            details=ctx.details, alert_rule_id=rule.id, is_followup=False,
            severity=rule.severity,
        )
        state.status = "firing"
        state.fired_at = now_ms
        state.last_followup_at = now_ms
        state.condition_cleared_at = None
        state.cooldown_until = None
        IEP4_ALERTS_FIRED.labels(rule_type=rule.type).inc()
        logger.info("Alert FIRING rule=%s (%s) name=%s", rule.id, rule.type, rule.name)
        if send_email and ctx.recipients:
            try:
                await self._delivery.send(ctx.recipients, ctx.email_subject, ctx.email_body)
                IEP4_EMAILS.labels(outcome="sent").inc()
            except Exception:
                IEP4_EMAILS.labels(outcome="failed").inc()
                logger.exception("Alert email delivery failed rule=%s", rule.id)

    async def _resolve(self, rule, state, now_ms, cooldown_ms: int) -> None:
        n = await self._repo.resolve_alerts_for_rule(rule.id)
        state.condition_cleared_at = now_ms
        state.cooldown_until = now_ms + cooldown_ms
        state.status = "cooldown"
        logger.info("Alert RESOLVED rule=%s — %d row(s) auto-resolved", rule.id, n)

    def _reset(self, state: AlertState) -> None:
        state.status = "idle"
        state.condition_first_met_at = None
        state.fired_at = None
        state.condition_cleared_at = None
        state.cooldown_until = None
        state.last_followup_at = None
