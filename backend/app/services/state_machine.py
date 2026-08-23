"""Lead state machine — the single coordination backbone (spec §6.4).
Every agent/workflow must transition leads through here; no direct status writes."""

from fastapi import HTTPException

TRANSITIONS: dict[str, set[str]] = {
    "new": {"enriching", "rejected"},
    "enriching": {"qualified", "signal_holding", "outreach_ready", "rejected"},
    "qualified": {"signal_holding", "outreach_ready", "contacted", "rejected", "do_not_call"},
    "signal_holding": {"outreach_ready", "qualified", "archived", "expired_rejected"},
    "outreach_ready": {"contacted", "rejected", "do_not_call"},
    "contacted": {"responded", "contacted", "unreachable", "do_not_call", "archived"},
    "responded": {"qualified_conversation", "lost", "archived"},
    "qualified_conversation": {"meeting_booked", "lost"},
    "meeting_booked": {"meeting_held", "meeting_booked", "lost"},
    "meeting_held": {"proposal", "won", "lost"},
    "proposal": {"won", "lost"},
    "won": set(),
    "lost": {"archived"},
    "rejected": set(),
    "do_not_call": set(),
    "unreachable": {"archived"},
    "archived": set(),
}


# Hard compliance override: a do_not_call decision is valid from any
# non-terminal state (suppression happens immediately everywhere).
for _s, _targets in TRANSITIONS.items():
    if _s not in ("won", "rejected", "do_not_call", "archived"):
        _targets.add("do_not_call")

TERMINAL = {s for s, nxt in TRANSITIONS.items() if not nxt}


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, set())


def transition(conn, lead_id: str, workspace_id: str, current: str, target: str) -> bool:
    """Optimistic guarded transition. Returns True if applied."""
    if not can_transition(current, target):
        raise HTTPException(
            409,
            f"invalid lead transition {current} -> {target}",
        )
    cur = conn.execute(
        """UPDATE leads SET status = %s, updated_at = now()
           WHERE id = %s AND workspace_id = %s AND status = %s
           RETURNING id""",
        (target, lead_id, workspace_id, current),
    )
    return cur.fetchone() is not None
