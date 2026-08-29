"""Explicit agent boundaries enforced in code.

Each GTM agent declares what it may read/write and whether it may send.
Every send-capable gate must go through ``assert_can_send``; QA decisions
must never be produced by the same agent that produced the artifact under
review (``assert_not_self_approval``).
"""

import psycopg.rows

import app.db as db

AGENTS: dict[str, dict] = {
    "GTM_LEADS": {
        "capabilities": {"read_prospects", "write_qualification", "write_contacts"},
        "cannot_send": True,
    },
    "GTM_INTENT": {
        "capabilities": {"read_signals", "write_scores"},
        "cannot_send": True,
    },
    "GTM_COPY": {
        "capabilities": {"read_research", "write_drafts"},
        "cannot_send": True,
    },
    "GTM_QA": {
        "capabilities": {"read_all", "write_qa_decisions"},
        "cannot_send": True,
        "cannot_self_approve": True,
    },
    "GTM_OUTBOUND": {
        "capabilities": {"read_approved_only", "schedule_send"},
        "cannot_send": False,
    },
    "GTM_REPLIES": {
        "capabilities": {"read_inbound", "write_conversation_state"},
        "cannot_send": True,
    },
}


class PermissionDenied(Exception):
    """Raised when an agent attempts an action outside its declared boundaries."""


def _get(agent: str) -> dict:
    entry = AGENTS.get(agent)
    if entry is None:
        raise PermissionDenied(f"unknown agent: {agent}")
    return entry


def ensure_registered() -> None:
    """Seed the agents table with the known GTM agents (idempotent)."""
    with db.get_pool().connection() as conn:
        for name in AGENTS:
            conn.execute(
                """INSERT INTO agents (name) VALUES (%s)
                   ON CONFLICT (name) DO NOTHING""",
                (name,),
            )


def assert_capability(agent: str, capability: str) -> None:
    """Raise PermissionDenied unless the agent declares this capability."""
    entry = _get(agent)
    if capability not in entry["capabilities"]:
        raise PermissionDenied(
            f"{agent} lacks capability '{capability}' "
            f"(has: {sorted(entry['capabilities'])})"
        )


def assert_can_send(agent: str) -> None:
    """Raise PermissionDenied if the agent is barred from sending."""
    entry = _get(agent)
    if entry.get("cannot_send"):
        raise PermissionDenied(f"{agent} is not permitted to send")


def assert_not_self_approval(agent: str, produced_by: str) -> None:
    """QA may never approve an artifact it produced itself."""
    entry = _get(agent)
    if entry.get("cannot_self_approve") and agent == produced_by:
        raise PermissionDenied(f"{agent} cannot self-approve its own artifacts")
