"""Provider-layer contract tests: registry, LLM chain fallback, circuit
breaker, rate limiter, retry helper, and new-table migrations."""

import asyncio

import psycopg
import pytest

import app.providers as providers
from app.providers.base import (
    ProviderUnavailable,
    Registry,
    VerificationResult,
)
from app.providers.fixtures import (
    FixtureCRM,
    FixtureCalendar,
    FixtureEmailFinder,
    FixtureEmailSender,
    FixtureEnrichment,
    FixtureJobSource,
    FixtureLLM,
    FixtureVerifier,
)
from app.providers.llm_openrouter import OpenRouterChatLLM, OpenRouterError
from app.providers.resilience import (
    AsyncRateLimiter,
    CircuitBreaker,
    CircuitOpenError,
    retry_with_backoff,
    retry_with_backoff_sync,
)


@pytest.fixture
def registry():
    r = Registry()
    yield r
    r.clear_overrides()


class TestMigrations:
    NEW_TABLES = [
        "sending_domains", "mailboxes", "mailbox_events", "sequences",
        "sequence_steps", "outbound_messages", "system_flags",
        "hiring_signals", "enrichments", "email_verifications",
        "research_reports", "provider_usage", "scores", "experiments",
        "experiment_assignments", "watch_subscriptions",
        "jobs", "alerts", "daily_audits", "telegram_settings",
    ]

    def test_all_new_tables_exist(self, db_url):
        conn = psycopg.connect(db_url)
        present = {
            r[0] for r in conn.execute(
                """SELECT tablename FROM pg_tables WHERE schemaname='public'"""
            ).fetchall()
        }
        conn.close()
        missing = set(self.NEW_TABLES) - present
        assert not missing, f"missing tables: {missing}"

    def test_jobs_columns_and_checks(self, db_url):
        conn = psycopg.connect(db_url)
        cols = {r[0] for r in conn.execute(
            """SELECT column_name FROM information_schema.columns
               WHERE table_name='jobs'"""
        ).fetchall()}
        conn.close()
        assert {"id", "type", "pool", "priority", "status", "payload",
                "attempts", "max_attempts", "run_at", "provider",
                "idempotency_key"} <= cols

    def test_mailbox_credentials_never_plaintext_default(self, db_url):
        conn = psycopg.connect(db_url)
        row = conn.execute(
            """SELECT column_default FROM information_schema.columns
               WHERE table_name='mailboxes' AND column_name='credentials'"""
        ).fetchone()
        conn.close()
        assert "'{}'" in row[0]

    def test_system_flags_upsert_helper(self, db_url):
        from app.services import flags

        first = flags.set_flag("shadow_mode", True, updated_by="tester")
        assert first["value"] is True
        second = flags.set_flag("shadow_mode", False, updated_by="tester2")
        assert second["value"] is False
        rows = flags.all_flags()
        assert rows == {"shadow_mode": False}
        assert flags.get_flag("pause_all_sending") is None


class TestRegistry:
    def test_get_unregistered_raises(self, registry):
        with pytest.raises(ProviderUnavailable):
            registry.get("nope")

    def test_override_shadows_registration(self, registry):
        real = FixtureVerifier(result="valid")
        fake = FixtureVerifier(result="invalid")
        registry.register("verifier", real)
        registry.override("verifier", fake)
        assert registry.get("verifier") is fake
        registry.clear_overrides()
        assert registry.get("verifier") is real


class TestFixtureProviders:
    def test_fixture_llm_script_marker_and_echo(self):
        llm = FixtureLLM(scripts={"RESEARCH": '{"summary": "canned"}'})
        hit = llm.complete("sys", "please RESEARCH this company")
        assert hit.content == '{"summary": "canned"}'
        echo = llm.complete("be", "calm")
        assert echo.content == "be\ncalm"
        assert echo.model_used == "fixture-llm"

    def test_fixture_llm_fail_once(self):
        llm = FixtureLLM(fail_once=True)
        with pytest.raises(RuntimeError):
            llm.complete("s", "u")
        assert llm.complete("s", "u").content  # recovered

    def test_fixture_job_source_filter(self):
        src = FixtureJobSource(postings=[
            {"title": "Receptionist"}, {"title": "Trucker"},
        ])
        assert len(src.search("hiring")) == 2
        filtered = src.search("hiring", {"title_contains": "recept"})
        assert [p["title"] for p in filtered] == ["Receptionist"]

    def test_fixture_verifier_configurable(self):
        v = FixtureVerifier(result="accept_all", confidence=0.5)
        res = v.verify("a@b.co")
        assert isinstance(res, VerificationResult)
        assert res.result == "accept_all" and res.confidence == 0.5

    def test_fixture_enrichment_merges(self):
        e = FixtureEnrichment(extra_fields={"employee_estimate": 7})
        out = e.enrich_company({"business_name": "X"})
        assert out["employee_estimate"] == 7 and out["business_name"] == "X"

    def test_fixture_sender_records_and_injects_failure(self):
        sender = FixtureEmailSender(fail_next=1)
        bad = sender.send(from_addr="a@x.test", to="b@y.test", subject="s",
                          body_text="hi")
        good = sender.send(from_addr="a@x.test", to="b@y.test", subject="s",
                           body_text="hi again")
        assert bad.ok is False and bad.error == "injected failure"
        assert good.ok is True and good.provider_message_id == "fixture-2"
        assert len(sender.sent) == 2

    def test_fixture_email_finder(self):
        f = FixtureEmailFinder()
        found = f.find_email({"business_name": "Acme", "website": "acme.test"},
                             "Bob Smith")
        assert found["email"] == "bob@acme.test"


class TestFixtureCRMAndCalendar:
    def test_fixture_crm_upsert_retrieve_search_and_failure(self):
        crm = FixtureCRM(fail_on={"upsert_company"})
        with pytest.raises(RuntimeError, match="fixture crm upsert_company failure"):
            crm.upsert_company({"business_name": "FailCo"})
        assert crm.companies == {}

        crm = FixtureCRM()
        crm.upsert_company({"business_name": "Acme", "id": "c1"})
        crm.upsert_contact({"name": "Bob", "email": "bob@acme.test", "id": "ct1"})
        crm.create_opportunity({"name": "Deal", "value": 10000, "contact_id": "ct1"})
        assert crm.get_contact("ct1")["name"] == "Bob"
        search = crm.search_contacts("bob")
        assert search["results"][0]["name"] == "Bob"

    def test_fixture_calendar_create_availability_book_and_failure(self):
        cal = FixtureCalendar(fail_on={"book_slot"})
        with pytest.raises(RuntimeError, match="fixture calendar book_slot failure"):
            cal.book_slot({"start": "2025-01-15T10:00:00Z"}, {"name": "Bob"})
        assert len(cal.events) == 0

        cal = FixtureCalendar()
        event = cal.create_event({"title": "Demo", "start": "2025-01-15T10:00:00Z", "end": "2025-01-15T10:30:00Z"})
        assert event["title"] == "Demo"
        avail = cal.get_availability("2025-01-15T09:00:00Z", "2025-01-15T12:00:00Z")
        assert "slots" in avail
        booking = cal.book_slot(
            {"start": "2025-01-15T10:00:00Z", "end": "2025-01-15T10:30:00Z"},
            {"name": "Bob", "email": "bob@acme.test"}
        )
        assert booking["status"] == "confirmed"
        assert booking["contact"]["email"] == "bob@acme.test"
    MODELS = ["model-a", "model-b", "model-c"]

    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch):
        from app.config import get_settings

        monkeypatch.setenv("LLM_MODEL_CHAIN", ",".join(self.MODELS))
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    @pytest.fixture
    def llm(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        from app.config import get_settings

        get_settings.cache_clear()
        return OpenRouterChatLLM()

    def test_falls_to_next_model_on_network_error(self, llm):
        requested = []

        def transport(payload):
            requested.append(payload["model"])
            if payload["model"] == self.MODELS[0]:
                raise ConnectionError("boom")
            return {"choices": [{"message": {"content": "ok"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                    "model": payload["model"]}

        llm._transport = transport
        resp = llm.complete("sys", "user")
        assert requested == self.MODELS[:2]
        assert resp.model_used == "model-b"
        assert resp.tokens_in == 10 and resp.tokens_out == 5
        assert resp.cost_usd > 0

    def test_falls_on_429_and_5xx_but_not_401(self, llm):
        calls = []

        def transport_429(payload):
            calls.append("429")
            if len(calls) < 2:
                raise OpenRouterError(429, "rate limited")
            return {"choices": [{"message": {"content": "fine"}}],
                    "usage": {}, "model": "model-b"}

        llm._transport = transport_429
        assert llm.complete("s", "u").content == "fine"

        def transport_500(payload):
            raise OpenRouterError(502, "bad gateway")

        llm._transport = transport_500
        with pytest.raises(ProviderUnavailable):
            llm.complete("s", "u")

        def transport_401(payload):
            raise OpenRouterError(401, "no auth")

        llm._transport = transport_401
        with pytest.raises(OpenRouterError) as exc:
            llm.complete("s", "u")
        assert exc.value.status_code == 401

    def test_tier_selection(self, llm, monkeypatch):
        def ok_transport(payload):
            return {"choices": [{"message": {"content": "x"}}], "usage": {},
                    "model": payload["model"]}

        def fail_others(payload):
            if payload["model"] != "model-c":
                raise ConnectionError("fail")
            return ok_transport(payload)

        seen = []

        def recording(inner):
            def t(payload):
                seen.append(payload["model"])
                return inner(payload)
            return t

        # cheap starts at chain[0] and walks forward
        llm._transport = recording(fail_others)
        llm.complete("s", "u", model_tier="cheap")
        assert seen[-3:] == self.MODELS
        # frontier starts at the last model
        seen.clear()
        llm.complete("s", "u", model_tier="frontier")
        assert seen == ["model-c"]
        # strong honors env override and stops on first success
        monkeypatch.setenv("LLM_STRONG_MODEL", "model-strong")
        seen.clear()
        llm._transport = recording(ok_transport)
        llm.complete("s", "u", model_tier="strong")
        assert seen == ["model-strong"]

    def test_missing_key_raises_provider_unavailable(self, monkeypatch):
        from app.config import get_settings

        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.setenv("LLM_API_KEY", "")
        get_settings.cache_clear()
        try:
            with pytest.raises(ProviderUnavailable):
                OpenRouterChatLLM()
        finally:
            get_settings.cache_clear()


class TestCircuitBreaker:
    def test_opens_after_threshold(self):
        breaker = CircuitBreaker(failure_threshold=3, reset_timeout=60)

        def boom():
            raise RuntimeError("down")

        for _ in range(3):
            with pytest.raises(RuntimeError):
                breaker.call(boom)
        assert breaker.state == "open"
        assert breaker.allow() is False
        with pytest.raises(CircuitOpenError):
            breaker.call(lambda: "never")

    def test_half_open_recovery(self):
        breaker = CircuitBreaker(failure_threshold=2, reset_timeout=0.05)

        def boom():
            raise RuntimeError("down")

        for _ in range(2):
            with pytest.raises(RuntimeError):
                breaker.call(boom)
        assert breaker.state == "open"

        import time as _time

        _time.sleep(0.06)
        assert breaker.allow() is True
        assert breaker.state == "half-open"

        # failure in half-open reopens
        with pytest.raises(RuntimeError):
            breaker.call(boom)
        assert breaker.state == "open"

        _time.sleep(0.06)
        assert breaker.allow() is True  # lazy open -> half-open transition
        assert breaker.state == "half-open"
        assert breaker.call(lambda: "up") == "up"
        assert breaker.state == "closed"

    def test_acall_success_path(self):
        async def scenario():
            breaker = CircuitBreaker()

            async def ok():
                return "ok"

            return await breaker.acall(ok)

        assert asyncio.run(scenario()) == "ok"


class TestRateLimiterAndRetry:
    def test_rate_limiter_bounds_concurrency(self):
        limiter = AsyncRateLimiter(max_concurrency=2)
        state = {"active": 0, "peak": 0}

        async def work():
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
            await asyncio.sleep(0.01)
            state["active"] -= 1

        async def scenario():
            async with limiter:
                pass
            async def guarded():
                async with limiter:
                    await work()
            await asyncio.gather(*(guarded() for _ in range(6)))

        asyncio.run(scenario())
        assert state["peak"] <= 2

    def test_retry_with_backoff_succeeds_then_exhausts(self):
        attempts = {"n": 0}

        async def flaky():
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise ValueError("transient")
            return "recovered"

        result = asyncio.run(retry_with_backoff(
            flaky, attempts=3, base_delay=0.01, jitter=0.0))
        assert result == "recovered" and attempts["n"] == 3

        async def always_fails():
            raise KeyError("permanent")

        with pytest.raises(KeyError):
            asyncio.run(retry_with_backoff(always_fails, attempts=2,
                                           base_delay=0.01,
                                           retry_on=(KeyError,)))

    def test_sync_retry_helper(self):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise RuntimeError("try again")
            return "done"

        assert retry_with_backoff_sync(flaky, attempts=3, base_delay=0.001) == "done"
