"""GTM message lifecycle stage machine (migration 0008).

Every managed outbound message walks DISCOVERED → … → SENT through here;
no direct gtm_stage writes elsewhere. Legacy rows keep gtm_stage NULL and
are invisible to this machine.
"""

import psycopg.rows

import app.db as db

STAGES = (
    'DISCOVERED', 'QUALIFIED', 'INTENT_SCORED', 'RESEARCHED', 'COPY_GENERATED',
    'QA_PENDING', 'QA_PASSED', 'COMPLIANCE_PENDING', 'SEND_READY', 'SCHEDULED',
    'SENT', 'QA_FAILED', 'COMPLIANCE_FAILED', 'SUPPRESSED', 'HELD', 'EXPIRED',
    'CANCELLED',
)

# Only stages from which the sender (email_service) may claim a message.
AUTHORIZED_SEND_STAGES = ('SEND_READY', 'SCHEDULED')

FAILURE_STAGES = (
    'QA_FAILED', 'COMPLIANCE_FAILED', 'SUPPRESSED', 'HELD', 'EXPIRED', 'CANCELLED',
)


class InvalidTransition(Exception):
    pass


TRANSITIONS: dict[str, set[str]] = {
    'DISCOVERED': {'QUALIFIED'},
    'QUALIFIED': {'INTENT_SCORED'},
    'INTENT_SCORED': {'RESEARCHED'},
    'RESEARCHED': {'COPY_GENERATED'},
    'COPY_GENERATED': {'QA_PENDING'},
    'QA_PENDING': {'QA_PASSED', 'QA_FAILED', 'HELD', 'CANCELLED'},
    'QA_FAILED': {'COPY_GENERATED', 'HELD', 'CANCELLED'},
    'QA_PASSED': {'COMPLIANCE_PENDING', 'CANCELLED'},
    'COMPLIANCE_PENDING': {'SEND_READY', 'COMPLIANCE_FAILED', 'SUPPRESSED',
                           'HELD', 'CANCELLED'},
    'COMPLIANCE_FAILED': {'COPY_GENERATED', 'SUPPRESSED', 'HELD', 'CANCELLED'},
    'SEND_READY': {'SCHEDULED', 'HELD', 'EXPIRED', 'SUPPRESSED', 'CANCELLED'},
    'SCHEDULED': {'SENT', 'HELD', 'EXPIRED', 'SUPPRESSED', 'CANCELLED'},
    'SENT': set(),
    'HELD': {'QA_PENDING', 'CANCELLED', 'EXPIRED'},
    'SUPPRESSED': set(),
    'EXPIRED': set(),
    'CANCELLED': set(),
}


def can_transition(from_stage: str | None, to_stage: str) -> bool:
    if from_stage is None:
        return to_stage in STAGES  # initial enrollment of a managed row
    return to_stage in TRANSITIONS.get(from_stage, set())


def transition_message(workspace_id: str, message_id: str, to_stage: str,
                       actor: str = 'system', reason: str | None = None,
                       conn=None, qa_run_id: str | None = None) -> dict:
    """Guarded optimistic stage move + observable event row.

    Pass conn to compose atomically with the caller's transaction; otherwise
    a pool connection is opened. Raises InvalidTransition on illegal hops,
    unknown stages, concurrent modification, or missing messages.
    """
    if to_stage not in STAGES:
        raise InvalidTransition(f"unknown stage {to_stage!r}")

    def _run(c):
        c.row_factory = psycopg.rows.dict_row
        row = c.execute(
            "SELECT gtm_stage FROM messages WHERE id=%s AND workspace_id=%s",
            (message_id, workspace_id),
        ).fetchone()
        if row is None:
            raise InvalidTransition("message not found")
        current = row["gtm_stage"]
        if not can_transition(current, to_stage):
            raise InvalidTransition(
                f"invalid stage transition {current} -> {to_stage}")
        updated = c.execute(
            """UPDATE messages SET gtm_stage=%s
               WHERE id=%s AND workspace_id=%s
                 AND (gtm_stage IS NOT DISTINCT FROM %s)
               RETURNING id""",
            (to_stage, message_id, workspace_id, current),
        ).fetchone()
        if updated is None:
            raise InvalidTransition(
                f"concurrent stage change while moving to {to_stage}")
        c.execute(
            """INSERT INTO message_stage_events
                   (workspace_id, message_id, from_stage, to_stage, actor,
                    reason, qa_run_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (workspace_id, message_id, current, to_stage, actor, reason,
             qa_run_id),
        )
        return {"message_id": str(message_id), "from_stage": current,
                "to_stage": to_stage, "actor": actor, "reason": reason,
                "qa_run_id": qa_run_id}

    if conn is not None:
        return _run(conn)
    with db.get_pool().connection() as own:
        return _run(own)


def stage_history(workspace_id: str, message_id: str) -> list[dict]:
    """All stage events for a message, oldest first."""
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        rows = conn.execute(
            """SELECT id, message_id, from_stage, to_stage, actor, reason,
                      qa_run_id, created_at
               FROM message_stage_events
               WHERE workspace_id=%s AND message_id=%s
               ORDER BY created_at, id""",
            (workspace_id, message_id),
        ).fetchall()
    return list(rows)
