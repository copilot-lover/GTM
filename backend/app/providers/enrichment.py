"""Enrichment provider adapters: Apollo, Hunter, Clearbit.

All implement EnrichmentProvider.enrich_company(company: dict) -> dict.
CircuitBreaker(threshold=5), retry_with_backoff(3). Fixture fallback.
Return partial data on error (never raise).
"""

import logging
import os
import httpx

from app.providers.base import EnrichmentProvider
from app.providers.fixtures import FixtureEnrichment
from app.providers.resilience import CircuitBreaker, retry_with_backoff_sync

log = logging.getLogger(__name__)

REQUIRED_FIELDS = [
    "website", "phone", "address", "city", "state", "zip",
    "employee_estimate", "tech_signals", "owner_name", "owner_title",
    "owner_email", "owner_phone", "owner_linkedin", "social_links",
]


def _merge_partial(target: dict, source: dict) -> dict:
    """Merge non-None values from source into target."""
    for k, v in source.items():
        if v is not None:
            target[k] = v
    return target


class ApolloAdapter(EnrichmentProvider):
    def __init__(self):
        self.api_key = os.getenv("APOLLO_API_KEY")
        self.base_url = "https://api.apollo.io/v1"
        self.breaker = CircuitBreaker(failure_threshold=5, reset_timeout=60.0)
        self._fixture = FixtureEnrichment()
        if not self.api_key:
            log.warning("APOLLO_API_KEY not set; will use fixture fallback")

    def enrich_company(self, company: dict) -> dict:
        company_id = company.get("id", "unknown")
        log.info("apollo enrich_company start", extra={"company_id": company_id})

        if not self.api_key:
            return self._fixture.enrich_company(company)

        def _call():
            self.breaker.check()
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            payload = self._build_payload(company)
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(f"{self.base_url}/organizations/enrich", json=payload, headers=headers)
                resp.raise_for_status()
                return resp.json()

        try:
            data = retry_with_backoff_sync(_call, attempts=3, base_delay=1.0, jitter=0.5)
            self.breaker.record_success()
            result = self._parse_response(data)
            log.info("apollo enrich_company success", extra={"company_id": company_id})
            return result
        except Exception as e:
            self.breaker.record_failure()
            log.warning("apollo enrich_company failed, using fixture", extra={"company_id": company_id, "error": str(e)})
            return self._fixture.enrich_company(company)

    def _build_payload(self, company: dict) -> dict:
        payload = {}
        if company.get("website"):
            payload["domain"] = company["website"].replace("https://", "").replace("http://", "").strip("/")
        if company.get("business_name"):
            payload["name"] = company["business_name"]
        if company.get("phone"):
            payload["phone"] = company["phone"]
        return payload

    def _parse_response(self, data: dict) -> dict:
        org = data.get("organization", {})
        result = {}
        result["website"] = org.get("website_url")
        result["phone"] = org.get("phone")
        result["address"] = org.get("raw_address")
        result["city"] = org.get("city")
        result["state"] = org.get("state")
        result["zip"] = org.get("postal_code")
        result["employee_estimate"] = org.get("estimated_num_employees")
        result["tech_signals"] = org.get("technologies", [])
        result["owner_name"] = None
        result["owner_title"] = None
        result["owner_email"] = None
        result["owner_phone"] = None
        result["owner_linkedin"] = None
        result["social_links"] = {}
        if org.get("linkedin_url"):
            result["social_links"]["linkedin"] = org["linkedin_url"]
        if org.get("twitter_url"):
            result["social_links"]["twitter"] = org["twitter_url"]
        if org.get("facebook_url"):
            result["social_links"]["facebook"] = org["facebook_url"]
        return {k: v for k, v in result.items() if v is not None}


class HunterAdapter(EnrichmentProvider):
    def __init__(self):
        self.api_key = os.getenv("HUNTER_API_KEY")
        self.base_url = "https://api.hunter.io/v2"
        self.breaker = CircuitBreaker(failure_threshold=5, reset_timeout=60.0)
        self._fixture = FixtureEnrichment()
        if not self.api_key:
            log.warning("HUNTER_API_KEY not set; will use fixture fallback")

    def enrich_company(self, company: dict) -> dict:
        company_id = company.get("id", "unknown")
        log.info("hunter enrich_company start", extra={"company_id": company_id})

        if not self.api_key:
            return self._fixture.enrich_company(company)

        def _call():
            self.breaker.check()
            domain = company.get("website", "").replace("https://", "").replace("http://", "").strip("/")
            if not domain:
                raise ValueError("no domain for hunter enrichment")
            params = {"domain": domain, "api_key": self.api_key}
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(f"{self.base_url}/domain-search", params=params)
                resp.raise_for_status()
                return resp.json()

        try:
            data = retry_with_backoff_sync(_call, attempts=3, base_delay=1.0, jitter=0.5)
            self.breaker.record_success()
            result = self._parse_response(data)
            log.info("hunter enrich_company success", extra={"company_id": company_id})
            return result
        except Exception as e:
            self.breaker.record_failure()
            log.warning("hunter enrich_company failed, using fixture", extra={"company_id": company_id, "error": str(e)})
            return self._fixture.enrich_company(company)

    def _parse_response(self, data: dict) -> dict:
        result = {}
        domain_data = data.get("data", {})
        result["website"] = f"https://{domain_data.get('domain')}" if domain_data.get("domain") else None
        pattern = domain_data.get("pattern")
        if pattern:
            result["owner_email"] = pattern
        emails = domain_data.get("emails", [])
        if emails:
            first = emails[0]
            result["owner_name"] = f"{first.get('first_name', '')} {first.get('last_name', '')}".strip() or None
            result["owner_title"] = first.get("position")
            result["owner_phone"] = first.get("phone_number")
            result["owner_linkedin"] = first.get("linkedin")
        result["employee_estimate"] = domain_data.get("organization", {}).get("employees")
        result["tech_signals"] = []
        result["address"] = domain_data.get("organization", {}).get("address")
        result["city"] = domain_data.get("organization", {}).get("city")
        result["state"] = domain_data.get("organization", {}).get("state")
        result["zip"] = domain_data.get("organization", {}).get("postal_code")
        result["social_links"] = {}
        return {k: v for k, v in result.items() if v is not None}


class ClearbitAdapter(EnrichmentProvider):
    def __init__(self):
        self.api_key = os.getenv("CLEARBIT_API_KEY")
        self.base_url = "https://company.clearbit.com/v2"
        self.breaker = CircuitBreaker(failure_threshold=5, reset_timeout=60.0)
        self._fixture = FixtureEnrichment()
        if not self.api_key:
            log.warning("CLEARBIT_API_KEY not set; will use fixture fallback")

    def enrich_company(self, company: dict) -> dict:
        company_id = company.get("id", "unknown")
        log.info("clearbit enrich_company start", extra={"company_id": company_id})

        if not self.api_key:
            return self._fixture.enrich_company(company)

        def _call():
            self.breaker.check()
            domain = company.get("website", "").replace("https://", "").replace("http://", "").strip("/")
            if not domain:
                raise ValueError("no domain for clearbit enrichment")
            headers = {"Authorization": f"Bearer {self.api_key}"}
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(f"{self.base_url}/companies/find", params={"domain": domain}, headers=headers)
                if resp.status_code == 404:
                    return {}
                resp.raise_for_status()
                return resp.json()

        try:
            data = retry_with_backoff_sync(_call, attempts=3, base_delay=1.0, jitter=0.5)
            self.breaker.record_success()
            result = self._parse_response(data)
            log.info("clearbit enrich_company success", extra={"company_id": company_id})
            return result
        except Exception as e:
            self.breaker.record_failure()
            log.warning("clearbit enrich_company failed, using fixture", extra={"company_id": company_id, "error": str(e)})
            return self._fixture.enrich_company(company)

    def _parse_response(self, data: dict) -> dict:
        result = {}
        result["website"] = f"https://{data.get('domain')}" if data.get("domain") else None
        result["phone"] = data.get("phone")
        result["address"] = data.get("address")
        result["city"] = data.get("city")
        result["state"] = data.get("state")
        result["zip"] = data.get("postal_code")
        metrics = data.get("metrics", {})
        result["employee_estimate"] = metrics.get("employees")
        result["tech_signals"] = data.get("tech", [])
        result["owner_name"] = None
        result["owner_title"] = None
        result["owner_email"] = None
        result["owner_phone"] = None
        result["owner_linkedin"] = None
        result["social_links"] = {}
        if data.get("linkedin", {}).get("handle"):
            result["social_links"]["linkedin"] = f"https://linkedin.com/company/{data['linkedin']['handle']}"
        if data.get("twitter", {}).get("handle"):
            result["social_links"]["twitter"] = f"https://twitter.com/{data['twitter']['handle']}"
        if data.get("facebook", {}).get("handle"):
            result["social_links"]["facebook"] = f"https://facebook.com/{data['facebook']['handle']}"
        return {k: v for k, v in result.items() if v is not None}


def register_providers():
    from app.providers import registry
    try:
        registry.register("apollo", ApolloAdapter())
    except Exception as e:
        log.warning(f"ApolloAdapter registration failed: {e}")
    try:
        registry.register("hunter", HunterAdapter())
    except Exception as e:
        log.warning(f"HunterAdapter registration failed: {e}")
    try:
        registry.register("clearbit", ClearbitAdapter())
    except Exception as e:
        log.warning(f"ClearbitAdapter registration failed: {e}")