"""GlobalID state machine & cleanup (IEP3 spec §6). Runs after Process 2.

LOST -> ACTIVE re-entry is handled inside Process 1 (``reactivate_if_lost``),
not here.
"""

from __future__ import annotations

from sqlalchemy import text


class StateManager:
    def __init__(self, repo, settings):
        self._repo, self._s = repo, settings

    async def run_cleanup(self, session, batch: int) -> dict:
        # ACTIVE -> LOST: no active linked LocalID seen this batch
        await session.execute(
            text(
                """
                UPDATE global_identities gi
                SET state = 'lost', lost_since_batch = :batch
                WHERE gi.state = 'active'
                  AND NOT EXISTS (
                      SELECT 1 FROM global_local_mapping glm
                      WHERE glm.global_id = gi.global_id
                        AND glm.is_active = TRUE
                        AND glm.last_seen_batch = :batch)
                """
            ),
            {"batch": batch},
        )

        # LOST -> EXITED: grace period elapsed
        exited = await session.execute(
            text(
                """
                UPDATE global_identities
                SET state = 'exited'
                WHERE state = 'lost'
                  AND (:batch - lost_since_batch) >= :grace
                RETURNING global_id
                """
            ),
            {"batch": batch, "grace": self._s.global_grace_batches},
        )
        exited_ids = [r.global_id for r in exited]

        if exited_ids:
            await session.execute(
                text(
                    """
                    UPDATE global_local_mapping
                    SET is_active = FALSE, unlinked_at_batch = :batch
                    WHERE global_id = ANY(:ids) AND is_active = TRUE
                    """
                ),
                {"batch": batch, "ids": exited_ids},
            )

        return {"exited": len(exited_ids)}
