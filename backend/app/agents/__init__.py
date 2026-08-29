"""GTM agent package: explicit capability boundaries, run ledger, scheduled runner."""

from app.agents.ledger import (
    agent_health,
    complete_run,
    record_run,
    tracked_run,
)
from app.agents.registry import (
    AGENTS,
    PermissionDenied,
    assert_can_send,
    assert_capability,
    assert_not_self_approval,
    ensure_registered,
)

__all__ = [
    "AGENTS",
    "PermissionDenied",
    "assert_can_send",
    "assert_capability",
    "assert_not_self_approval",
    "ensure_registered",
    "agent_health",
    "complete_run",
    "record_run",
    "tracked_run",
]
