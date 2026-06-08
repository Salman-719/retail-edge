"""Allow 'eep_restart' in camera_runtime_sessions.stop_reason CHECK.

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-08

EEP's startup _close_orphan_sessions() closes leftover open sessions with
stop_reason='eep_restart', but the original CHECK constraint omitted that value,
so the cleanup UPDATE raised CheckViolationError (caught + logged, leaving
orphan sessions open). Add 'eep_restart' to the allowed set. Idempotent.
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE camera_runtime_sessions
            DROP CONSTRAINT IF EXISTS camera_runtime_sessions_stop_reason_check;
        ALTER TABLE camera_runtime_sessions
            ADD CONSTRAINT camera_runtime_sessions_stop_reason_check
            CHECK (stop_reason IN (
                'schedule', 'manual', 'version_activation',
                'eep_restart', 'crash', 'unknown'
            ));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE camera_runtime_sessions
            DROP CONSTRAINT IF EXISTS camera_runtime_sessions_stop_reason_check;
        ALTER TABLE camera_runtime_sessions
            ADD CONSTRAINT camera_runtime_sessions_stop_reason_check
            CHECK (stop_reason IN (
                'schedule', 'manual', 'version_activation', 'crash', 'unknown'
            ));
        """
    )
