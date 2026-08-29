"""In-memory fixture providers for tests A-H.

Fixture mode selection: tests register these against app.providers.registry
via `registry.override(name, instance)` (or a pytest fixture that does so);
overrides shadow real registrations and are cleared with
`registry.clear_overrides()`. Real providers requiring API keys raise
ProviderUnavailable at construction, so tests never touch the network.

Failure injection: FixtureEmailSender.fail_next counts down remaining sends
that return SendResult(ok=False); FixtureLLM raises RuntimeError once when
fail_once=True. Use these to drive retry/circuit-breaker paths.
"""

from app.providers.base import (
    CalendarProvider,
    CRMProvider,
    EmailFinderProvider,
    EmailSendingProvider,
    EmailVerificationProvider,
    EnrichmentProvider,
    JobSourceProvider,
    LLMProvider,
    LLMResponse,
    SendResult,
    VerificationResult,
)


class FixtureLLM(LLMProvider):
    """scripts maps a marker substring to canned JSON content; unmatched
    prompts get a deterministic echo of the system+user text."""

    model_used = "fixture-llm"

    def __init__(self, scripts: dict[str, str] | None = None,
                 fail_once: bool = False):
        self.scripts = scripts or {}
        self.fail_once = fail_once
        self.calls: list[dict] = []

    def complete(self, system: str, user: str,
                 model_tier: str = "cheap") -> LLMResponse:
        self.calls.append({"system": system, "user": user, "tier": model_tier})
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("fixture llm transient failure")
        prompt = system + "\n" + user
        for marker, content in self.scripts.items():
            if marker in prompt:
                return LLMResponse(content=content, model_used=self.model_used)
        return LLMResponse(content=prompt, model_used=self.model_used)


class FixtureJobSource(JobSourceProvider):
    """Returns seeded postings; optionally filters on title substring."""

    def __init__(self, postings: list[dict] | None = None):
        self.postings = postings or []
        self.searches: list[tuple[str, dict | None]] = []

    def search(self, query: str, filters: dict | None = None) -> list[dict]:
        self.searches.append((query, filters))
        title = (filters or {}).get("title_contains")
        if title:
            return [p for p in self.postings if title.lower() in p.get("title", "").lower()]
        return list(self.postings)


class FixtureVerifier(EmailVerificationProvider):
    def __init__(self, result: str = "valid", confidence: float = 0.95):
        self.result = result
        self.confidence = confidence
        self.verified: list[str] = []

    def verify(self, email: str) -> VerificationResult:
        self.verified.append(email)
        return VerificationResult(
            email=email, result=self.result,
            confidence=self.confidence, raw={"provider": "fixture"},
        )


class FixtureEnrichment(EnrichmentProvider):
    def __init__(self, extra_fields: dict | None = None):
        self.extra_fields = extra_fields or {"employee_estimate": 12}
        self.enriched: list[dict] = []

    def enrich_company(self, company: dict) -> dict:
        self.enriched.append(company)
        return {**company, **self.extra_fields}


class FixtureEmailSender(EmailSendingProvider):
    """Records sends in memory; fail_next injects N failures before success."""

    def __init__(self, fail_next: int = 0):
        self.sent: list[dict] = []
        self.fail_next = fail_next

    def send(self, *, from_addr: str, to: str, subject: str, body_text: str,
             body_html: str | None = None,
             message_id: str | None = None) -> SendResult:
        record = {
            "from_addr": from_addr, "to": to, "subject": subject,
            "body_text": body_text, "message_id": message_id,
        }
        if self.fail_next > 0:
            self.fail_next -= 1
            self.sent.append(record)
            return SendResult(ok=False, error="injected failure")
        self.sent.append(record)
        return SendResult(
            ok=True,
            provider_message_id=f"fixture-{len(self.sent)}",
        )


class FixtureEmailFinder(EmailFinderProvider):
    def __init__(self, addresses: dict[tuple[str, str], str] | None = None):
        self.addresses = addresses or {}
        self.misses: list[tuple[str, str]] = []

    def find_email(self, company: dict, contact_name: str,
                   title: str | None = None) -> dict | None:
        key = (company.get("business_name", ""), contact_name)
        email = self.addresses.get(key)
        if not email:
            domain = (company.get("website") or "").replace("https://", "").strip("/")
            email = f"{contact_name.split()[0].lower()}@{domain or 'example.com'}"
        return {"email": email, "confidence": 0.9}


class FixtureCRM(CRMProvider):
    """In-memory CRM with deterministic stores + optional failure injection."""

    def __init__(self, fail_on: set[str] | None = None):
        self.companies: dict[str, dict] = {}
        self.contacts: dict[str, dict] = {}
        self.opportunities: dict[str, dict] = {}
        self.fail_on = fail_on or set()
        self.calls: list[dict] = []

    def _maybe_fail(self, operation: str):
        if operation in self.fail_on:
            raise RuntimeError(f"fixture crm {operation} failure")

    def upsert_company(self, company_data: dict) -> dict | None:
        self.calls.append({"op": "upsert_company", "data": company_data})
        self._maybe_fail("upsert_company")
        key = company_data.get("id") or company_data.get("business_name")
        if key:
            self.companies[key] = {**self.companies.get(key, {}), **company_data}
            return self.companies[key]
        return None

    def upsert_contact(self, contact_data: dict) -> dict | None:
        self.calls.append({"op": "upsert_contact", "data": contact_data})
        self._maybe_fail("upsert_contact")
        key = contact_data.get("id") or contact_data.get("email")
        if key:
            self.contacts[key] = {**self.contacts.get(key, {}), **contact_data}
            return self.contacts[key]
        return None

    def create_opportunity(self, opp_data: dict) -> dict | None:
        self.calls.append({"op": "create_opportunity", "data": opp_data})
        self._maybe_fail("create_opportunity")
        key = opp_data.get("id") or f"opp-{len(self.opportunities)+1}"
        self.opportunities[key] = {**opp_data, "id": key}
        return self.opportunities[key]

    def get_contact(self, contact_id: str) -> dict | None:
        self.calls.append({"op": "get_contact", "contact_id": contact_id})
        self._maybe_fail("get_contact")
        return self.contacts.get(contact_id)

    def search_contacts(self, query: str) -> dict | None:
        self.calls.append({"op": "search_contacts", "query": query})
        self._maybe_fail("search_contacts")
        results = [
            c for c in self.contacts.values()
            if query.lower() in (c.get("name", "") + c.get("email", "") + c.get("company", "")).lower()
        ]
        return {"results": results} if results else None


class FixtureCalendar(CalendarProvider):
    """In-memory calendar with deterministic availability + optional failure injection."""

    def __init__(self, fail_on: set[str] | None = None):
        self.events: list[dict] = []
        self.availability: dict[str, list[dict]] = {}
        self.fail_on = fail_on or set()
        self.calls: list[dict] = []

    def _maybe_fail(self, operation: str):
        if operation in self.fail_on:
            raise RuntimeError(f"fixture calendar {operation} failure")

    def create_event(self, event_data: dict) -> dict | None:
        self.calls.append({"op": "create_event", "data": event_data})
        self._maybe_fail("create_event")
        event = {**event_data, "id": event_data.get("id") or f"evt-{len(self.events)+1}"}
        self.events.append(event)
        return event

    def get_availability(self, start: str, end: str) -> dict | None:
        self.calls.append({"op": "get_availability", "start": start, "end": end})
        self._maybe_fail("get_availability")
        key = f"{start}:{end}"
        if key in self.availability:
            return {"slots": self.availability[key]}
        default_slots = [
            {"start": start, "end": end, "duration_minutes": 30},
        ]
        return {"slots": default_slots}

    def book_slot(self, slot: dict, contact: dict) -> dict | None:
        self.calls.append({"op": "book_slot", "slot": slot, "contact": contact})
        self._maybe_fail("book_slot")
        booking = {
            "id": f"booking-{len(self.events)+1}",
            "slot": slot,
            "contact": contact,
            "status": "confirmed",
        }
        self.events.append(booking)
        return booking
