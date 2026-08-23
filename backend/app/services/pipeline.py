"""Six-stage lead intelligence pipeline (spec §5.1, ported from the old
pipeline.py with fail-closed semantics preserved).

Stage flow: qualify -> enrich -> audit -> offer -> personalize.
Hard rules (inherited):
  1. Enrichment and later stages are gated on fit_status == qualified.
  2. Fail-closed: unclear data -> review queue, never a guess.
  3. Evidence text mandatory for qualification/audit/offer decisions.
  4. Recommended offer must address recorded primary pain (deterministic check).
  5. Unverified email can never be sent (enforced in email service).
  6. Nothing is sent without human approval (enforced in email service).
"""

import json
import re

import psycopg.rows
from dns import resolver

import app.db as db
from app.services import llm, scoring


class PipelineError(Exception):
    pass


# ------------------------------------------------------------------ helpers

def _load_lead(workspace_id: str, lead_id: str) -> dict:
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        row = conn.execute(
            """SELECT l.*, c.business_name, c.website, c.phone AS company_phone,
                      c.city, c.state, c.vertical, c.number_of_locations,
                      c.google_rating, c.review_count, c.tech_signals
               FROM leads l JOIN companies c ON c.id = l.company_id
               WHERE l.id=%s AND l.workspace_id=%s""",
            (lead_id, workspace_id),
        ).fetchone()
    if row is None:
        raise PipelineError("lead not found")
    return row


def _update_lead(lead_id: str, fields: dict) -> None:
    sets = ", ".join(f"{k}=%s" for k in fields)
    values = list(fields.values()) + [lead_id]
    with db.get_pool().connection() as conn:
        conn.execute(
            f"UPDATE leads SET {sets}, updated_at=now() WHERE id=%s", tuple(values)
        )


def _add_activity(workspace_id: str, lead_id: str, summary: str, actor: str = "agent",
                  type_: str = "ai_action") -> None:
    with db.get_pool().connection() as conn:
        conn.execute(
            """INSERT INTO activities (workspace_id, lead_id, type, summary, actor)
               VALUES (%s,%s,%s,%s,%s)""",
            (workspace_id, lead_id, type_, summary, actor),
        )


def _flag_review(workspace_id: str, lead_id: str, reason: str) -> None:
    lead = _load_lead(workspace_id, lead_id)
    reasons = list(lead.get("review_reasons") or [])
    if reason not in reasons:
        reasons.append(reason)
    _update_lead(lead_id, {"review_reasons": json.dumps(reasons)})
    _add_activity(workspace_id, lead_id, f"routed to review: {reason}", actor="system")


def _fail_closed(fn):
    """Decorator: pipeline stage failures never guess — they route to review."""
    def wrapper(workspace_id: str, lead_id: str) -> dict:
        try:
            return fn(workspace_id, lead_id)
        except llm.MissingConfiguration as e:
            _flag_review(workspace_id, lead_id, f"stage {fn.__name__} blocked: {e}")
            raise
        except llm.BudgetExceeded:
            _flag_review(workspace_id, lead_id, "daily AI budget exhausted")
            raise
        except llm.ReviewRequired as e:
            _flag_review(workspace_id, lead_id, f"agent output invalid: {e}")
            raise
    wrapper.__name__ = fn.__name__
    return wrapper


# ------------------------------------------------------- stage 1: qualify

QUALIFY_SYSTEM = (
    "You are the Qualification Agent for Orbit, an agency selling AI receptionist / "
    "missed-call recovery / booking automation to small local owner-operated "
    "home-services contractors (plumbers, HVAC, electricians, roofers). "
    "Detect ICP signals from the supplied evidence. Signal keys you may set true: "
    "single_location, owner_visible, family_owned, simple_site, residential_focus, "
    "local_service_area, direct_phone, franchise, multi_location, careers_page, "
    "enterprise_signals, national_brand, multi_state. "
    "Fail closed: if evidence does not clearly support a signal, leave it false and "
    "set unclear=true. Never invent facts."
)

QUALIFY_KEYS = ["signals", "unclear", "evidence", "reason"]


@_fail_closed
def stage_qualify(workspace_id: str, lead_id: str) -> dict:
    lead = _load_lead(workspace_id, lead_id)
    if not lead["business_name"]:
        raise PipelineError("candidate missing business_name")

    user_msg = json.dumps({
        "business_name": lead["business_name"],
        "website": lead["website"],
        "city": lead["city"],
        "state": lead["state"],
        "vertical": lead["vertical"],
        "google_rating": str(lead["google_rating"]),
        "review_count": lead["review_count"],
        "number_of_locations": lead["number_of_locations"],
        "source_evidence": lead.get("evidence", {}).get("source"),
    })

    parsed = llm.structured_complete(
        agent_name="qualification_agent",
        system=QUALIFY_SYSTEM,
        user=user_msg,
        required_keys=QUALIFY_KEYS,
        workspace_id=workspace_id,
    )
    signals = parsed.get("signals") or {}
    score, detail = scoring.icp_fit_score(signals)
    fit_status = scoring.fit_status_for(score, signals, bool(parsed.get("unclear")))
    priority = scoring.priority_score(
        intent=min(1.0, max(0.0, float(parsed.get("intent", 0.3)))),
        fit=score / 10,
        contact_quality=0.6 if lead.get("company_phone") else 0.2,
        history=0.0,
    )

    evidence = {**(lead.get("evidence") or {}),
                "icp_signals": detail,
                "agent_evidence": parsed.get("evidence"),
                "qualification_reason": parsed.get("reason")}
    _update_lead(lead_id, {
        "lead_score": score,
        "fit_status": fit_status,
        "priority_score": priority,
        "evidence": json.dumps(evidence),
        "rejection_reason": parsed.get("reason") if fit_status.startswith("rejected") else None,
    })
    if lead["status"] == "new":
        from app.services import state_machine

        # Spec §6.4: NEW → ENRICHING → QUALIFIED. Rejection short-circuits.
        with db.get_pool().connection() as conn:
            target = "rejected" if fit_status.startswith("rejected") else "enriching"
            state_machine.transition(conn, lead_id, workspace_id, "new", target)
    _add_activity(
        workspace_id, lead_id,
        f"qualified: score {score}/10, fit_status={fit_status}, evidence recorded",
    )
    return {"lead_score": score, "fit_status": fit_status}


# ------------------------------------------------------- stage 2: enrich

ENRICH_SYSTEM = (
    "You are the Enrichment Agent. Extract the owner's name, a public contact email, "
    "and confirm employee size for the given business STRICTLY from provided page "
    "content. If any field cannot be found verbatim in the content, return null for "
    "it — NEVER guess or construct emails. Include source_notes quoting where each "
    "field was found."
)

ENRICH_KEYS = ["owner_name", "email", "employee_estimate", "confidence", "source_notes"]


@_fail_closed
def stage_enrich(workspace_id: str, lead_id: str) -> dict:
    lead = _load_lead(workspace_id, lead_id)
    if lead["fit_status"] != "qualified":
        raise PipelineError("enrichment hard-gated on fit_status == qualified")
    if not lead["website"]:
        _flag_review(workspace_id, lead_id, "no website to enrich from")
        raise PipelineError("no website")

    from app.services.scraping import scrape
    try:
        result = scrape(lead["website"], stealth=True)
    except Exception as e:
        _flag_review(workspace_id, lead_id, f"site fetch failed: {type(e).__name__}")
        raise PipelineError("site fetch failed")

    parsed = llm.structured_complete(
        agent_name="enrichment_agent",
        system=ENRICH_SYSTEM,
        user=json.dumps({
            "business_name": lead["business_name"],
            "page_content": result.body[:12000],
        }),
        required_keys=ENRICH_KEYS,
        workspace_id=workspace_id,
    )
    owner = parsed.get("owner_name")
    email = parsed.get("email")
    confidence = int(parsed.get("confidence", 0))

    review_reasons = []
    if not owner:
        review_reasons.append("owner name not found — human review")
    if not email:
        review_reasons.append("email not found — human review")

    # persist owner on company; create/update contact with email + verification
    with db.get_pool().connection() as conn:
        if owner:
            conn.execute(
                "UPDATE companies SET owner_name=%s, updated_at=now() WHERE id=(SELECT company_id FROM leads WHERE id=%s)",
                (owner, lead_id),
            )
        if email and EMAIL_RE.match(email):
            verify_email(workspace_id, lead_id, email.lower())
        if review_reasons:
            existing = list(lead.get("review_reasons") or [])
            _update_lead(lead_id, {"review_reasons": json.dumps(existing + review_reasons)})
        if confidence:
            conn.execute(
                """UPDATE companies SET owner_operator_confidence=%s, updated_at=now()
                   WHERE id=(SELECT company_id FROM leads WHERE id=%s)""",
                (confidence, lead_id),
            )
    # enrichment complete: ENRICHING → QUALIFIED per §6.4
    if lead["status"] == "enriching":
        from app.services import state_machine

        with db.get_pool().connection() as conn:
            state_machine.transition(conn, lead_id, workspace_id, "enriching", "qualified")
    _add_activity(workspace_id, lead_id,
                  f"enriched: owner={owner!r}, email={'found' if email else 'missing'}")
    return {"owner_name": owner, "email": email, "confidence": confidence}


EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def verify_email(workspace_id: str, lead_id: str, email: str) -> dict:
    """Syntax + DNS gate now; provider verification required before send."""
    status = "failed"
    confidence = 0
    if EMAIL_RE.match(email):
        status = "syntax_ok"
        confidence = 30
        domain = email.split("@")[1]
        try:
            answers = resolver.resolve(domain, "MX")
            if answers:
                status = "dns_ok"
                confidence = 60
        except Exception:
            pass

    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        lead = conn.execute(
            "SELECT contact_id FROM leads WHERE id=%s AND workspace_id=%s",
            (lead_id, workspace_id),
        ).fetchone()
        if lead and lead["contact_id"]:
            # never downgrade a provider-verified contact by re-running syntax/DNS checks
            existing = conn.execute(
                "SELECT email_verification_status FROM contacts WHERE id=%s",
                (str(lead["contact_id"]),),
            ).fetchone()
            if existing and existing["email_verification_status"] == "verified":
                return {"status": "verified", "confidence": None, "unchanged": True}
            conn.execute(
                """UPDATE contacts SET email=%s, email_verification_status=%s,
                   email_verification_confidence=%s, email_verification_provider='syntax_dns',
                   email_verified_at=now() WHERE id=%s""",
                (email, status, confidence, str(lead["contact_id"])),
            )
        elif lead:
            conn.execute(
                """INSERT INTO contacts (workspace_id, company_id, email,
                       email_verification_status, email_verification_confidence,
                       email_verification_provider, email_verified_at)
                   SELECT %s, company_id, %s, %s, %s, 'syntax_dns', now()
                   FROM leads WHERE id=%s""",
                (workspace_id, email, status, confidence, lead_id),
            )
    return {"status": status, "confidence": confidence}


def mark_provider_verified(workspace_id: str, lead_id: str, provider: str, confidence: int = 90) -> dict:
    """Operator/provider confirms deliverability — clears the send gate."""
    with db.get_pool().connection() as conn:
        row = conn.execute(
            """UPDATE contacts SET email_verification_status='verified',
               email_verification_confidence=%s, email_verification_provider=%s,
               email_verified_at=now()
               WHERE id=(SELECT contact_id FROM leads WHERE id=%s AND workspace_id=%s)
               RETURNING id""",
            (confidence, provider, lead_id, workspace_id),
        ).fetchone()
    if row is None:
        raise PipelineError("no contact on lead to verify")
    return {"status": "verified", "provider": provider}


# ------------------------------------------------------- stage 3: website audit

AUDIT_SYSTEM = (
    "You are the Website Audit Agent for home-services contractor sites. From the "
    "supplied homepage HTML/content, detect: has_online_booking, has_chatbot, "
    "mobile_quality (good/poor/unknown), cta_quality (strong/weak/unknown), "
    "after_hours_capture (yes/no/unknown), trust_signals_present, plus concrete "
    "pain_points observed (quote what you saw) and primary_pain/secondary_pain chosen "
    "from pain_points. Evidence must quote observed content. Fail closed: unknown "
    "stays unknown."
)

AUDIT_KEYS = ["findings", "pain_points", "primary_pain", "secondary_pain", "website_score"]

PAIN_TO_OFFER = {
    "no_online_booking": "after_hours_booking",
    "missed_calls": "missed_call_recovery",
    "after_hours_missed_calls": "ai_receptionist",
    "slow_response": "lead_qualification",
    "weak_cta": "website_conversion",
    "poor_mobile": "website_conversion",
    "no_follow_up": "follow_up_automation",
    "few_reviews": "review_generation",
    "manual_scheduling": "appointment_scheduling",
    "overwhelmed_front_desk": "ai_receptionist",
}


@_fail_closed
def stage_audit(workspace_id: str, lead_id: str) -> dict:
    lead = _load_lead(workspace_id, lead_id)
    if not lead["website"]:
        _flag_review(workspace_id, lead_id, "audit skipped: no website")
        raise PipelineError("no website")

    from app.services.scraping import scrape
    try:
        result = scrape(lead["website"])
    except Exception as e:
        _flag_review(workspace_id, lead_id, f"audit fetch failed: {type(e).__name__}")
        raise PipelineError("site fetch failed")

    pagespeed = {}
    findings_block = {
        "homepage_content": result.body[:15000],
        "pagespeed_mobile_score": pagespeed.get("mobile"),
    }
    parsed = llm.structured_complete(
        agent_name="website_audit_agent",
        system=AUDIT_SYSTEM,
        user=json.dumps({"business": lead["business_name"], **findings_block}),
        required_keys=AUDIT_KEYS,
        workspace_id=workspace_id,
    )
    pains = parsed.get("pain_points") or []
    primary = parsed.get("primary_pain")
    if not pains or not primary:
        _flag_review(workspace_id, lead_id, "audit found no concrete pains")
        raise PipelineError("no pains identified")
    if primary not in pains:
        # deterministic consistency check (hard rule 4 precursor)
        _flag_review(workspace_id, lead_id, "primary pain missing from pain_points list")
        raise PipelineError("primary_pain inconsistent")

    _update_lead(lead_id, {
        "website_findings": json.dumps({
            "findings": parsed.get("findings"),
            "pain_points": pains,
            "pagespeed": pagespeed,
        }),
        "primary_pain": primary,
        "secondary_pain": parsed.get("secondary_pain"),
    })
    _add_activity(workspace_id, lead_id, f"audited site: primary pain = {primary}")
    return {"pain_points": pains, "primary_pain": primary}


# ------------------------------------------------------- stage 4: offer selection

OFFER_SYSTEM = (
    "You are the Offer Selection Agent. Choose EXACTLY ONE offer_id for the business "
    "from this catalog based on the strongest recorded pain:\n"
    + "\n".join(f"- {o}" for o in scoring.OFFER_CATALOG)
    + "\nPain-to-offer hints: " + json.dumps(PAIN_TO_OFFER)
    + "\nReturn offer_id, why (citing the pain), and expected_outcome."
)

OFFER_KEYS = ["offer_id", "why", "expected_outcome"]


@_fail_closed
def stage_offer(workspace_id: str, lead_id: str) -> dict:
    lead = _load_lead(workspace_id, lead_id)
    if not lead["primary_pain"]:
        raise PipelineError("offer selection requires completed audit")

    parsed = llm.structured_complete(
        agent_name="offer_selection_agent",
        system=OFFER_SYSTEM,
        user=json.dumps({
            "business_name": lead["business_name"],
            "vertical": lead["vertical"],
            "primary_pain": lead["primary_pain"],
            "secondary_pain": lead["secondary_pain"],
            "pain_points": (lead.get("website_findings") or {}).get("pain_points"),
        }),
        required_keys=OFFER_KEYS,
        workspace_id=workspace_id,
    )
    offer = parsed.get("offer_id")
    if offer not in scoring.OFFER_CATALOG:
        _flag_review(workspace_id, lead_id, f"invalid offer selected: {offer!r}")
        raise PipelineError("invalid offer")

    # HARD RULE 4: deterministic offer-pain consistency check.
    expected = PAIN_TO_OFFER.get(lead["primary_pain"])
    if expected and offer != expected:
        _flag_review(
            workspace_id, lead_id,
            f"offer-pain contract violation: pain={lead['primary_pain']} requires {expected}, got {offer}",
        )
        raise PipelineError("offer-pain mismatch (contract error)")

    _update_lead(lead_id, {"recommended_offer": offer})
    _add_activity(workspace_id, lead_id, f"offer selected: {offer} ({parsed.get('why')})")
    return {"recommended_offer": offer}


# ------------------------------------------------------- stage 5: personalization

PERSONALIZE_SYSTEM = (
    "You are the Email Personalization Agent writing cold emails to owner-operated "
    "home-services contractors. Hermes structure, exactly 4 sentences: Fact (evidence "
    "you observed), Inference (what it costs them), Offer (one line), Question (low-"
    "friction CTA). UNDER 75 WORDS TOTAL. Plain language, no hype, no invented facts. "
    "Reference only the evidence provided."
)

PERSONALIZE_KEYS = ["subject", "first_sentence", "body", "cta", "followup_angle"]

BANNED_PHRASES = [
    "i hope this email finds you well", "quick question", "just following up",
    "circling back", "touching base", "game-changer", "revolutionary",
    "as a valued", "act now", "limited time",
]


@_fail_closed
def stage_personalize(workspace_id: str, lead_id: str) -> dict:
    lead = _load_lead(workspace_id, lead_id)
    if not all([lead["primary_pain"], lead["recommended_offer"]]):
        raise PipelineError("personalization requires audit + offer stages complete")

    parsed = llm.structured_complete(
        agent_name="email_personalization_agent",
        system=PERSONALIZE_SYSTEM,
        user=json.dumps({
            "owner_name": None,  # fail-closed: never invent names
            "business_name": lead["business_name"],
            "evidence": {
                "observed": (lead.get("evidence") or {}).get("agent_evidence"),
                "primary_pain": lead["primary_pain"],
                "secondary_pain": lead["secondary_pain"],
                "website_findings": (lead.get("website_findings") or {}).get("findings"),
            },
            "offer": lead["recommended_offer"],
        }),
        required_keys=PERSONALIZE_KEYS,
        workspace_id=workspace_id,
        max_tokens=600,
    )
    body_text = " ".join(filter(None, [parsed.get("first_sentence"), parsed.get("body"), parsed.get("cta")]))
    word_count = len(body_text.split())

    # deterministic QA checks
    problems = []
    if word_count >= 75:
        problems.append(f"draft exceeds 75 words ({word_count})")
    lowered = body_text.lower()
    hit_banned = [p for p in BANNED_PHRASES if p in lowered]
    if hit_banned:
        problems.append(f"banned phrases present: {hit_banned}")
    sentences = re.split(r"[.!?]+(?:\s|$)", body_text.strip())
    if len([s for s in sentences if s.strip()]) != 4:
        problems.append(f"structure must be exactly 4 sentences, got {len([s for s in sentences if s.strip()])}")

    if problems:
        # AI critic pass: one revision attempt before routing to review
        revised = llm.structured_complete(
            agent_name="email_critic_agent",
            system="You are the Email Critic Agent. Fix these problems in the draft while keeping the 4-sentence Fact/Inference/Offer/Question structure and under 75 words.",
            user=json.dumps({"problems": problems, "draft": parsed}),
            required_keys=PERSONALIZE_KEYS,
            workspace_id=workspace_id,
            max_tokens=600,
        )
        body_text = " ".join(filter(None, [revised.get("first_sentence"), revised.get("body"), revised.get("cta")]))
        word_count = len(body_text.split())
        if word_count >= 75:
            _flag_review(workspace_id, lead_id, f"draft still too long after critic pass ({word_count} words)")
            raise llm.ReviewRequired(problems)
        parsed = revised

    # create draft message awaiting approval — NEVER auto-send
    msg_id = create_draft_message(workspace_id, lead_id, parsed, body_text)
    _add_activity(workspace_id, lead_id, f"draft created ({word_count} words), awaiting approval")
    return {"message_id": msg_id, "word_count": word_count, "draft": parsed}


def create_draft_message(workspace_id: str, lead_id: str, parsed: dict, body_text: str) -> str:
    with db.get_pool().connection() as conn:
        row = conn.execute(
            """INSERT INTO messages
               (workspace_id, lead_id, channel, direction, subject, body_text, status)
               VALUES (%s,%s,'email','outbound',%s,%s,'pending_approval')
               RETURNING id""",
            (workspace_id, lead_id, parsed.get("subject"), body_text),
        ).fetchone()
    return str(row["id"])


# ---------------------------------------------------------------- runner

STAGES = [stage_qualify, stage_enrich, stage_audit, stage_offer, stage_personalize]


def run_pipeline(workspace_id: str, lead_id: str) -> dict:
    """Run all six stages (search happens upstream). Stops at first blocker;
    failures are recorded and the lead lands in the review queue."""
    results: dict = {"lead_id": lead_id, "stages": {}}
    for stage in STAGES:
        try:
            results["stages"][stage.__name__] = stage(workspace_id, lead_id)
        except (llm.MissingConfiguration, llm.BudgetExceeded, llm.ReviewRequired, PipelineError) as e:
            results["stopped_at"] = stage.__name__
            results["error"] = str(e)
            break
    else:
        results["stopped_at"] = None

    # outreach_ready only when fully drafted AND email provider-verified
    lead = _load_lead(workspace_id, lead_id)
    contact = None
    with db.get_pool().connection() as conn:
        row = conn.execute(
            """SELECT email_verification_status FROM contacts WHERE id =
               (SELECT contact_id FROM leads WHERE id=%s)""",
            (lead_id,),
        ).fetchone()
        contact = row["email_verification_status"] if row else None
    if (
        results["stopped_at"] is None
        and contact == "verified"
    ):
        from app.services import state_machine

        with db.get_pool().connection() as conn:
            fresh = conn.execute("SELECT status FROM leads WHERE id=%s", (lead_id,)).fetchone()
            current = fresh["status"] if fresh else None
            if current and state_machine.can_transition(current, "outreach_ready"):
                state_machine.transition(conn, lead_id, workspace_id, current, "outreach_ready")
    return results
