"""Waterfall enrichment & verification orchestration.

- enrich_company_waterfall: tries providers in priority order, stops when enough fields filled
- find_decision_maker_email: uses EmailFinderProvider with decision-maker ranking
- verify_email_waterfall: local pre-checks -> provider waterfall
- track_provider_usage: quota tracking with reserve threshold
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

import psycopg.rows

import app.db as db
from app.config import get_settings
from app.providers import registry, ProviderUnavailable
from app.providers.base import VerificationResult
from app.services import flags
from app.services.email_service import mark_provider_verified


EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

log = logging.getLogger(__name__)

TARGET_FIELDS = ["website", "phone", "employee_estimate", "tech_signals", "owner_name", "owner_email"]


def _get_workspace_id(company_id: str) -> str | None:
    with db.get_pool().connection() as conn:
        row = conn.execute(
            "SELECT workspace_id FROM companies WHERE id=%s", (company_id,)
        ).fetchone()
    return str(row["workspace_id"]) if row else None


def _get_company(company_id: str) -> dict | None:
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        return conn.execute("SELECT * FROM companies WHERE id=%s", (company_id,)).fetchone()


COMPANY_ENRICHABLE_FIELDS = {
    "website", "phone", "address", "city", "state", "zip",
    "employee_estimate", "tech_signals", "owner_name", "owner_operator_confidence",
    "vertical", "number_of_locations", "google_rating", "review_count",
}


import json


def _update_company(company_id: str, fields: dict) -> None:
    if not fields:
        return
    # Filter to only valid company columns
    valid_fields = {k: v for k, v in fields.items() if k in COMPANY_ENRICHABLE_FIELDS}
    if not valid_fields:
        return
    # Serialize jsonb fields
    for k, v in valid_fields.items():
        if k == "tech_signals" and isinstance(v, (list, dict)):
            valid_fields[k] = json.dumps(v)
    sets = ", ".join(f"{k}=%s" for k in valid_fields)
    values = list(valid_fields.values()) + [company_id]
    with db.get_pool().connection() as conn:
        conn.execute(f"UPDATE companies SET {sets}, updated_at=now() WHERE id=%s", tuple(values))


def _json_default(obj):
    if hasattr(obj, '__str__'):
        return str(obj)
    raise TypeError(f'Object of type {type(obj).__name__} is not JSON serializable')


def _log_enrichment(workspace_id: str, company_id: str | None, contact_id: str | None,
                    provider: str, operation: str, request: dict, response: dict,
                    succeeded: bool, cost_units: float = 1.0) -> None:
    with db.get_pool().connection() as conn:
        conn.execute(
            """INSERT INTO enrichments (workspace_id, company_id, contact_id, provider, operation,
               request, response, succeeded, cost_units)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (workspace_id, company_id, contact_id, provider, operation,
             json.dumps(request, default=_json_default), json.dumps(response, default=_json_default), succeeded, cost_units),
        )


def _fields_filled(company: dict) -> int:
    count = 0
    for f in TARGET_FIELDS:
        v = company.get(f)
        if v and (not isinstance(v, (list, dict)) or len(v) > 0):
            count += 1
    return count


def _get_provider_priority(flag_key: str, default: list[str]) -> list[str]:
    try:
        value = flags.get_flag(flag_key)
        if value:
            return value
    except Exception:
        pass
    return default


def track_provider_usage(provider: str, operation: str, cost_units: float = 1.0) -> bool:
    """Upsert provider_usage for current period.
    Returns False if provider should be deprioritized (used >= quota - reserve_threshold)."""
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        row = conn.execute(
            """SELECT quota, used, reserve_threshold FROM provider_usage
               WHERE provider=%s AND operation=%s AND period=%s""",
            (provider, operation, period),
        ).fetchone()
        if row:
            quota = row["quota"]
            used = row["used"] + int(cost_units)
            reserve = row["reserve_threshold"]
            if quota > 0 and used >= quota - reserve:
                conn.execute(
                    """UPDATE provider_usage SET used=%s WHERE provider=%s AND operation=%s AND period=%s""",
                    (used, provider, operation, period),
                )
                return False
            conn.execute(
                """UPDATE provider_usage SET used=%s WHERE provider=%s AND operation=%s AND period=%s""",
                (used, provider, operation, period),
            )
            return True
        else:
            conn.execute(
                """INSERT INTO provider_usage (provider, operation, period, quota, used, reserve_threshold)
                   VALUES (%s,%s,%s,0,1,20)""",
                (provider, operation, period),
            )
            return True


def enrich_company_waterfall(company_id: str) -> dict:
    """Try enrichment providers in priority order until enough fields filled."""
    company = _get_company(company_id)
    if not company:
        raise ValueError(f"Company {company_id} not found")

    workspace_id = _get_workspace_id(company_id)
    if not workspace_id:
        raise ValueError(f"Workspace not found for company {company_id}")

    priority = _get_provider_priority("enrichment_provider_priority", ["apollo", "hunter", "clearbit"])
    enriched = dict(company)
    filled_before = _fields_filled(enriched)

    for provider_name in priority:
        if not track_provider_usage(provider_name, "enrich_company"):
            log.info("provider deprioritized due to quota reserve", extra={"provider": provider_name})
            continue

        try:
            provider = registry.get(provider_name)
        except ProviderUnavailable:
            log.warning("provider unavailable", extra={"provider": provider_name})
            continue

        try:
            result = provider.enrich_company(enriched)
            merged = {**enriched, **result}
            _update_company(company_id, result)
            _log_enrichment(workspace_id, company_id, None, provider_name, "enrich_company",
                           {"company_id": company_id}, result, True)
            enriched = merged
            filled_after = _fields_filled(enriched)
            log.info("enrichment step complete", extra={
                "provider": provider_name, "company_id": company_id,
                "filled_before": filled_before, "filled_after": filled_after,
            })
            if filled_after >= len(TARGET_FIELDS) or filled_after == filled_before:
                break
            filled_before = filled_after
        except Exception as e:
            log.error("provider exception", extra={"provider": provider_name, "error": str(e), "type": type(e).__name__}, exc_info=True)
            _log_enrichment(workspace_id, company_id, None, provider_name, "enrich_company",
                           {"company_id": company_id}, {"error": str(e)}, False)
            log.warning("provider failed", extra={"provider": provider_name, "error": str(e)})
            continue

    return enriched


def find_decision_maker_email(company_id: str) -> dict | None:
    """Find decision-maker email using EmailFinderProvider with ranking."""
    company = _get_company(company_id)
    if not company:
        raise ValueError(f"Company {company_id} not found")

    workspace_id = _get_workspace_id(company_id)
    if not workspace_id:
        raise ValueError(f"Workspace not found for company {company_id}")

    try:
        finder = registry.get("apollo_email_finder")
    except ProviderUnavailable:
        log.warning("email finder provider unavailable")
        return None

    contact_titles = [
        "Owner", "Founder", "President", "General Manager", "GM",
        "Operations Manager", "Service Manager", "Office Manager",
        "Dispatcher Lead", "Dispatcher",
    ]

    best_result = None
    best_rank = 99
    best_confidence = 0

    contact_name = company.get("owner_name") or company.get("business_name") or ""

    for title in contact_titles:
        try:
            result = finder.find_email(company, contact_name, title)
            if result and result.get("email"):
                rank = rank_title(title)
                confidence = result.get("confidence", 0)
                if rank < best_rank or (rank == best_rank and confidence > best_confidence):
                    best_result = result
                    best_rank = rank
                    best_confidence = confidence
        except Exception as e:
            log.warning("email finder failed for title", extra={"title": title, "error": str(e)})
            continue

    if best_result:
        email = best_result["email"]
        with db.get_pool().connection() as conn:
            conn.execute(
                """INSERT INTO contacts (workspace_id, company_id, email, email_verification_status,
                   email_verification_confidence, email_verification_provider, is_decision_maker)
                   VALUES (%s,%s,%s,'unknown',0,'email_finder',true)
                   ON CONFLICT DO NOTHING""",
                (workspace_id, company_id, email),
            )
        return {"email": email, "confidence": best_result.get("confidence", 0), "source": best_result.get("source")}

    return None


def rank_title(title: str) -> int:
    TITLE_RANKING = {
        "owner": 1, "founder": 2, "president": 3, "gm": 4, "general manager": 4,
        "operations manager": 5, "service manager": 6, "office manager": 7,
        "dispatcher lead": 8, "dispatcher": 8,
    }
    t = title.lower().strip()
    for key, rank in TITLE_RANKING.items():
        if key in t:
            return rank
    return 99


DISPOSABLE_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com",
    "throwaway.email", "fakeinbox.com", "trashmail.com", "yopmail.com",
    "getnada.com", "maildrop.cc", "dispostable.com", "temp-mail.org",
    "emailondeck.com", "mintemail.com", "spamgourmet.com", "sharklasers.com",
    "grr.la", "bccto.me", "chacuo.net", "mytemp.email", "emailfake.com",
}

SPAM_TRAP_KEYWORDS = {
    "abuse", "postmaster", "hostmaster", "webmaster", "admin", "root",
    "noreply", "no-reply", "donotreply", "do-not-reply", "bounce",
    "spam", "trap", "honeypot",
}


def _local_prechecks(email: str) -> tuple[dict, float]:
    """Run local validation checks: syntax, DNS, disposable, spam trap heuristics.
    Returns (checks_dict, confidence) where confidence is 0.0-1.0 scale."""
    from dns import resolver

    checks = {
        "syntax_ok": False,
        "dns_ok": False,
        "disposable": False,
        "spam_trap_risk": False,
    }
    confidence = 0.0

    if not EMAIL_RE.match(email):
        return checks, 0.0

    checks["syntax_ok"] = True
    confidence = 0.3

    domain = email.split("@")[1].lower()
    local_part = email.split("@")[0].lower()

    if domain in DISPOSABLE_DOMAINS:
        checks["disposable"] = True

    if any(kw in local_part for kw in SPAM_TRAP_KEYWORDS):
        checks["spam_trap_risk"] = True

    try:
        answers = resolver.resolve(domain, "MX")
        if answers:
            checks["dns_ok"] = True
            confidence = 0.6
    except Exception:
        pass

    return checks, confidence


def verify_email_waterfall(contact_id: str) -> VerificationResult:
    """Local pre-checks -> provider waterfall. On verified, calls mark_provider_verified()."""
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        contact = conn.execute("SELECT * FROM contacts WHERE id=%s", (contact_id,)).fetchone()
        if not contact:
            raise ValueError(f"Contact {contact_id} not found")

        email = contact["email"]
        if not email:
            return VerificationResult(email="", result="invalid", confidence=0,
                                      raw={"error": "no email on contact"})

        workspace_id = contact["workspace_id"]

        # Find associated lead for mark_provider_verified
        lead = conn.execute(
            "SELECT id FROM leads WHERE contact_id=%s AND workspace_id=%s LIMIT 1",
            (contact_id, workspace_id),
        ).fetchone()
        lead_id = str(lead["id"]) if lead else None

    local_checks, local_confidence = _local_prechecks(email)

    if not local_checks["syntax_ok"]:
        result = VerificationResult(email=email, result="invalid", confidence=0,
                                    raw={"provider": "local", "local_checks": local_checks})
        _log_verification(workspace_id, contact_id, email, result)
        return result

    if local_checks["disposable"]:
        result = VerificationResult(email=email, result="disposable", confidence=local_confidence,
                                    raw={"provider": "local", "local_checks": local_checks})
        _log_verification(workspace_id, contact_id, email, result)
        return result

    if local_checks["spam_trap_risk"]:
        result = VerificationResult(email=email, result="spam_trap", confidence=local_confidence,
                                    raw={"provider": "local", "local_checks": local_checks})
        _log_verification(workspace_id, contact_id, email, result)
        return result

    priority = _get_provider_priority("verification_provider_priority", ["zerobounce", "hunter_verify"])

    for provider_name in priority:
        if not track_provider_usage(provider_name, "verify_email"):
            log.info("provider deprioritized due to quota reserve", extra={"provider": provider_name})
            continue

        try:
            provider = registry.get(provider_name)
        except ProviderUnavailable:
            log.warning("provider unavailable", extra={"provider": provider_name})
            continue

        try:
            result = provider.verify(email)
            result.raw = {**result.raw, "local_checks": local_checks}
            _log_verification(workspace_id, contact_id, email, result)

            if result.result == "valid" and result.confidence >= 0.9:
                confidence_pct = int(result.confidence * 100)
                if lead_id:
                    mark_provider_verified(workspace_id, lead_id, provider_name, confidence_pct)
                else:
                    # Directly update contact when no lead is associated
                    with db.get_pool().connection() as conn:
                        conn.execute(
                            """UPDATE contacts SET email_verification_status='verified',
                               email_verification_confidence=%s, email_verification_provider=%s,
                               email_verified_at=now() WHERE id=%s""",
                            (confidence_pct, provider_name, contact_id),
                        )
            return result
        except Exception as e:
            _log_verification(workspace_id, contact_id, email,
                             VerificationResult(email=email, result="unknown", confidence=0,
                                               raw={"provider": provider_name, "error": str(e), "local_checks": local_checks}))
            log.warning("verification provider failed", extra={"provider": provider_name, "error": str(e)})
            continue

    return VerificationResult(email=email, result="unknown", confidence=local_confidence,
                              raw={"provider": "none", "local_checks": local_checks})


def _log_verification(workspace_id: str, contact_id: str, email: str, result: VerificationResult) -> None:
    with db.get_pool().connection() as conn:
        conn.execute(
            """INSERT INTO email_verifications (workspace_id, contact_id, email, result, provider,
               local_checks, confidence)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (workspace_id, contact_id, email, result.result,
             result.raw.get("provider") if isinstance(result.raw, dict) else None,
             json.dumps(result.raw.get("local_checks", {}) if isinstance(result.raw, dict) else {}),
             result.confidence),
        )