"""AI Company Research Service — WS-D: research with evidence citations.

Assembles evidence from hiring signals, job postings, website findings, tech signals,
reviews, and business data. Calls LLM (strong tier) to produce structured research
report with evidence citations. QC gate validates no hallucinated facts.
"""

import json
import logging
from dataclasses import dataclass

import psycopg.rows

import app.db as db
from app.providers import ProviderUnavailable, get
from app.providers.base import LLMProvider, LLMResponse

log = logging.getLogger(__name__)

RESEARCH_SYSTEM_PROMPT = (
    "You are a company research analyst for Orbit (AI receptionist agency). "
    "Given evidence about a home-services company, produce a research_report JSON "
    "with: summary, primary_problem, reason_now, recommended_offer, evidence[]. "
    "Each evidence item MUST have {claim, source_ref, source_type} where "
    "source_type in ('hiring_signal','job_description','website','tech_signal',"
    "'review','business_data'). NO INVENTED FACTS — every claim must trace to a "
    "source_ref from the provided evidence. Return ONLY valid JSON."
)

RESEARCH_EVIDENCE_TYPES = {
    "hiring_signal", "job_description", "website", "tech_signal",
    "review", "business_data"
}

@dataclass
class ResearchReport:
    summary: str
    primary_problem: str
    reason_now: str
    recommended_offer: str
    evidence: list[dict]
    model_used: str


def _get_llm() -> LLMProvider | None:
    try:
        return get("llm")
    except ProviderUnavailable:
        return None


def _assemble_evidence(company_id: str, workspace_id: str) -> list[dict]:
    """Assemble all evidence sources for a company."""
    evidence = []

    # Hiring signals (active)
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        signals = conn.execute(
            """SELECT * FROM hiring_signals
               WHERE company_id=%s AND workspace_id=%s AND status='active'
               ORDER BY signal_score DESC""",
            (company_id, workspace_id),
        ).fetchall()

    for s in signals:
        evidence.append({
            "source_ref": f"hiring_signal:{s['id']}",
            "source_type": "hiring_signal",
            "content": {
                "title": s.get("title"),
                "role_category": s.get("role_category"),
                "intent_category": s.get("intent_category"),
                "pain_hypothesis": s.get("pain_hypothesis"),
                "orbit_product_fit": s.get("orbit_product_fit"),
                "signal_score": s.get("signal_score"),
                "description": s.get("description", "")[:2000],
            }
        })

    # Job postings (qualified)
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        postings = conn.execute(
            """SELECT * FROM job_postings
               WHERE company_id=%s AND workspace_id=%s AND status IN ('qualified','nurture')
               ORDER BY intent_score DESC""",
            (company_id, workspace_id),
        ).fetchall()

    for p in postings:
        evidence.append({
            "source_ref": f"job_posting:{p['id']}",
            "source_type": "job_description",
            "content": {
                "title": p.get("title"),
                "intent_score": p.get("intent_score"),
                "intent_category": p.get("intent_category"),
                "qualification_rationale": p.get("qualification_rationale"),
                "description_raw": p.get("description_raw", "")[:2000],
                "relevant_responsibilities": p.get("relevant_responsibilities"),
            }
        })

    # Company data + website findings + tech signals
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        company = conn.execute(
            "SELECT * FROM companies WHERE id=%s", (company_id,)
        ).fetchone()

    if company:
        # Business data evidence
        biz_fields = [
            "business_name", "vertical", "city", "state", "employee_estimate",
            "number_of_locations", "owner_name", "google_rating", "review_count",
            "phone", "website"
        ]
        biz_content = {k: company.get(k) for k in biz_fields if company.get(k)}
        if biz_content:
            evidence.append({
                "source_ref": f"company:{company_id}",
                "source_type": "business_data",
                "content": biz_content
            })

        # Website findings
        wf = company.get("website_findings") or {}
        if wf:
            evidence.append({
                "source_ref": f"website_findings:{company_id}",
                "source_type": "website",
                "content": wf
            })

        # Tech signals
        tech = company.get("tech_signals") or {}
        if tech:
            evidence.append({
                "source_ref": f"tech_signals:{company_id}",
                "source_type": "tech_signal",
                "content": tech
            })

        # Reviews evidence
        if company.get("google_rating") or company.get("review_count"):
            evidence.append({
                "source_ref": f"reviews:{company_id}",
                "source_type": "review",
                "content": {
                    "google_rating": company.get("google_rating"),
                    "review_count": company.get("review_count"),
                }
            })

    return evidence


def _build_user_prompt(company: dict, evidence: list[dict]) -> str:
    """Build the user prompt with company context and evidence."""
    import json as _json

    def _json_default(obj):
        if hasattr(obj, '__str__'):
            return str(obj)
        raise TypeError(f'Object of type {type(obj).__name__} is not JSON serializable')

    evidence_summary = []
    for i, e in enumerate(evidence):
        evidence_summary.append(f"[{i}] {e['source_ref']} ({e['source_type']}): {_json.dumps(e['content'], default=_json_default)[:1500]}")

    return (
        f"Company: {company.get('business_name')}\n"
        f"Vertical: {company.get('vertical')}\n"
        f"Location: {company.get('city')}, {company.get('state')}\n"
        f"Website: {company.get('website')}\n\n"
        f"EVIDENCE:\n" + "\n".join(evidence_summary)
    )


def _call_llm_research(company: dict, evidence: list[dict]) -> ResearchReport:
    """Call LLM (strong tier) to generate research report."""
    llm = _get_llm()
    if not llm:
        return _fallback_research(company, evidence)

    user_prompt = _build_user_prompt(company, evidence)

    try:
        resp: LLMResponse = llm.complete(RESEARCH_SYSTEM_PROMPT, user_prompt, model_tier="strong")
        import json as _json
        data = _json.loads(resp.content)

        return ResearchReport(
            summary=data.get("summary", ""),
            primary_problem=data.get("primary_problem", ""),
            reason_now=data.get("reason_now", ""),
            recommended_offer=data.get("recommended_offer", "ai_receptionist"),
            evidence=data.get("evidence", []),
            model_used=resp.model_used,
        )
    except Exception as e:
        log.warning(f"LLM research failed: {e}")
        return _fallback_research(company, evidence)


def _fallback_research(company: dict, evidence: list[dict]) -> ResearchReport:
    """Deterministic fallback when LLM unavailable."""
    primary_problem = "High inbound call volume overwhelming staff"
    reason_now = "Active hiring for receptionist/dispatcher roles indicates growth pain"
    recommended_offer = "ai_receptionist"

    # Infer from evidence
    for e in evidence:
        if e["source_type"] == "hiring_signal":
            content = e.get("content", {})
            if content.get("pain_hypothesis"):
                primary_problem = content["pain_hypothesis"][:200]
            if content.get("orbit_product_fit"):
                recommended_offer = content["orbit_product_fit"].split(",")[0]

    # Build evidence citations
    cited_evidence = []
    for i, e in enumerate(evidence):
        content = e.get("content", {})
        claim = ""
        if e["source_type"] == "hiring_signal":
            claim = f"Hiring for {content.get('role_category', 'role')} with {content.get('intent_category', '')} intent (score: {content.get('signal_score', 0)})"
        elif e["source_type"] == "job_description":
            claim = f"Job posting: {content.get('title', '')} — {content.get('qualification_rationale', '')[:200]}"
        elif e["source_type"] == "website":
            claim = f"Website has booking CTA: {content.get('booking_cta', {}).get('text', 'none')}, chat: {content.get('chat_widget', 'none')}"
        elif e["source_type"] == "tech_signal":
            active_tech = [k for k, v in content.items() if v]
            claim = f"Tech stack includes: {', '.join(active_tech) or 'none detected'}"
        elif e["source_type"] == "review":
            claim = f"Google rating: {content.get('google_rating')}, reviews: {content.get('review_count')}"
        elif e["source_type"] == "business_data":
            claim = f"Business: {content.get('business_name')}, {content.get('employee_estimate', '?')} employees, vertical: {content.get('vertical')}"

        if claim:
            cited_evidence.append({
                "claim": claim,
                "source_ref": e["source_ref"],
                "source_type": e["source_type"]
            })

    return ResearchReport(
        summary=f"{company.get('business_name')} is a {company.get('vertical', 'home services')} company with active hiring signals indicating need for AI receptionist.",
        primary_problem=primary_problem,
        reason_now=reason_now,
        recommended_offer=recommended_offer,
        evidence=cited_evidence,
        model_used="fallback-deterministic",
    )


def _validate_research_report(report: ResearchReport, evidence: list[dict]) -> tuple[bool, list[str]]:
    """QC gate: validate every evidence claim traces to source."""
    failures = []
    evidence_by_ref = {e["source_ref"]: e for e in evidence}

    for i, ev in enumerate(report.evidence):
        claim = ev.get("claim", "").strip()
        source_ref = ev.get("source_ref", "").strip()
        source_type = ev.get("source_type", "").strip()

        if not claim:
            failures.append(f"evidence[{i}]: empty claim")
            continue
        if not source_ref:
            failures.append(f"evidence[{i}]: missing source_ref")
            continue
        if source_ref not in evidence_by_ref:
            failures.append(f"evidence[{i}]: source_ref '{source_ref}' not in assembled evidence")
            continue
        if source_type not in RESEARCH_EVIDENCE_TYPES:
            failures.append(f"evidence[{i}]: invalid source_type '{source_type}'")
            continue

        # Heuristic: claim keywords should appear in source text
        source_content = json.dumps(evidence_by_ref[source_ref].get("content", {})).lower()
        claim_words = [w for w in claim.lower().split() if len(w) > 3]
        if claim_words:
            matches = sum(1 for w in claim_words if w in source_content)
            if matches == 0:
                failures.append(f"evidence[{i}]: claim keywords not found in source (possible hallucination)")

    return len(failures) == 0, failures


def _repair_research_report(report: ResearchReport, evidence: list[dict], failures: list[str]) -> ResearchReport:
    """Re-prompt LLM once with failures to fix hallucinations."""
    llm = _get_llm()
    if not llm:
        return report  # can't repair without LLM

    evidence_by_ref = {e["source_ref"]: e for e in evidence}

    def _json_default(obj):
        if hasattr(obj, '__str__'):
            return str(obj)
        raise TypeError(f'Object of type {type(obj).__name__} is not JSON serializable')

    repair_prompt = (
        f"Previous report failed validation: {json.dumps(failures)}. "
        f"Evidence sources:\n" +
        "\n".join(f"  {ref}: {json.dumps(e['content'], default=_json_default)[:1000]}" for ref, e in evidence_by_ref.items()) +
        "\n\nProduce corrected research_report JSON with valid evidence citations only."
    )

    try:
        resp: LLMResponse = llm.complete(RESEARCH_SYSTEM_PROMPT, repair_prompt, model_tier="strong")
        import json as _json
        data = _json.loads(resp.content)

        return ResearchReport(
            summary=data.get("summary", report.summary),
            primary_problem=data.get("primary_problem", report.primary_problem),
            reason_now=data.get("reason_now", report.reason_now),
            recommended_offer=data.get("recommended_offer", report.recommended_offer),
            evidence=data.get("evidence", []),
            model_used=resp.model_used,
        )
    except Exception as e:
        log.warning(f"LLM repair failed: {e}")
        return report


def research_company(company_id: str) -> ResearchReport:
    """Main entry: research a company, validate, write to research_reports, return report."""
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        company = conn.execute(
            "SELECT * FROM companies WHERE id=%s", (company_id,)
        ).fetchone()

    if not company:
        raise ValueError(f"Company {company_id} not found")

    workspace_id = str(company["workspace_id"])
    evidence = _assemble_evidence(company_id, workspace_id)
    report = _call_llm_research(company, evidence)

    # QC gate
    passed, failures = _validate_research_report(report, evidence)
    if not passed:
        log.warning(f"Research QC failed for {company_id}: {failures}")
        report = _repair_research_report(report, evidence, failures)
        passed, failures = _validate_research_report(report, evidence)
        if not passed:
            log.error(f"Research QC still failing after repair: {failures}")

    # Write to research_reports
    with db.get_pool().connection() as conn:
        conn.execute(
            """INSERT INTO research_reports (workspace_id, company_id, summary, primary_problem,
                   reason_now, recommended_offer, evidence, model_used)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                workspace_id, company_id,
                report.summary, report.primary_problem, report.reason_now,
                report.recommended_offer, json.dumps(report.evidence), report.model_used,
            ),
        )

    return report


def validate_research_report(report: ResearchReport, company_id: str) -> tuple[bool, list[str]]:
    """Standalone validation function for external use."""
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        company = conn.execute(
            "SELECT workspace_id FROM companies WHERE id=%s", (company_id,)
        ).fetchone()
    if not company:
        return False, ["company not found"]

    evidence = _assemble_evidence(company_id, str(company["workspace_id"]))
    return _validate_research_report(report, evidence)