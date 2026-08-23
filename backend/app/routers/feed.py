import json

from fastapi import APIRouter, Depends
from psycopg.rows import dict_row

import app.db as db
from app.core.deps import audit, require_workspace

router = APIRouter(prefix="/feed", tags=["feed"])


@router.get("")
def feed(user: dict = Depends(require_workspace)):
    """Agent activity feed in the GTM style: one row per recent play."""
    ws = user["workspace_id"]
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        rows = conn.execute(
            """SELECT a.summary, a.type, a.actor, a.created_at,
                      l.id AS lead_id, l.status, l.priority_score,
                      l.recommended_offer, c.business_name, c.city, c.state
               FROM activities a
               JOIN leads l ON l.id = a.lead_id
               JOIN companies c ON c.id = l.company_id
               WHERE a.workspace_id = %s
               ORDER BY a.created_at DESC
               LIMIT 40""",
            (ws,),
        ).fetchall()
        total_leads = conn.execute(
            """SELECT count(*) AS n FROM leads
               WHERE workspace_id=%s AND status NOT IN
                 ('rejected','do_not_call','archived')""",
            (ws,),
        ).fetchone()["n"]
    return {"total_plays": total_leads, "items": rows}


@router.post("/seed-demo", status_code=201)
def seed_demo(user: dict = Depends(require_workspace)):
    """Fill the current workspace with a realistic demo batch so the operator
    can see the system's shape before wiring real sources."""
    ws = user["workspace_id"]
    demo = [
        ("Kernersville Plumbing Co", "plumbing", "Kernersville", "NC",
         "qualified", 78, "P2", "no_online_booking", "after_hours_booking",
         "Sourcing leads", 0.004),
        ("Triad Heating & Air", "hvac", "Greensboro", "NC",
         "contacted", 91, "P1", "after_hours_missed_calls", "ai_receptionist",
         "Writing the opener", 0.011),
        ("High Point Electric LLC", "electrical", "High Point", "NC",
         "responded", 88, "P1", "missed_calls", "missed_call_recovery",
         "Waiting on reply · last send 6h ago", 0.008),
        ("Winston-Salem Roofing", "roofing", "Winston-Salem", "NC",
         "outreach_ready", 74, "P2", "no_follow_up", "follow_up_automation",
         "Draft awaiting approval", 0.006),
        ("Battleground Plumbing", "plumbing", "Greensboro", "NC",
         "meeting_booked", 95, "P1", "overwhelmed_front_desk", "ai_receptionist",
         "Meeting Thursday 10am", 0.014),
        ("Salem Mechanical", "hvac", "Winston-Salem", "NC",
         "qualified", 69, "P3", "weak_cta", "website_conversion",
         "Qualifying ICP fit", 0.003),
        ("Oak Ridge Electric", "electrical", "Oak Ridge", "NC",
         "rejected", 31, None, None, None,
         "Rejected: franchise signals", 0.002),
        ("Piedmont Comfort Systems", "hvac", "Greensboro", "NC",
         "contacted", 82, "P2", "manual_scheduling", "appointment_scheduling",
         "Cadence day-3 follow-up", 0.005),
    ]
    seeded = 0
    with db.get_pool().connection() as conn:
        conn.row_factory = dict_row
        for (name, vertical, city, state, status, pri, tier, pain, offer,
             stage_label, cost) in demo:
            row = conn.execute(
                """INSERT INTO companies (workspace_id, business_name, city,
                       state, vertical, phone, source)
                   VALUES (%s,%s,%s,%s,%s,%s,'demo')
                   ON CONFLICT (workspace_id, lower(business_name),
                                coalesce(city,''), coalesce(state,''))
                   DO UPDATE SET updated_at=now() RETURNING id""",
                (ws, name, city, state, vertical, f"+1336555{1000 + seeded}"),
            ).fetchone()
            company_id = str(row["id"])
            lead = conn.execute(
                """INSERT INTO leads (workspace_id, company_id, status,
                       priority_score, primary_pain, recommended_offer, source)
                   VALUES (%s,%s,%s,%s,%s,%s,'demo')
                   RETURNING id""",
                (ws, company_id, status, pri, pain, offer),
            ).fetchone()
            lead_id = str(lead["id"])
            conn.execute(
                """INSERT INTO activities (workspace_id, lead_id, type, summary,
                       actor, payload)
                   VALUES (%s,%s,'ai_action',%s,'agent',%s)""",
                (ws, lead_id, stage_label,
                 json.dumps({"demo": True, "cost_usd": cost})),
            )
            conn.execute(
                """INSERT INTO agent_runs (workspace_id, agent_name, trigger,
                       status, cost_usd, latency_ms, finished_at)
                   VALUES (%s,'pipeline_demo','demo_batch','success',%s,840, now())""",
                (ws, cost),
            )
            seeded += 1
        audit(
            conn,
            actor_type="user",
            actor_id=str(user["id"]),
            action="seed_demo",
            entity="workspace",
            entity_id=ws,
            workspace_id=ws,
        )
    return {"seeded": seeded}
