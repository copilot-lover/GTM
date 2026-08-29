"""Email finder provider adapter: Apollo.

Implements EmailFinderProvider.find_email(company, contact_name, title) -> dict | None.
Decision-maker ranking: owner > founder > president > gm > operations_manager > 
service_manager > office_manager > dispatcher_lead > other.
Returns highest-confidence match for highest-ranked title.
"""

import logging
import os
from typing import Any

import httpx

from app.providers.base import EmailFinderProvider, ProviderUnavailable
from app.providers.fixtures import FixtureEmailFinder
from app.providers.resilience import CircuitBreaker, retry_with_backoff_sync

log = logging.getLogger(__name__)

TITLE_RANKING = {
    "owner": 1,
    "founder": 2,
    "president": 3,
    "gm": 4,
    "general manager": 4,
    "operations_manager": 5,
    "service_manager": 6,
    "office_manager": 7,
    "dispatcher_lead": 8,
    "dispatcher": 8,
    "other": 99,
}


def rank_title(title: str | None) -> int:
    if not title:
        return 99
    t = title.lower().strip()
    for key, rank in TITLE_RANKING.items():
        if key in t:
            return rank
    return 99


class ApolloEmailFinder(EmailFinderProvider):
    def __init__(self):
        self.api_key = os.getenv("APOLLO_API_KEY")
        self.base_url = "https://api.apollo.io/v1"
        self.breaker = CircuitBreaker(failure_threshold=5, reset_timeout=60.0)
        self._fixture = FixtureEmailFinder()
        if not self.api_key:
            log.warning("APOLLO_API_KEY not set; will use fixture fallback")

    def find_email(self, company: dict, contact_name: str, title: str | None = None) -> dict | None:
        company_id = company.get("id", "unknown")
        log.info("apollo find_email start", extra={"company_id": company_id, "contact": contact_name, "title": title})

        if not self.api_key:
            result = self._fixture.find_email(company, contact_name, title)
            if result:
                result["source"] = "fixture"
            return result

        def _call():
            self.breaker.check()
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            domain = company.get("website", "").replace("https://", "").replace("http://", "").strip("/")
            if not domain:
                raise ValueError("no domain for email finder")
            payload = {
                "q_organization_domains": [domain],
                "q_person_name": contact_name,
                "page": 1,
                "per_page": 20,
            }
            if title:
                payload["q_person_titles"] = [title]
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(f"{self.base_url}/mixed_people/search", json=payload, headers=headers)
                resp.raise_for_status()
                return resp.json()

        try:
            data = retry_with_backoff_sync(_call, attempts=3, base_delay=1.0, jitter=0.5)
            self.breaker.record_success()
            result = self._parse_response(data, title)
            if result:
                result["source"] = "apollo"
            log.info("apollo find_email success", extra={"company_id": company_id, "found": result is not None})
            return result
        except Exception as e:
            self.breaker.record_failure()
            log.warning("apollo find_email failed, using fixture", extra={"company_id": company_id, "error": str(e)})
            result = self._fixture.find_email(company, contact_name, title)
            if result:
                result["source"] = "fixture"
            return result

    def _parse_response(self, data: dict, requested_title: str | None) -> dict | None:
        people = data.get("people", [])
        if not people:
            return None

        best = None
        best_rank = 99
        best_confidence = 0

        for person in people:
            email = person.get("email")
            if not email:
                continue
            person_title = person.get("title", "")
            rank = rank_title(person_title)
            confidence = person.get("email_confidence", 0) or 0

            if rank < best_rank or (rank == best_rank and confidence > best_confidence):
                best = {
                    "email": email,
                    "confidence": min(confidence / 100.0, 1.0),
                    "title": person_title,
                    "name": f"{person.get('first_name', '')} {person.get('last_name', '')}".strip(),
                }
                best_rank = rank
                best_confidence = confidence

        return best


def register_providers():
    from app.providers import registry
    try:
        registry.register("apollo_email_finder", ApolloEmailFinder())
    except Exception as e:
        log.warning(f"ApolloEmailFinder registration failed: {e}")