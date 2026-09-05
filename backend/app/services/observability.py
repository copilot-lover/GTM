"""
Observability — make GTM decisions explainable after the fact (Phase 12).
For important transitions record enough to answer:
 WHAT HAPPENED? WHY? WHAT INFO AVAILABLE? WHAT DECISION? WHAT NEXT?

Structured decision evidence, not hidden chain-of-thought.
"""

from dataclasses import dataclass, asdict
import json
import psycopg
import app.db as db


@dataclass
class DecisionRecord:
    what_happened: str
    why: str
    info_available: dict
    decision: str
    what_next: str
    confidence: float | None = None
    evidence_refs: list | None = None


def record_decision(workspace_id: str, _entity_type: str, entity_id: str,
                    record: DecisionRecord, actor: str = "system") -> dict:
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        row = conn.execute(
            """INSERT INTO activities (workspace_id, lead_id, type, summary, actor, payload_json)
               VALUES (%s, %s, 'system', %s, %s, %s) RETURNING id""",
            (workspace_id, entity_id, f"DECISION: {record.what_happened} → {record.decision} (why: {record.why})",
             actor, json.dumps(asdict(record))),
        ).fetchone()
    return dict(row) if row else {}


def explain_lead(workspace_id: str, lead_id: str) -> dict:
    """Return explainable snapshot for a lead: current state, why, evidence, next."""
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        lead = conn.execute("SELECT * FROM leads WHERE id=%s AND workspace_id=%s", (lead_id, workspace_id)).fetchone()
        if not lead:
            return {"error": "lead not found"}
        activities = conn.execute(
            "SELECT type, summary, actor, created_at FROM activities WHERE lead_id=%s ORDER BY created_at DESC LIMIT 20",
            (lead_id,)
        ).fetchall()
        scores = conn.execute(
            "SELECT score_type, score, components FROM scores WHERE lead_id=%s ORDER BY created_at DESC LIMIT 5",
            (lead_id,)
        ).fetchall()
        messages = conn.execute(
            "SELECT id, gtm_stage, status, subject FROM messages WHERE lead_id=%s ORDER BY created_at DESC LIMIT 10",
            (lead_id,)
        ).fetchall()
    return {
        "what_happened": f"Lead {lead['business_name'] if lead.get('business_name') else lead_id} currently {lead['status']}",
        "why": f"fit_status={lead.get('fit_status')} lead_score={lead.get('lead_score')} priority={lead.get('priority_score')}",
        "info_available": {"lead": dict(lead), "scores": [dict(s) for s in scores]},
        "decision": f"status={lead['status']}",
        "what_next": "see activities + outbound_gate for next authorized step",
        "evidence": {"activities": [dict(a) for a in activities], "messages": [dict(m) for m in messages]},
    }
