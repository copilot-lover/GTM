"""Durable Postgres job queue with SKIP LOCKED claiming and worker pools.

Priority ordering: priority ASC — 0 is the most urgent (P0), 5 the least.
Failed jobs retry with exponential backoff (base * 2^attempts ± jitter) by
returning to QUEUED with a future run_at; once attempts >= max_attempts they
land in DEAD_LETTER.
"""

import asyncio
import json
import random

import psycopg.rows

import app.db as db
from app.config import get_settings
from app.providers.resilience import AsyncRateLimiter
from app.providers import registry, ProviderUnavailable
from app.services import hiring_signals, enrichment, website_intel, research, opportunity

RETRY_BASE_DELAY = 2.0
RETRY_JITTER = 1.0

_HANDLERS: dict[tuple[str, str], object] = {}


def worker(pool: str, type_: str):
    """Register an async-or-sync handler for a (pool, type) pair."""

    def deco(fn):
        _HANDLERS[(pool, type_)] = fn
        return fn

    return deco


def _parse_json_dict(raw: str) -> dict:
    return json.loads(raw)


def enqueue(
    *,
    type: str,
    pool: str,
    priority: int = 3,
    payload: dict | None = None,
    idempotency_key: str | None = None,
    max_attempts: int = 3,
    run_at=None,
    workspace_id: str | None = None,
    provider: str | None = None,
) -> dict:
    """Insert a job; a duplicate idempotency_key returns the existing row."""
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        return conn.execute(
            """INSERT INTO jobs (type, pool, priority, payload, idempotency_key,
                   max_attempts, run_at, workspace_id, provider)
               VALUES (%s,%s,%s,%s,%s,%s,COALESCE(%s, now()),%s,%s)
               ON CONFLICT (idempotency_key) DO UPDATE SET id = jobs.id
               RETURNING *""",
            (
                type, pool, priority, json.dumps(payload or {}),
                idempotency_key, max_attempts, run_at, workspace_id, provider,
            ),
        ).fetchone()


def claim_next(pool: str) -> dict | None:
    """Atomically claim the most urgent runnable job in the pool."""
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        return conn.execute(
            """UPDATE jobs SET status='RUNNING', attempts=attempts+1, started_at=now()
               WHERE id = (
                   SELECT id FROM jobs
                   WHERE pool=%s AND status='QUEUED' AND run_at <= now()
                   ORDER BY priority ASC, run_at ASC
                   LIMIT 1
                   FOR UPDATE SKIP LOCKED
               ) RETURNING *""",
            (pool,),
        ).fetchone()


def complete(job_id: str, result: dict | None = None) -> None:
    with db.get_pool().connection() as conn:
        conn.execute(
            """UPDATE jobs SET status='COMPLETED', result=%s,
                   completed_at=now(), error=NULL WHERE id=%s""",
            (json.dumps(result or {}), job_id),
        )


def fail(job_id: str, error: str, *, base_delay: float = RETRY_BASE_DELAY,
         jitter: float = RETRY_JITTER) -> dict | None:
    """Record a failure: DEAD_LETTER when attempts exhausted, else QUEUED
    again with run_at pushed out by exponential backoff."""
    row = get_job(job_id)
    attempts = int(row["attempts"]) if row else 0
    delay = max(0.0, base_delay * (2 ** attempts) + random.uniform(-jitter, jitter))
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        return conn.execute(
            """UPDATE jobs SET
                   status = CASE WHEN attempts >= max_attempts
                                 THEN 'DEAD_LETTER' ELSE 'QUEUED' END,
                   completed_at = CASE WHEN attempts >= max_attempts THEN now() END,
                   error = %s,
                   run_at = CASE WHEN attempts < max_attempts
                                 THEN now() + make_interval(secs => %s)
                                 ELSE run_at END
               WHERE id=%s RETURNING *""",
            (error, delay, job_id),
        ).fetchone()


def get_job(job_id: str) -> dict | None:
    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        return conn.execute("SELECT * FROM jobs WHERE id=%s", (job_id,)).fetchone()


class WorkerSupervisor:
    """Runs one claim/dispatch loop per pool.

    Pools come from settings.worker_pools_json ({pool: concurrency}).
    Per-provider in-flight caps come from settings.provider_concurrency_json
    ({provider_name: max_concurrency}) via resilience.AsyncRateLimiter.
    """

    def __init__(self, pools: dict[str, int] | None = None,
                 poll_interval: float = 1.0):
        if pools is None:
            pools = _parse_json_dict(get_settings().worker_pools_json)
        self.pools = {k: int(v) for k, v in pools.items()}
        self.poll_interval = poll_interval
        self._tasks: list[asyncio.Task] = []
        self._provider_limiters: dict[str, AsyncRateLimiter] = {}
        self._provider_limits: dict[str, int] = _parse_json_dict(
            get_settings().provider_concurrency_json
        )

    def _limiter_for(self, provider: str | None) -> AsyncRateLimiter | None:
        if not provider or provider not in self._provider_limits:
            return None
        if provider not in self._provider_limiters:
            self._provider_limiters[provider] = AsyncRateLimiter(
                self._provider_limits[provider]
            )
        return self._provider_limiters[provider]

    def start(self) -> None:
        for pool_name, concurrency in self.pools.items():
            self._tasks.append(asyncio.create_task(
                self._pool_loop(pool_name, concurrency),
                name=f"orbit-worker-{pool_name}",
            ))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def run(self) -> None:
        """Start all pool loops and block until cancelled/stopped."""
        self.start()
        try:
            await asyncio.gather(*self._tasks)
        finally:
            await self.stop()

    async def _pool_loop(self, pool_name: str, concurrency: int) -> None:
        in_flight: set[asyncio.Task] = set()
        while True:
            while len(in_flight) < concurrency:
                job = await asyncio.to_thread(claim_next, pool_name)
                if job is None:
                    break
                task = asyncio.create_task(self._run_job(job))
                in_flight.add(task)
                task.add_done_callback(in_flight.discard)
            done, _ = await asyncio.wait(
                in_flight, timeout=self.poll_interval,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                in_flight.discard(task)

    async def _run_job(self, job: dict) -> None:
        key = (job["pool"], job["type"])
        handler = _HANDLERS.get(key)
        if handler is None:
            fail(str(job["id"]), f"no handler registered for pool={key[0]} type={key[1]}")
            return
        limiter = self._limiter_for(job["provider"])
        try:
            if limiter is not None:
                async with limiter:
                    result = await self._invoke(handler, job)
            else:
                result = await self._invoke(handler, job)
            complete(str(job["id"]), {"result": _plain(result)})
        except Exception as exc:
            fail(str(job["id"]), f"{type(exc).__name__}: {exc}")

    @staticmethod
    async def _invoke(handler, job: dict):
        outcome = handler(job)
        if asyncio.iscoroutine(outcome):
            outcome = await outcome
        return outcome


def _plain(value):
    if value is None or isinstance(value, (str, int, float, bool, list, dict)):
        return value
    return repr(value)


@worker("discovery", "job_discovery")
def handle_job_discovery(job: dict) -> dict:
    """Payload: {provider?: str, filters?: {title_contains: [], location: [], posted_after: str}}."""
    workspace_id = job.get("workspace_id")
    if not workspace_id:
        return {"ingested": 0, "error": "workspace_id required"}

    provider_name = job.get("payload", {}).get("provider")
    filters = job.get("payload", {}).get("filters", {})
    query = filters.get("title_contains", "") or "receptionist dispatcher customer service"

    providers_to_use = []
    if provider_name:
        try:
            providers_to_use.append((provider_name, registry.get(provider_name)))
        except ProviderUnavailable:
            return {"ingested": 0, "error": f"Provider '{provider_name}' not available"}
    else:
        for name in ("jobspipe", "theirstack", "jsearch", "fantastic_jobs", "adzuna"):
            try:
                providers_to_use.append((name, registry.get(name)))
            except ProviderUnavailable:
                pass

    if not providers_to_use:
        return {"ingested": 0, "errors": ["no providers available"]}

    total_ingested = 0
    by_provider = {}
    errors = []

    for name, provider in providers_to_use:
        try:
            postings = provider.search(query, filters)
            postings = hiring_signals.dedupe_postings(postings)
            count = 0
            for raw in postings:
                signal_id = hiring_signals.upsert_hiring_signal(workspace_id, raw, name)
                if signal_id:
                    count += 1
            total_ingested += count
            by_provider[name] = count
        except Exception as e:
            errors.append(f"{name}: {e}")

    return {"ingested": total_ingested, "by_provider": by_provider, "errors": errors}


@worker("discovery", "signal_scoring")
def handle_signal_scoring(job: dict) -> dict:
    """Payload: {signal_id: str} — recompute score + freshness + expiry for one signal."""
    signal_id = job.get("payload", {}).get("signal_id")
    workspace_id = job.get("workspace_id")
    if not signal_id or not workspace_id:
        return {"updated": False, "error": "signal_id and workspace_id required"}

    with db.get_pool().connection() as conn:
        conn.row_factory = psycopg.rows.dict_row
        row = conn.execute(
            """SELECT hs.*, c.* FROM hiring_signals hs
               JOIN companies c ON c.id = hs.company_id
               WHERE hs.id=%s AND hs.workspace_id=%s""",
            (signal_id, workspace_id),
        ).fetchone()

    if not row:
        return {"updated": False, "error": "signal not found"}

    company = dict(row)
    signal_score, freshness, intent_category = hiring_signals.compute_signal_score(
        {
            "role_category": row["role_category"],
            "intent_signals": {
                "after_hours": False,
                "phone_heavy": False,
                "scheduling_duties": False,
                "icp_match": False,
                "high_volume": False,
                "lead_intake": False,
                "multiple_openings": False,
            },
            "posted_at": row["posted_at"],
        },
        company,
    )

    with db.get_pool().connection() as conn:
        conn.execute(
            """UPDATE hiring_signals SET signal_score=%s, freshness_multiplier=%s,
                  intent_category=%s, updated_at=now() WHERE id=%s""",
            (signal_score, freshness, intent_category, signal_id),
        )

    # Also apply expiry check for this workspace
    expired_count = hiring_signals.apply_expiry(workspace_id)

    return {"updated": True, "signal_id": signal_id, "signal_score": signal_score, "expired": expired_count}


@worker("enrichment", "company_enrichment")
def handle_company_enrichment(job: dict) -> dict:
    """Payload: {company_id: str} — run enrichment waterfall for a company."""
    company_id = job.get("payload", {}).get("company_id")
    workspace_id = job.get("workspace_id")
    if not company_id or not workspace_id:
        return {"enriched": False, "error": "company_id and workspace_id required"}

    try:
        result = enrichment.enrich_company_waterfall(company_id)
        enriched_fields = {k: v for k, v in result.items() if k in [
            "website", "phone", "address", "city", "state", "zip",
            "employee_estimate", "tech_signals", "owner_name", "owner_email"
        ]}
        return {"enriched": True, "company_id": company_id, "fields": enriched_fields}
    except Exception as e:
        return {"enriched": False, "company_id": company_id, "error": str(e)}


@worker("verification", "email_verification")
def handle_email_verification(job: dict) -> dict:
    """Payload: {contact_id: str} — run verification waterfall for a contact."""
    contact_id = job.get("payload", {}).get("contact_id")
    workspace_id = job.get("workspace_id")
    if not contact_id or not workspace_id:
        return {"verified": False, "error": "contact_id and workspace_id required"}

    try:
        result = enrichment.verify_email_waterfall(contact_id)
        return {
            "verified": result.result == "valid",
            "contact_id": contact_id,
            "email": result.email,
            "result": result.result,
            "confidence": result.confidence,
            "provider": result.raw.get("provider") if isinstance(result.raw, dict) else None,
        }
    except Exception as e:
        return {"verified": False, "contact_id": contact_id, "error": str(e)}


@worker("enrichment", "email_finder")
def handle_email_finder(job: dict) -> dict:
    """Payload: {contact_id: str} — find decision-maker email for contact's company."""
    contact_id = job.get("payload", {}).get("contact_id")
    workspace_id = job.get("workspace_id")
    if not contact_id or not workspace_id:
        return {"found": False, "error": "contact_id and workspace_id required"}

    try:
        with db.get_pool().connection() as conn:
            conn.row_factory = psycopg.rows.dict_row
            contact = conn.execute(
                "SELECT company_id FROM contacts WHERE id=%s AND workspace_id=%s",
                (contact_id, workspace_id),
            ).fetchone()
        if not contact:
            return {"found": False, "error": "contact not found"}

        result = enrichment.find_decision_maker_email(str(contact["company_id"]))
        if result:
            return {
                "found": True,
                "contact_id": contact_id,
                "email": result["email"],
                "confidence": result["confidence"],
                "source": result.get("source"),
            }
        return {"found": False, "contact_id": contact_id}
    except Exception as e:
        return {"found": False, "contact_id": contact_id, "error": str(e)}


@worker("ai", "company_research")
def handle_company_research(job: dict) -> dict:
    """Payload: {company_id: str} — run AI research + QC validation for a company."""
    company_id = job.get("payload", {}).get("company_id")
    workspace_id = job.get("workspace_id")
    if not company_id or not workspace_id:
        return {"researched": False, "error": "company_id and workspace_id required"}

    try:
        report = research.research_company(company_id)
        # Validate
        passed, failures = research.validate_research_report(report, company_id)
        return {
            "researched": True,
            "company_id": company_id,
            "report": {
                "summary": report.summary,
                "primary_problem": report.primary_problem,
                "reason_now": report.reason_now,
                "recommended_offer": report.recommended_offer,
                "evidence_count": len(report.evidence),
                "model_used": report.model_used,
            },
            "qc_passed": passed,
            "qc_failures": failures,
        }
    except Exception as e:
        return {"researched": False, "company_id": company_id, "error": str(e)}


@worker("ai", "opportunity_score")
def handle_opportunity_score(job: dict) -> dict:
    """Payload: {company_id: str} — compute opportunity score + EMV for a company."""
    company_id = job.get("payload", {}).get("company_id")
    workspace_id = job.get("workspace_id")
    if not company_id or not workspace_id:
        return {"scored": False, "error": "company_id and workspace_id required"}

    try:
        breakdown = opportunity.compute_opportunity_score(company_id)
        emv = opportunity.compute_emv(company_id)
        return {
            "scored": True,
            "company_id": company_id,
            "opportunity_score": {
                "total": breakdown.total,
                "tier": breakdown.tier,
                "components": breakdown.components,
                "recommended_action": breakdown.recommended_action,
                "recommended_pitch": breakdown.recommended_pitch,
            },
            "emv": {
                "emv_usd": emv.emv,
                "p_positive_reply": emv.p_positive_reply,
                "p_meeting": emv.p_meeting,
                "est_customer_value": emv.est_customer_value,
            },
        }
    except Exception as e:
        return {"scored": False, "company_id": company_id, "error": str(e)}


@worker("ai", "website_intel")
def handle_website_intel(job: dict) -> dict:
    """Payload: {company_id: str} — fetch website intelligence for a company."""
    company_id = job.get("payload", {}).get("company_id")
    workspace_id = job.get("workspace_id")
    if not company_id or not workspace_id:
        return {"intel": False, "error": "company_id and workspace_id required"}

    try:
        result = website_intel.fetch_website_intel(company_id)
        return {
            "intel": True,
            "company_id": company_id,
            "website_findings": result.website_findings,
            "tech_signals": result.tech_signals,
        }
    except Exception as e:
        return {"intel": False, "company_id": company_id, "error": str(e)}


# -----------------------------------------------------------------------
# Outbound scheduler workers
# -----------------------------------------------------------------------

@worker("outbound", "scheduler_tick")
def handle_scheduler_tick(job: dict) -> dict:
    """Payload: {} — run one scheduler tick."""
    from app.services import scheduler
    result = scheduler.tick()
    return result


@worker("outbound", "followup_cancel_check")
def handle_followup_cancel_check(job: dict) -> dict:
    """Payload: {lead_id: str} — check if pending followups should be cancelled."""
    from app.services import scheduler
    lead_id = job.get("payload", {}).get("lead_id")
    if not lead_id:
        return {"checked": False, "error": "lead_id required"}
    cancelled = scheduler.check_followup_cancellation(lead_id)
    return {"checked": True, "lead_id": lead_id, "cancelled": cancelled}
