"""Suppression enforcement — the hard gate every outbound path must pass.
Enforced in code (not just UI) per spec §11.2."""

from dataclasses import dataclass

import app.db as db


@dataclass
class SuppressionResult:
    blocked: bool
    reason: str | None = None


def check(*, workspace_id: str, email: str | None = None,
          phone: str | None = None, company_id: str | None = None) -> SuppressionResult:
    """Returns blocked=True if ANY identifier matches suppression or global block."""
    values: list[tuple[str, str]] = []
    if email:
        values.append(("email", email.lower()))
    if phone:
        values.append(("phone", phone))
    if company_id:
        values.append(("company", company_id))
    if not values:
        return SuppressionResult(blocked=False)

    query = (
        "SELECT scope, value, reason FROM suppression "
        "WHERE workspace_id = %s AND ((scope = 'global') OR (scope = %s AND value = %s) OR (scope = %s AND value = %s) OR (scope = %s AND value = %s)) "
        "LIMIT 1"
    )
    flat: list = [workspace_id]
    for i in range(3):
        scope, value = values[i] if i < len(values) else ("__none__", "__none__")
        flat += [scope, value]

    with db.get_pool().connection() as conn:
        row = conn.execute(query, tuple(flat)).fetchone()

    if row:
        return SuppressionResult(
            blocked=True,
            reason=f"suppressed {row['scope']}:{row['value']} — {row['reason']}",
        )
    return SuppressionResult(blocked=False)


def add(conn, *, workspace_id: str, scope: str, value: str, reason: str,
        source_event: str | None = None) -> None:
    conn.execute(
        """INSERT INTO suppression (workspace_id, scope, value, reason, source_event)
           VALUES (%s,%s,%s,%s,%s)
           ON CONFLICT (workspace_id, scope, value) DO NOTHING""",
        (workspace_id, scope, value.lower() if scope == "email" else value, reason, source_event),
    )


def is_opted_out(conn, lead_id: str) -> bool:
    row = conn.execute(
        """SELECT c.opt_out_flag FROM leads l
           JOIN contacts c ON c.id = l.contact_id
           WHERE l.id = %s""",
        (lead_id,),
    ).fetchone()
    return bool(row and row[0])
