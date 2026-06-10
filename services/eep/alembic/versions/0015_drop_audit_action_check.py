"""Drop the audit_logs.action CHECK enum; validate in app instead.

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-09

audit_logs.action carried a hand-maintained CHECK (action IN (...)) enum. The
code already emitted 7 actions absent from that list (store_deleted, the four
shift_pattern_* / shift_employee_assigned / shift_attendance_updated, and
break_created), so each of those endpoints raised CheckViolationError on the
audit insert and rolled back the whole business transaction.

Rather than widen the enum again (cf. 0012, which widened a *different* CHECK for
the same class of bug), the action set becomes a single Python source of truth
(app/core/audit_actions.py :: AUDIT_ACTIONS), enforced at write time by
write_audit_log() and guarded by a drift test. Forward-only; no data migration.

upgrade(): drop the constraint (idempotent — safe whether or not it exists).
downgrade(): faithfully re-add the ORIGINAL 21-action enum only (the pre-0015
state), NOT the actions this fix unblocks.
"""
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE audit_logs
            DROP CONSTRAINT IF EXISTS audit_logs_action_check;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE audit_logs
            DROP CONSTRAINT IF EXISTS audit_logs_action_check;
        ALTER TABLE audit_logs
            ADD CONSTRAINT audit_logs_action_check
            CHECK (action IN (
                'login', 'logout',
                'config_edited', 'version_activated', 'version_rolled_back',
                'member_invited', 'member_removed', 'member_role_changed',
                'permission_changed', 'password_reset',
                'employee_created', 'employee_updated', 'employee_deleted',
                'shift_created', 'shift_updated', 'shift_deleted',
                'store_created', 'store_updated',
                'draft_created', 'draft_discarded', 'draft_expired'
            ));
        """
    )
