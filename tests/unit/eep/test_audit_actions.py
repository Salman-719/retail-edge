"""Drift guard for audit-log actions (pure, no DB).

Statically scans every ``write_audit_log(...)`` call site in the EEP routers and
core and asserts the emitted action string is registered in
``app.core.audit_actions.AUDIT_ACTIONS``.

This converts "someone added an audited action but forgot to register it" from a
production 500 (``CheckViolationError`` rolling back the business transaction)
into a failing unit test. See spec B1.

It also enforces that every call passes the action as a string literal — no
dynamic actions — which is what makes static validation sound.
"""
import ast
import os
import sys

import pytest

_EEP_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "services", "eep"
)
sys.path.insert(0, _EEP_DIR)

from app.core.audit_actions import AUDIT_ACTIONS  # noqa: E402

_APP_DIR = os.path.join(_EEP_DIR, "app")
_SCAN_DIRS = [
    os.path.join(_APP_DIR, "api", "routers"),
    os.path.join(_APP_DIR, "core"),
]


def _python_files() -> list[str]:
    files: list[str] = []
    for d in _SCAN_DIRS:
        for entry in sorted(os.listdir(d)):
            if entry.endswith(".py"):
                files.append(os.path.join(d, entry))
    return files


def _extract_action_node(call: ast.Call) -> ast.expr | None:
    """Return the AST node for the ``action`` argument of a write_audit_log call.

    Signature is ``write_audit_log(db, action, ...)`` — action is the 2nd
    positional arg, or the ``action=`` keyword.
    """
    if len(call.args) >= 2:
        return call.args[1]
    for kw in call.keywords:
        if kw.arg == "action":
            return kw.value
    return None


def _collect_call_sites() -> list[tuple[str, int, ast.expr | None]]:
    """Return (file, lineno, action_node) for every write_audit_log call."""
    sites: list[tuple[str, int, ast.expr | None]] = []
    for path in _python_files():
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else None
            )
            if name == "write_audit_log":
                sites.append((path, node.lineno, _extract_action_node(node)))
    return sites


def test_some_call_sites_found():
    """Guard against the scan silently matching nothing (e.g. moved files)."""
    assert _collect_call_sites(), "no write_audit_log call sites found — scan is broken"


def test_all_emitted_actions_are_string_literals():
    """No dynamic actions — static validation must be exhaustive."""
    offenders = [
        f"{os.path.basename(path)}:{lineno}"
        for path, lineno, node in _collect_call_sites()
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str))
    ]
    assert not offenders, (
        "write_audit_log called with a non-literal action (breaks static drift "
        f"validation) at: {', '.join(offenders)}"
    )


def test_all_emitted_actions_are_registered():
    """Every emitted action must be in AUDIT_ACTIONS."""
    unregistered = sorted(
        {
            node.value
            for _, _, node in _collect_call_sites()
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and node.value not in AUDIT_ACTIONS
        }
    )
    assert not unregistered, (
        "audit actions emitted by code but missing from "
        f"app/core/audit_actions.py::AUDIT_ACTIONS: {unregistered}"
    )


@pytest.mark.parametrize("action", sorted(AUDIT_ACTIONS))
def test_registry_entries_are_well_formed(action):
    """snake_case-ish, <= 50 chars, no spaces/caps (matches VARCHAR(50) column)."""
    assert action == action.lower(), f"{action!r} has uppercase"
    assert " " not in action, f"{action!r} has a space"
    assert len(action) <= 50, f"{action!r} exceeds VARCHAR(50)"
