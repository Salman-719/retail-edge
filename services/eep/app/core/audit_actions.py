"""Canonical set of valid audit-log actions — the single source of truth.

`audit_logs.action` is a plain ``VARCHAR(50)`` at the DB level (no ``CHECK`` enum).
The set of permitted actions is enforced in the application by
:func:`app.core.audit.write_audit_log`, which validates against ``AUDIT_ACTIONS``
below and raises ``ValueError`` for anything unregistered.

Adding a new audited action is a one-line edit here — never a migration, never a
production 500 from a forgotten DB enum. A drift-guard unit test
(``tests/unit/eep/test_audit_actions.py``) statically scans the routers and core
for ``write_audit_log(...)`` call sites and asserts every emitted action is a
member of this set.

Conventions for new actions: ``snake_case``, ``<= 50`` chars, aligned with the
row's ``entity_type``. No spaces, no caps.
"""

AUDIT_ACTIONS: frozenset[str] = frozenset(
    {
        # Auth & access
        "login",
        "logout",
        "password_reset",
        "permission_changed",
        # Stores
        "store_created",
        "store_updated",
        "store_deleted",
        # Config / versioning
        "config_edited",
        "version_activated",
        "version_rolled_back",
        # Drafts
        "draft_created",
        "draft_discarded",
        "draft_expired",
        # Members
        "member_invited",
        "member_removed",
        "member_role_changed",
        # Employees
        "employee_created",
        "employee_updated",
        "employee_deleted",
        # Shifts — instances
        "shift_created",
        "shift_updated",
        "shift_deleted",
        # Shifts — patterns / assignments / attendance / breaks
        "shift_pattern_created",
        "shift_pattern_updated",
        "shift_pattern_deleted",
        "shift_employee_assigned",
        "shift_attendance_updated",
        "break_created",
    }
)
