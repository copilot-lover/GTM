"""Job source adapters implementing JobSourceProvider protocol.
Each adapter wraps an external job API with retry, circuit breaker, and fixture fallback.
"""

import logging
import os
import httpx

from app.providers.base import JobSourceProvider, registry
from app.providers.fixtures import FixtureJobSource
from app.providers.resilience import CircuitBreaker, retry_with_backoff_sync

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15.0
MAX_RETRIES = 3
CIRCUIT_THRESHOLD = 5


class BaseJobAdapter(JobSourceProvider):
    """Base class with shared resilience + fixture fallback logic."""

    def __init__(
        self,
        provider_name: str,
        api_key_env: str,
        base_url: str,
        headers_factory: callable,
        request_factory: callable,
        response_parser: callable,
    ):
        self.provider_name = provider_name
        self.api_key_env = api_key_env
        self.base_url = base_url
        self._headers_factory = headers_factory
        self._request_factory = request_factory
        self._response_parser = response_parser
        self._circuit = CircuitBreaker(failure_threshold=CIRCUIT_THRESHOLD, reset_timeout=60.0)
        self._fixture: FixtureJobSource | None = None
        self._use_fixture = False

        api_key = os.environ.get(api_key_env)
        if not api_key:
            log.warning(f"{provider_name}: {api_key_env} not set, using fixture mode")
            self._use_fixture = True
            self._fixture = FixtureJobSource()
        else:
            self._api_key = api_key

    def search(self, query: str, filters: dict | None = None) -> list[dict]:
        if self._use_fixture:
            return self._fixture.search(query, filters)

        def _do_search():
            self._circuit.check()
            headers = self._headers_factory(self._api_key)
            payload = self._request_factory(query, filters)
            with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
                resp = client.post(f"{self.base_url}/search", headers=headers, json=payload)
                resp.raise_for_status()
                return self._response_parser(resp.json())

        try:
            results = retry_with_backoff_sync(_do_search, attempts=MAX_RETRIES)
            self._circuit.record_success()
            log.info(f"{self.provider_name} search: query='{query}' filters={filters} count={len(results)}")
            return results
        except Exception as e:
            self._circuit.record_failure()
            log.error(f"{self.provider_name} search failed: {e}")
            return []


class JobsPipeAdapter(BaseJobAdapter):
    """JobsPipe.com API adapter (primary tier)."""

    def __init__(self):
        super().__init__(
            provider_name="jobspipe",
            api_key_env="JOBSPIPE_API_KEY",
            base_url="https://api.jobspipe.com/v1",
            headers_factory=lambda k: {"Authorization": f"Bearer {k}", "Content-Type": "application/json"},
            request_factory=lambda q, f: {
                "query": q,
                "filters": f or {},
            },
            response_parser=lambda data: [
                {
                    "source_job_id": str(item.get("id", "")),
                    "title": item.get("title", ""),
                    "description": item.get("description", ""),
                    "company_name": item.get("company", {}).get("name", ""),
                    "company_city": item.get("location", {}).get("city", ""),
                    "company_state": item.get("location", {}).get("state", ""),
                    "job_url": item.get("url", ""),
                    "posted_at": item.get("posted_date"),
                    "source": "jobspipe",
                }
                for item in data.get("jobs", [])
            ],
        )


class TheirStackAdapter(BaseJobAdapter):
    """TheirStack API adapter."""

    def __init__(self):
        super().__init__(
            provider_name="theirstack",
            api_key_env="THEIRSTACK_API_KEY",
            base_url="https://api.theirstack.com/v1",
            headers_factory=lambda k: {"Authorization": f"Bearer {k}", "Content-Type": "application/json"},
            request_factory=lambda q, f: {
                "job_title_or": q,
                "location": (f or {}).get("location", []),
                "posted_at_max_age_days": (f or {}).get("posted_after"),
            },
            response_parser=lambda data: [
                {
                    "source_job_id": str(item.get("id", "")),
                    "title": item.get("job_title", ""),
                    "description": item.get("description", ""),
                    "company_name": item.get("company_name", ""),
                    "company_city": item.get("location", {}).get("city", ""),
                    "company_state": item.get("location", {}).get("state", ""),
                    "job_url": item.get("job_url", ""),
                    "posted_at": item.get("posted_at"),
                    "source": "theirstack",
                }
                for item in data.get("data", [])
            ],
        )


class JSearchAdapter(BaseJobAdapter):
    """JSearch (RapidAPI) adapter."""

    def __init__(self):
        super().__init__(
            provider_name="jsearch",
            api_key_env="JSEARCH_API_KEY",
            base_url="https://jsearch.p.rapidapi.com",
            headers_factory=lambda k: {
                "X-RapidAPI-Key": k,
                "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
                "Content-Type": "application/json",
            },
            request_factory=lambda q, f: {
                "query": q,
                "page": "1",
                "num_pages": "1",
            },
            response_parser=lambda data: [
                {
                    "source_job_id": str(item.get("job_id", "")),
                    "title": item.get("job_title", ""),
                    "description": item.get("job_description", ""),
                    "company_name": item.get("employer_name", ""),
                    "company_city": item.get("job_city", ""),
                    "company_state": item.get("job_state", ""),
                    "job_url": item.get("job_apply_link", ""),
                    "posted_at": item.get("job_posted_at_datetime_utc"),
                    "source": "jsearch",
                }
                for item in data.get("data", [])
            ],
        )


class FantasticJobsAdapter(BaseJobAdapter):
    """Fantastic.jobs API adapter."""

    def __init__(self):
        super().__init__(
            provider_name="fantastic_jobs",
            api_key_env="FANTASTIC_JOBS_API_KEY",
            base_url="https://api.fantastic.jobs/v1",
            headers_factory=lambda k: {"Authorization": f"Bearer {k}", "Content-Type": "application/json"},
            request_factory=lambda q, f: {
                "q": q,
                "location": (f or {}).get("location", []),
            },
            response_parser=lambda data: [
                {
                    "source_job_id": str(item.get("id", "")),
                    "title": item.get("title", ""),
                    "description": item.get("description", ""),
                    "company_name": item.get("company", {}).get("name", ""),
                    "company_city": item.get("location", {}).get("city", ""),
                    "company_state": item.get("location", {}).get("state", ""),
                    "job_url": item.get("apply_url", ""),
                    "posted_at": item.get("created_at"),
                    "source": "fantastic_jobs",
                }
                for item in data.get("jobs", [])
            ],
        )


class AdzunaAdapter(BaseJobAdapter):
    """Adzuna API adapter."""

    def __init__(self):
        super().__init__(
            provider_name="adzuna",
            api_key_env="ADZUNA_API_KEY",
            base_url="https://api.adzuna.com/v1/api/jobs",
            headers_factory=lambda k: {"Content-Type": "application/json"},
            request_factory=lambda q, f: {
                "app_id": os.environ.get("ADZUNA_APP_ID", ""),
                "app_key": k,
                "what": q,
                "where": ",".join((f or {}).get("location", [])),
                "results_per_page": 20,
            },
            response_parser=lambda data: [
                {
                    "source_job_id": str(item.get("id", "")),
                    "title": item.get("title", ""),
                    "description": item.get("description", ""),
                    "company_name": item.get("company", {}).get("display_name", ""),
                    "company_city": item.get("location", {}).get("area", ["", ""])[0] if item.get("location", {}).get("area") else "",
                    "company_state": item.get("location", {}).get("area", ["", ""])[1] if len(item.get("location", {}).get("area", [])) > 1 else "",
                    "job_url": item.get("redirect_url", ""),
                    "posted_at": item.get("created"),
                    "source": "adzuna",
                }
                for item in data.get("results", [])
            ],
        )


def register_providers() -> None:
    """Register all job source adapters with the global registry."""
    registry.register("jobspipe", JobsPipeAdapter())
    registry.register("theirstack", TheirStackAdapter())
    registry.register("jsearch", JSearchAdapter())
    registry.register("fantastic_jobs", FantasticJobsAdapter())
    registry.register("adzuna", AdzunaAdapter())


register_providers()