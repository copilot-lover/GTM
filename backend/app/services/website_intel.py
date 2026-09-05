"""Website Intelligence Service — WS-D: scraping + detection.

Fetches company website via scraping service, parses for booking CTAs, chat widgets,
phones, forms, SSL, viewport, TTFB, after-hours messaging, and tech stack signatures.
Writes to companies.website_findings/tech_signals jsonb.
"""

import json
import logging
import re
from dataclasses import dataclass

import psycopg.rows

import app.db as db
from app.providers import ProviderUnavailable, get
from app.providers.base import LLMProvider, LLMResponse
from app.services import scraping

log = logging.getLogger(__name__)

TECH_STACK_PATTERNS = {
    "servicetitan": [
        r"servicetitan\.com",
        r"st\.servicetitan\.com",
        r"servicetitan\.js",
    ],
    "housecall_pro": [
        r"housecallpro\.com",
        r"housecall\.pro",
        r"hcp\.js",
    ],
    "jobber": [
        r"jobber\.com",
        r"getjobber\.com",
        r"jobber\.js",
    ],
    "workiz": [
        r"workiz\.com",
        r"workiz\.js",
    ],
    "hubspot": [
        r"js\.hsforms\.net",
        r"hs-scripts\.com",
        r"hubspot\.com",
        r"_hsq\.push",
    ],
    "salesforce": [
        r"salesforce\.com",
        r"sfdc\.js",
        r"force\.com",
    ],
    "calendly": [
        r"calendly\.com",
        r"assets\.calendly\.com",
    ],
    "google_analytics": [
        r"google-analytics\.com",
        r"googletagmanager\.com",
        r"gtag\(",
        r"ga\(",
    ],
    "facebook_pixel": [
        r"connect\.facebook\.net",
        r"fbq\(",
        r"facebook\.net/tr",
    ],
}

WEBSITE_FINDINGS_SCHEMA = {
    "booking_cta": {"text": "", "href": ""},
    "chat_widget": "",
    "phone_visible": {"text": "", "href": ""},
    "forms": [],
    "ssl_valid": False,
    "mobile_viewport_meta": False,
    "ttfb_ms": 0,
    "after_hours_messaging": False,
    "after_hours_gap": False,
    "no_online_booking": False,
    "weak_website": False,
}

@dataclass
class WebsiteIntelResult:
    website_findings: dict
    tech_signals: dict

def _get_llm() -> LLMProvider | None:
    try:
        return get("llm")
    except ProviderUnavailable:
        return None


def _fetch_via_scraper(website: str) -> scraping.ScrapeResult | None:
    """Call the internal scrape endpoint (or direct service) with stealth=True."""
    try:
        return scraping.scrape(website, stealth=True)
    except Exception as e:
        log.warning(f"scrape failed for {website}: {e}")
        return None


def _extract_booking_cta(html: str) -> dict[str, str]:
    """Find booking/schedule CTA buttons/links."""
    patterns = [
        (r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>([^<]*(?:book|schedule|appoint|reserve)[^<]*)</a>', "href", "text"),
        (r'<button[^>]*>([^<]*(?:book|schedule|appoint|reserve)[^<]*)</button>', None, "text"),
        (r'<a[^>]+class=["\'][^"\']*(?:btn|cta|book|schedule)[^"\']*["\'][^>]*href=["\']([^"\']+)["\'][^>]*>([^<]*)</a>', "href", "text"),
    ]
    for pattern, href_group, text_group in patterns:
        matches = re.finditer(pattern, html, re.IGNORECASE)
        for m in matches:
            href = m.group(href_group) if href_group else ""
            text = m.group(text_group).strip() if text_group else ""
            if text and len(text) > 3:
                return {"text": text[:200], "href": href}
    return {"text": "", "href": ""}


def _detect_chat_widget(html: str) -> str:
    """Detect chat widget service from script/src patterns."""
    chat_patterns = {
        "intercom": [r"intercom\.io", r"intercom\.js"],
        "drift": [r"drift\.com", r"js\.driftt\.com"],
        "hubspot": [r"hubspot\.com.*chat", r"hs-chat"],
        "zendesk": [r"zendesk\.com", r"zopim\.com"],
        "tawk": [r"tawk\.to"],
        "crisp": [r"crisp\.chat"],
        "freshchat": [r"freshchat\.com"],
        "tidio": [r"tidio\.com"],
    }
    for service, patterns in chat_patterns.items():
        for p in patterns:
            if re.search(p, html, re.IGNORECASE):
                return service
    return ""


def _extract_phone_visible(html: str) -> dict[str, str]:
    """Find visible phone numbers in tel: links or clickable elements."""
    tel_match = re.search(r'href=["\']tel:([^"\']+)["\']', html, re.IGNORECASE)
    if tel_match:
        phone = tel_match.group(1)
        return {"text": phone, "href": f"tel:{phone}"}
    return {"text": "", "href": ""}


def _extract_forms(html: str) -> list[dict]:
    """Extract form actions and field names."""
    forms = []
    form_matches = re.finditer(r'<form[^>]*action=["\']([^"\']*)["\'][^>]*>(.*?)</form>', html, re.IGNORECASE | re.DOTALL)
    for m in form_matches:
        action = m.group(1)
        form_html = m.group(2)
        fields = re.findall(r'<input[^>]+name=["\']([^"\']+)["\']', form_html, re.IGNORECASE)
        fields += re.findall(r'<textarea[^>]+name=["\']([^"\']+)["\']', form_html, re.IGNORECASE)
        fields += re.findall(r'<select[^>]+name=["\']([^"\']+)["\']', form_html, re.IGNORECASE)
        forms.append({"action": action, "fields": fields})
    return forms


def _check_ssl_valid(scrape_result: scraping.ScrapeResult) -> bool:
    """Check if SSL is valid based on scrape response."""
    return scrape_result.status == 200 and scrape_result.url.startswith("https://")


def _check_mobile_viewport(html: str) -> bool:
    """Check for mobile viewport meta tag."""
    return bool(re.search(r'<meta[^>]+name=["\']viewport["\'][^>]*content=["\'][^"\']*width=device-width', html, re.IGNORECASE))


def _detect_after_hours_messaging(html: str) -> bool:
    """Check footer/banner for after-hours messaging keywords."""
    footer_section = re.search(r'<footer[^>]*>(.*?)</footer>', html, re.IGNORECASE | re.DOTALL)
    banner_section = re.search(r'(?:banner|alert|notice)[^>]*>(.*?)</', html, re.IGNORECASE | re.DOTALL)
    search_text = ""
    if footer_section:
        search_text += footer_section.group(1)
    if banner_section:
        search_text += " " + banner_section.group(1)
    search_text = search_text.lower()
    keywords = ["after hours", "after-hours", "closed", "emergency", "24/7", "24 hour", "on call", "on-call"]
    return any(k in search_text for k in keywords)


def _detect_tech_stack(html: str) -> dict[str, bool]:
    """Detect tech stack signatures from script/src patterns."""
    detected = {}
    for tech, patterns in TECH_STACK_PATTERNS.items():
        detected[tech] = any(re.search(p, html, re.IGNORECASE) for p in patterns)
    return detected


def _llm_summarize_findings(html: str, deterministic_findings: dict) -> dict:
    """Use LLM (cheap tier) to summarize findings if HTML is complex."""
    llm = _get_llm()
    if not llm:
        return deterministic_findings

    system = (
        "You are a website analyzer for Orbit (AI receptionist agency). "
        "Given HTML and deterministic findings, return ONLY valid JSON with these keys: "
        "booking_cta {text, href}, chat_widget (service name or empty), "
        "phone_visible {text, href}, forms [{action, fields[]}], "
        "ssl_valid (bool), mobile_viewport_meta (bool), ttfb_ms (int), "
        "after_hours_messaging (bool), tech_signals {servicetitan, housecall_pro, "
        "jobber, workiz, hubspot, salesforce, calendly, google_analytics, facebook_pixel}. "
        "Fail closed: unclear -> false/empty."
    )
    user = f"Deterministic findings: {json.dumps(deterministic_findings)}\n\nHTML (truncated): {html[:8000]}"
    try:
        resp: LLMResponse = llm.complete(system, user, model_tier="cheap")
        import json as _json
        return _json.loads(resp.content)
    except Exception as e:
        log.warning(f"LLM summarize failed: {e}")
        return deterministic_findings


def fetch_website_intel(company_id: str) -> WebsiteIntelResult:
    """Main entry: fetch website intel for a company, write to DB, return result."""
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        company = conn.execute(
            "SELECT id, workspace_id, business_name, website FROM companies WHERE id=%s",
            (company_id,),
        ).fetchone()

    if not company:
        raise ValueError(f"Company {company_id} not found")

    website = company.get("website")
    if not website:
        empty_result = WebsiteIntelResult(
            website_findings=WEBSITE_FINDINGS_SCHEMA.copy(),
            tech_signals={k: False for k in TECH_STACK_PATTERNS.keys()},
        )
        _write_findings(company_id, empty_result)
        return empty_result

    scrape_result = _fetch_via_scraper(website)
    if not scrape_result:
        empty_result = WebsiteIntelResult(
            website_findings=WEBSITE_FINDINGS_SCHEMA.copy(),
            tech_signals={k: False for k in TECH_STACK_PATTERNS.keys()},
        )
        _write_findings(company_id, empty_result)
        return empty_result

    html = scrape_result.body

    deterministic_findings = {
        "booking_cta": _extract_booking_cta(html),
        "chat_widget": _detect_chat_widget(html),
        "phone_visible": _extract_phone_visible(html),
        "forms": _extract_forms(html),
        "ssl_valid": _check_ssl_valid(scrape_result),
        "mobile_viewport_meta": _check_mobile_viewport(html),
        "ttfb_ms": getattr(scrape_result, "ttfb_ms", 0) or 0,
        "after_hours_messaging": _detect_after_hours_messaging(html),
    }

    tech_signals = _detect_tech_stack(html)

    # Derive gap signals (§16)
    booking_cta = deterministic_findings.get("booking_cta", {})
    has_booking_cta = bool(booking_cta.get("text"))
    phone_visible = deterministic_findings.get("phone_visible", {})
    has_phone = bool(phone_visible.get("text"))
    after_hours = deterministic_findings.get("after_hours_messaging", False)

    deterministic_findings["after_hours_gap"] = has_phone and not after_hours
    deterministic_findings["no_online_booking"] = not has_booking_cta
    deterministic_findings["weak_website"] = (
        not deterministic_findings.get("ssl_valid", False)
        or (deterministic_findings.get("ttfb_ms", 0) or 0) > 3000
        or not deterministic_findings.get("mobile_viewport_meta", False)
    )

    final_findings = _llm_summarize_findings(html, deterministic_findings)

    result = WebsiteIntelResult(
        website_findings=final_findings,
        tech_signals=tech_signals,
    )

    _write_findings(company_id, result)
    return result


def _write_findings(company_id: str, result: WebsiteIntelResult) -> None:
    with db.get_pool().connection() as conn:
        # Write tech_signals to companies (column exists)
        conn.execute(
            """UPDATE companies SET tech_signals=%s, updated_at=now() WHERE id=%s""",
            (json.dumps(result.tech_signals), company_id),
        )
        # Write website_findings to leads if a lead exists for this company
        conn.execute(
            """UPDATE leads SET website_findings=%s, updated_at=now()
               WHERE company_id=%s""",
            (json.dumps(result.website_findings), company_id),
        )