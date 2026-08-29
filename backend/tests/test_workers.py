"""Job queue contract tests: idempotent enqueue, claim ordering, retry
backoff, dead-lettering, and one supervised async smoke run."""

import asyncio
from datetime import datetime, timedelta

import psycopg
import pytest

from app.services import job_queue as jq


@pytest.fixture(autouse=True)
def _clean_handlers():
    yield
    jq._HANDLERS.clear()


def force_due(db_url, job_id: str):
    """Backoff makes run_at future-dated; pull it back for the next claim."""
    conn = psycopg.connect(db_url, autocommit=True)
    conn.execute("UPDATE jobs SET run_at = now() - interval '1s' WHERE id=%s",
                 (job_id,))
    conn.close()


class TestEnqueue:
    def test_enqueue_returns_row(self, db_url):
        job = jq.enqueue(type="enrich_company", pool="enrichment",
                         payload={"company_id": "abc"}, priority=1,
                         provider="apollo", workspace_id=None)
        assert job["status"] == "QUEUED"
        assert job["attempts"] == 0
        assert job["max_attempts"] == 3
        assert job["payload"] == {"company_id": "abc"}
        assert job["provider"] == "apollo"

    def test_enqueue_idempotency_key(self, db_url):
        j1 = jq.enqueue(type="verify_email", pool="verification",
                        payload={"email": "a@b.co"},
                        idempotency_key="verify:a@b.co:2026-08-24")
        j2 = jq.enqueue(type="verify_email", pool="verification",
                        payload={"email": "DIFFERENT"},
                        idempotency_key="verify:a@b.co:2026-08-24")
        assert str(j1["id"]) == str(j2["id"])
        assert j2["payload"] == {"email": "a@b.co"}
        conn = psycopg.connect(db_url)
        count = conn.execute("SELECT count(*) FROM jobs").fetchone()[0]
        conn.close()
        assert count == 1


class TestClaim:
    def test_claim_sets_running_and_counts_attempt(self, db_url):
        job = jq.enqueue(type="t", pool="ai")
        claimed = jq.claim_next("ai")
        assert str(claimed["id"]) == str(job["id"])
        assert claimed["status"] == "RUNNING"
        assert claimed["attempts"] == 1
        assert claimed["started_at"] is not None

    def test_claim_priority_zero_first(self, db_url):
        jq.enqueue(type="low", pool="outbound", priority=5)
        urgent = jq.enqueue(type="high", pool="outbound", priority=0)
        claimed = jq.claim_next("outbound")
        assert str(claimed["id"]) == str(urgent["id"])

    def test_claim_respects_run_at(self, db_url):
        jq.enqueue(type="later", pool="discovery",
                   run_at=datetime.now() + timedelta(hours=1))
        assert jq.claim_next("discovery") is None

    def test_claim_empty_pool_none(self, db_url):
        assert jq.claim_next("meeting") is None


class TestCompleteAndFail:
    def test_complete(self, db_url):
        job = jq.enqueue(type="t", pool="ai")
        jq.claim_next("ai")
        jq.complete(str(job["id"]), {"score": 42})
        row = jq.get_job(str(job["id"]))
        assert row["status"] == "COMPLETED"
        assert row["result"] == {"score": 42}
        assert row["completed_at"] is not None

    def test_fail_retries_with_backoff_then_dead_letters(self, db_url):
        job = jq.enqueue(type="flaky", pool="enrichment", max_attempts=2)

        c1 = jq.claim_next("enrichment")
        failed = jq.fail(str(job["id"]), "transient error")
        assert failed["status"] == "QUEUED"
        assert failed["error"] == "transient error"
        assert failed["run_at"] > c1["run_at"]

        force_due(db_url, job["id"])
        c2 = jq.claim_next("enrichment")
        assert c2["attempts"] == 2
        dead = jq.fail(str(job["id"]), "still broken")
        assert dead["status"] == "DEAD_LETTER"
        assert dead["completed_at"] is not None
        assert jq.claim_next("enrichment") is None

    def test_backoff_grows_between_attempts(self, db_url):
        job = jq.enqueue(type="t", pool="ai", max_attempts=99)
        jq.claim_next("ai")
        first = jq.fail(str(job["id"]), "e1")
        force_due(db_url, job["id"])
        jq.claim_next("ai")
        second = jq.fail(str(job["id"]), "e2")
        gap1 = (first["run_at"] - first["started_at"]).total_seconds()
        gap2 = (second["run_at"] - second["started_at"]).total_seconds()
        assert gap2 > gap1  # ~2x base with jitter; ranges never overlap


class TestSupervisedWorkers:
    def test_supervisor_processes_job_end_to_end(self, db_url):
        processed = []
        done = asyncio.Event()

        @jq.worker("verification", "fixture_verify")
        def handle(job):
            processed.append((job["type"], job["payload"]["email"]))
            if len(processed) >= 1:
                done.set()
            return {"verified": True}

        async def scenario():
            sup = jq.WorkerSupervisor(pools={"verification": 1},
                                      poll_interval=0.02)
            task = asyncio.create_task(sup.run())
            try:
                await asyncio.wait_for(done.wait(), timeout=5)
            finally:
                await sup.stop()
                await asyncio.gather(task, return_exceptions=True)

        jq.enqueue(type="fixture_verify", pool="verification",
                   payload={"email": "x@y.co"}, provider="zerobounce")
        asyncio.run(scenario())
        assert processed == [("fixture_verify", "x@y.co")]
        conn = psycopg.connect(db_url)
        row = conn.execute(
            "SELECT status FROM jobs WHERE type='fixture_verify'"
        ).fetchone()
        conn.close()
        assert row[0] == "COMPLETED"

    def test_supervisor_fails_job_without_handler(self, db_url):
        async def scenario():
            sup = jq.WorkerSupervisor(pools={"meeting": 1}, poll_interval=0.02)
            task = asyncio.create_task(sup.run())
            await asyncio.sleep(0.15)
            await sup.stop()
            await asyncio.gather(task, return_exceptions=True)

        jq.enqueue(type="unhandled_kind", pool="meeting", max_attempts=1)
        asyncio.run(scenario())
        conn = psycopg.connect(db_url)
        row = conn.execute(
            "SELECT status FROM jobs WHERE type='unhandled_kind'"
        ).fetchone()
        conn.close()
        assert row[0] == "DEAD_LETTER"

    def test_supervisor_records_handler_exception_and_retries(self, db_url):
        calls = {"n": 0}

        @jq.worker("ai", "boom_kind")
        def handle(job):
            calls["n"] += 1
            raise RuntimeError("handler exploded")

        async def scenario():
            sup = jq.WorkerSupervisor(pools={"ai": 1}, poll_interval=0.02)
            task = asyncio.create_task(sup.run())
            await asyncio.sleep(0.2)
            await sup.stop()
            await asyncio.gather(task, return_exceptions=True)

        job = jq.enqueue(type="boom_kind", pool="ai", max_attempts=3)
        asyncio.run(scenario())
        assert calls["n"] == 1  # backoff pushes the retry past this window
        row = jq.get_job(str(job["id"]))
        assert row["status"] == "QUEUED"
        assert "RuntimeError" in row["error"]
