"""IEP3 — Alerts & Rule Engine.

Evaluates rule conditions on tracking events and emits alerts.
Stub endpoints — logic will be implemented in Milestone 3.
"""
import uuid
from datetime import datetime
from typing import List

from fastapi import FastAPI, HTTPException, Path

from app.schemas import (
    AlertRuleCreate, AlertRule,
    TrackingEvent, AlertResult,
    Alert, AlertUpdate,
    HealthResponse,
)

app = FastAPI(
    title="RetailVision IEP3 — Alerts",
    version="0.1.0",
    description="Evaluates rule conditions on tracking events and emits alerts.",
)

# ── In-memory store (replaced by DB in Milestone 3) ─────────────────────────
_rules: dict[str, AlertRule] = {}
_alerts: dict[str, Alert] = {}


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse()


# ── Rules CRUD ───────────────────────────────────────────────────────────────

@app.post("/alerts/rules", response_model=AlertRule)
async def create_rule(payload: AlertRuleCreate):
    rule = AlertRule(
        **payload.model_dump(),
        id=uuid.uuid4().hex,
        created_at=datetime.utcnow(),
    )
    _rules[rule.id] = rule
    return rule


@app.get("/alerts/rules", response_model=List[AlertRule])
async def list_rules(store_id: str | None = None):
    rules = list(_rules.values())
    if store_id:
        rules = [r for r in rules if r.store_id == store_id]
    return rules


@app.delete("/alerts/rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: str = Path(...)):
    if rule_id not in _rules:
        raise HTTPException(404, "Rule not found")
    del _rules[rule_id]


# ── Evaluation ───────────────────────────────────────────────────────────────

@app.post("/alerts/evaluate", response_model=List[AlertResult])
async def evaluate(event: TrackingEvent):
    """Evaluate all enabled rules against a tracking event.
    Stub — returns empty list until rule engine is implemented."""
    results: List[AlertResult] = []
    # TODO: iterate _rules, check conditions, emit AlertResults
    return results


# ── Alerts ───────────────────────────────────────────────────────────────────

@app.get("/alerts/{store_id}", response_model=List[Alert])
async def list_alerts(store_id: str):
    return [a for a in _alerts.values() if a.store_id == store_id]


@app.patch("/alerts/{alert_id}", response_model=Alert)
async def update_alert(alert_id: str, payload: AlertUpdate):
    if alert_id not in _alerts:
        raise HTTPException(404, "Alert not found")
    alert = _alerts[alert_id]
    if payload.status:
        alert.status = payload.status
    _alerts[alert_id] = alert
    return alert
