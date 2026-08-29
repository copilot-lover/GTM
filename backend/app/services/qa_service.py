"""Independent QA layer (conceptually agent GTM_QA).

GTM_QA reviews artifacts produced by the other agents (drafts from GTM_COPY,
leads/research from GTM_LEADS / GTM_INTENT) and never generates copy itself.
Every check here is deterministic code — the backend NEVER calls an LLM.
The layer fails closed: any critical finding marks the run 'failed' and blocks
progression. It cannot be bypassed because the sender gate (built elsewhere)
requires a passed qa_runs record for managed messages before anything leaves
the building.

Every finding is a dict: {'rule', 'severity': 'critical'|'warning',
'message', optional 'evidence_ref'}.
"""

import datetime as dt
import json
import re

import psycopg.rows

import app.db as db


FINDING_RULES = {
    'UNSUPPORTED_FACT', 'WRONG_SIGNAL', 'WEAK_ICP_FIT', 'GENERIC_COPY',
    'WRONG_PERSON', 'WRONG_OFFER', 'COMPLIANCE_FAILURE', 'EXCESSIVE_CLAIM',
    'MISSING_EVIDENCE',
}


class QAError(Exception):
    pass


# ---------------------------------------------------------------- helpers

def _finding(rule: str, severity: str, message: str,
             evidence_ref: str | None = None) -> dict:
    f = {"rule": rule, "severity": severity, "message": message}
    if evidence_ref:
        f["evidence_ref"] = evidence_ref
    return f


def _failed_rules(findings: list[dict]) -> list[str]:
    return sorted({f["rule"] for f in findings if f["severity"] == "critical"})


def _store_qa_run(workspace_id: str, object_type: str, object_id: str,
                  findings: list[dict], evidence_refs=None) -> dict:
    """Insert one qa_runs row; attempt = previous max for this object + 1."""
    failed = _failed_rules(findings)
    status = "failed" if failed else "passed"
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        prev = conn.execute(
            """SELECT COALESCE(MAX(attempt), 0) AS n FROM qa_runs
               WHERE workspace_id=%s AND object_type=%s AND object_id=%s""",
            (workspace_id, object_type, object_id),
        ).fetchone()
        row = conn.execute(
            """INSERT INTO qa_runs
               (workspace_id, object_type, object_id, score, status, findings,
                evidence_refs, failed_rules, attempt, model)
               VALUES (%s,%s,%s,NULL,%s,%s,%s,%s,%s,'deterministic')
               RETURNING *""",
            (workspace_id, object_type, object_id, status,
             json.dumps(findings), json.dumps(evidence_refs or []),
             json.dumps(failed), (prev["n"] or 0) + 1),
        ).fetchone()
    return dict(row)


def _load_copy_message(workspace_id: str, message_id: str) -> dict:
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        row = conn.execute(
            """SELECT id, workspace_id, lead_id, campaign_id, channel, direction,
                      subject, body_text, claims, evidence_refs, gtm_stage,
                      experiment_id
               FROM messages WHERE id=%s AND workspace_id=%s""",
            (message_id, workspace_id),
        ).fetchone()
    if row is None:
        raise QAError("message not found")
    return dict(row)


def _load_compliance_context(workspace_id: str, message_id: str) -> dict:
    """Same joins as email_service._load_message."""
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        row = conn.execute(
            """SELECT m.*, l.contact_id, l.company_id, l.status AS lead_status,
                      c.email, c.opt_out_flag, c.email_verification_status,
                      co.phone AS company_phone, co.business_name
               FROM messages m
               JOIN leads l ON l.id = m.lead_id
               LEFT JOIN contacts c ON c.id = l.contact_id
               LEFT JOIN companies co ON co.id = l.company_id
               WHERE m.id=%s AND m.workspace_id=%s""",
            (message_id, workspace_id),
        ).fetchone()
    if row is None:
        raise QAError("message not found")
    return dict(row)


def max_attempts() -> int:
    from app.config import get_settings

    return get_settings().gtm_copy_max_attempts


def latest_run(workspace_id: str, object_type: str,
               object_id: str) -> dict | None:
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        row = conn.execute(
            """SELECT * FROM qa_runs
               WHERE workspace_id=%s AND object_type=%s AND object_id=%s
               ORDER BY created_at DESC, id DESC LIMIT 1""",
            (workspace_id, object_type, object_id),
        ).fetchone()
    return dict(row) if row else None


# --------------------------------------------------------------- copy QA

def _claim_is_covered(index: int, claim_text: str, refs: list[dict]) -> bool:
    lowered = (claim_text or "").lower()
    for e in refs:
        if not isinstance(e, dict):
            continue
        if e.get("claim_index") == index:
            return True
        text = e.get("text") or ""
        if text and text.lower() in lowered:
            return True
        ref = e.get("ref") or ""
        if ref and isinstance(ref, str) and ref.lower() in lowered:
            return True
    return False


def _check_signal_refs(workspace_id: str, refs: list[dict],
                       findings: list[dict]) -> None:
    """Every evidence ref carrying a signal_id must point at a live signal."""
    for e in refs:
        if not isinstance(e, dict):
            continue
        sid = e.get("signal_id")
        if not sid:
            continue
        with db.get_pool().connection() as conn:
            conn.row_factory = psycopg.rows.dict_row
            row = conn.execute(
                """SELECT id, status, expires_at FROM hiring_signals
                   WHERE id=%s AND workspace_id=%s""",
                (sid, workspace_id),
            ).fetchone()
        if row is None:
            findings.append(_finding(
                "WRONG_SIGNAL", "critical",
                f"evidence cites nonexistent hiring signal {sid}",
                evidence_ref=str(sid)))
        elif row["status"] != "active" or (
                row["expires_at"]
                and row["expires_at"] < dt.datetime.now(dt.timezone.utc)):
            findings.append(_finding(
                "WRONG_SIGNAL", "critical",
                f"hiring signal {sid} is expired "
                f"(status={row['status']}, expires_at={row['expires_at']})",
                evidence_ref=str(sid)))


def run_copy_qa(workspace_id: str, message_id: str, actor: str = "GTM_QA") -> dict:
    """Deterministic review of a generated draft. Gate: message.gtm_stage must
    be QA_PENDING (NULL legacy rows are checked+recorded but never transitioned)."""
    from app.services import gtm_lifecycle

    msg = _load_copy_message(workspace_id, message_id)
    findings: list[dict] = []
    claims = list(msg.get("claims") or [])
    refs = [r for r in (msg.get("evidence_refs") or []) if isinstance(r, dict)]
    subject = (msg.get("subject") or "").strip()
    body = (msg.get("body_text") or "").strip()

    # structural completeness
    if not subject or not body:
        findings.append(_finding(
            "MISSING_EVIDENCE", "critical",
            "draft is incomplete: " +
            ", ".join(n for n, v in (("subject", subject), ("body", body)) if not v)
            + " empty"))

    # claim -> evidence coverage
    for i, claim in enumerate(claims):
        claim_text = claim if isinstance(claim, str) else str((claim or {}).get("text") or "")
        if not _claim_is_covered(i, claim_text, refs):
            findings.append(_finding(
                "UNSUPPORTED_FACT", "critical",
                f"claim[{i}] has no matching evidence ref: "
                f"{(claim_text or '(empty)')[:120]}"))

    _check_signal_refs(workspace_id, refs, findings)

    # generic-copy heuristics (mirror pipeline.apply_draft logic)
    from app.services.pipeline import BANNED_PHRASES

    lowered = body.lower()
    hits = [p for p in BANNED_PHRASES if p in lowered]
    if hits:
        findings.append(_finding(
            "GENERIC_COPY", "critical", f"banned phrases present: {hits}"))
    word_count = len(body.split())
    if word_count >= 75:
        findings.append(_finding(
            "GENERIC_COPY", "warning",
            f"draft exceeds 75 words ({word_count})"))
    sentences = re.split(r"[.!?]+(?:\s|$)", body)
    n_sentences = len([s for s in sentences if s.strip()])
    if body and n_sentences != 4:
        findings.append(_finding(
            "GENERIC_COPY", "warning",
            f"draft must be exactly 4 sentences, got {n_sentences}"))

    run = _store_qa_run(workspace_id, "copy", message_id, findings, refs)

    stage = msg.get("gtm_stage")
    if stage == "QA_PENDING":
        target = "QA_PASSED" if run["status"] == "passed" else "QA_FAILED"
        gtm_lifecycle.transition_message(
            workspace_id, message_id, target, actor=actor,
            reason=f"copy QA {run['status']}: {_failed_rules(findings) or 'clean'}",
            qa_run_id=run["id"])
    elif stage is not None:
        raise QAError(f"copy QA expects gtm_stage QA_PENDING, got {stage}")

    result = dict(run)
    result["findings"] = findings
    return result


# --------------------------------------------------------- compliance QA

_BLOCKED_LEAD_STATUSES = {"do_not_call", "rejected", "archived", "lost"}


def run_compliance_qa(workspace_id: str, message_id: str,
                      actor: str = "GTM_QA") -> dict:
    """Consent/suppression/verification gate. Lifecycle: QA_PASSED ->
    COMPLIANCE_PENDING -> SEND_READY (pass) or COMPLIANCE_FAILED (fail)."""
    from app.services import gtm_lifecycle, suppression

    msg = _load_compliance_context(workspace_id, message_id)
    findings: list[dict] = []

    if msg.get("opt_out_flag"):
        findings.append(_finding(
            "COMPLIANCE_FAILURE", "critical", "contact has opted out"))
    if msg.get("email"):
        result = suppression.check(
            workspace_id=workspace_id, email=msg["email"],
            phone=msg.get("company_phone"),
            company_id=str(msg["company_id"]) if msg.get("company_id") else None)
        if result.blocked:
            findings.append(_finding(
                "COMPLIANCE_FAILURE", "critical",
                f"suppression block: {result.reason}"))
    else:
        findings.append(_finding(
            "COMPLIANCE_FAILURE", "critical", "contact has no email address"))
    if msg.get("email_verification_status") != "verified":
        findings.append(_finding(
            "COMPLIANCE_FAILURE", "critical",
            "email not provider-verified "
            f"(status={msg.get('email_verification_status')})"))
    if msg.get("campaign_id"):
        with db.get_pool().connection() as conn:
            conn.row_factory = psycopg.rows.dict_row
            camp = conn.execute(
                "SELECT status FROM campaigns WHERE id=%s",
                (str(msg["campaign_id"]),),
            ).fetchone()
        if camp is None or camp["status"] != "active":
            findings.append(_finding(
                "COMPLIANCE_FAILURE", "critical",
                "campaign inactive"
                + (f" (status={camp['status']})" if camp else " (missing)")))
    if msg.get("lead_status") in _BLOCKED_LEAD_STATUSES:
        findings.append(_finding(
            "COMPLIANCE_FAILURE", "critical",
            f"lead status blocks outreach: {msg['lead_status']}"))

    run = _store_qa_run(workspace_id, "compliance", message_id, findings)

    stage = msg.get("gtm_stage")
    if stage == "QA_PASSED":
        gtm_lifecycle.transition_message(
            workspace_id, message_id, "COMPLIANCE_PENDING", actor=actor,
            reason="compliance QA started")
        stage = "COMPLIANCE_PENDING"
    if stage == "COMPLIANCE_PENDING":
        target = "SEND_READY" if run["status"] == "passed" else "COMPLIANCE_FAILED"
        gtm_lifecycle.transition_message(
            workspace_id, message_id, target, actor=actor,
            reason=f"compliance QA {run['status']}: "
                   f"{_failed_rules(findings) or 'clean'}",
            qa_run_id=run["id"])
    elif stage is not None:
        raise QAError(
            f"compliance QA expects gtm_stage QA_PASSED or "
            f"COMPLIANCE_PENDING, got {stage}")

    result = dict(run)
    result["findings"] = findings
    return result


# ----------------------------------------------------------------- lead QA

def run_lead_qa(workspace_id: str, lead_id: str, actor: str = "GTM_QA") -> dict:
    """ICP-fit / identity checks on a lead artifact. No lifecycle transitions:
    leads have their own FSM."""
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        lead = conn.execute(
            """SELECT l.*, c.email AS contact_email
               FROM leads l LEFT JOIN contacts c ON c.id = l.contact_id
               WHERE l.id=%s AND l.workspace_id=%s""",
            (lead_id, workspace_id),
        ).fetchone()
    if lead is None:
        raise QAError("lead not found")

    findings: list[dict] = []
    fit_status = lead.get("fit_status") or ""
    lead_score = lead.get("lead_score")
    if fit_status.startswith("rejected"):
        findings.append(_finding(
            "WEAK_ICP_FIT", "critical", f"fit_status rejected: {fit_status}"))
    elif lead_score is not None and lead_score < 5:
        findings.append(_finding(
            "WEAK_ICP_FIT", "critical", f"lead_score below floor: {lead_score}/10"))
    if not lead.get("contact_id") or not lead.get("contact_email"):
        findings.append(_finding(
            "WRONG_PERSON", "critical",
            "no reachable contact person on lead (contact/email missing)"))

    evidence = lead.get("evidence") or {}
    signal_ids = evidence.get("signal_ids") or []
    for sid in signal_ids:
        with db.get_pool().connection() as conn:
            row = conn.execute(
                "SELECT id FROM hiring_signals WHERE id=%s AND workspace_id=%s",
                (sid, workspace_id),
            ).fetchone()
        if row is None:
            findings.append(_finding(
                "WRONG_SIGNAL", "critical",
                f"lead ICP evidence cites nonexistent hiring signal {sid}",
                evidence_ref=str(sid)))

    run = _store_qa_run(workspace_id, "lead", lead_id, findings)
    result = dict(run)
    result["findings"] = findings
    return result


# ------------------------------------------------------------- research QA

_RESEARCH_MAX_AGE_DAYS = 30


def run_research_qa(workspace_id: str, lead_id: str, actor: str = "GTM_QA") -> dict:
    """Freshness + provenance checks on the latest research report for the
    lead's company."""
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        lead = conn.execute(
            "SELECT company_id FROM leads WHERE id=%s AND workspace_id=%s",
            (lead_id, workspace_id),
        ).fetchone()
        if lead is None:
            raise QAError("lead not found")
        report = conn.execute(
            """SELECT * FROM research_reports WHERE company_id=%s
               ORDER BY created_at DESC, id DESC LIMIT 1""",
            (str(lead["company_id"]),),
        ).fetchone()

    findings: list[dict] = []
    if report is None:
        findings.append(_finding(
            "MISSING_EVIDENCE", "critical",
            "no research report exists for this company"))
    else:
        evidence = list(report.get("evidence") or [])
        if not evidence:
            findings.append(_finding(
                "MISSING_EVIDENCE", "warning",
                "research report carries an empty evidence array"))
        age_days = (dt.datetime.now(dt.timezone.utc) - report["created_at"]).days
        if age_days > _RESEARCH_MAX_AGE_DAYS:
            findings.append(_finding(
                "MISSING_EVIDENCE", "warning",
                f"research report is stale ({age_days} days old, "
                f"max {_RESEARCH_MAX_AGE_DAYS})"))
        # QC provenance: every evidence item must cite a source_ref + claim.
        for i, ev in enumerate(evidence):
            if not isinstance(ev, dict) or not ev.get("source_ref") or not ev.get("claim"):
                findings.append(_finding(
                    "UNSUPPORTED_FACT", "critical",
                    f"report evidence[{i}] failed QC: missing claim/source_ref"))

    run = _store_qa_run(workspace_id, "research", lead_id, findings)
    result = dict(run)
    result["findings"] = findings
    return result


# ------------------------------------------------------------ resubmission

def resubmit_copy(workspace_id: str, message_id: str, parsed: dict,
                  actor: str = "GTM_COPY") -> dict:
    """Findings-driven regeneration path. Requeues a failed draft for another
    QA round until gtm_copy_max_attempts is exhausted, then holds it."""
    from app.services import gtm_lifecycle

    prev = latest_run(workspace_id, "copy", message_id)
    if prev is None or prev["status"] == "passed":
        raise QAError("nothing to resubmit")

    next_attempt = (prev["attempt"] or 0) + 1
    ceiling = max_attempts()
    if next_attempt > ceiling:
        gtm_lifecycle.transition_message(
            workspace_id, message_id, "HELD", actor=actor,
            reason=f"max QA attempts exceeded ({ceiling})")
        return {"held": True, "attempts": prev["attempt"]}

    body_text = " ".join(filter(None, [
        parsed.get("first_sentence"), parsed.get("body"), parsed.get("cta")]))
    claims = list(parsed.get("claims") or [])
    refs = list(parsed.get("evidence_refs") or [])
    with db.get_pool().connection() as conn:
        conn.execute(
            """UPDATE messages SET subject=%s, body_text=%s, claims=%s,
               evidence_refs=%s WHERE id=%s AND workspace_id=%s""",
            (parsed.get("subject"), body_text, json.dumps(claims),
             json.dumps(refs), message_id, workspace_id),
        )

    gtm_lifecycle.transition_message(
        workspace_id, message_id, "COPY_GENERATED", actor=actor,
        reason=f"regeneration after QA findings (attempt {next_attempt}/{ceiling})")
    gtm_lifecycle.transition_message(
        workspace_id, message_id, "QA_PENDING", actor="GTM_QA",
        reason=f"findings-driven regeneration queued for QA (attempt {next_attempt})")
    return {"requeued": True, "attempt": next_attempt}
