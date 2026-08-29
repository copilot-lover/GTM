"""Tests for enrichment & verification waterfall orchestration."""

import pytest
import psycopg.rows
import app.db as db

from app.providers import registry
from app.providers.base import VerificationResult, ProviderUnavailable
from app.providers.fixtures import (
    FixtureEnrichment,
    FixtureVerifier,
    FixtureEmailFinder,
)
from app.services import enrichment as enrichment_service
from app.services.job_queue import (
    handle_company_enrichment,
    handle_email_verification,
    handle_email_finder,
)


class TestEnrichmentWaterfall:
    def test_waterfall_stops_when_filled(self, workspace):
        """Apollo returns partial → hunter fills rest → stops."""
        ws_id, user_id = workspace

        # Create company
        with db.get_pool().connection() as conn:
            conn.row_factory = psycopg.rows.dict_row
            company = conn.execute(
                """INSERT INTO companies (workspace_id, business_name) VALUES (%s,%s) RETURNING id""",
                (ws_id, "Test Corp"),
            ).fetchone()
        company_id = str(company["id"])

        # Register fixtures: apollo returns partial, hunter fills rest
        apollo_fixture = FixtureEnrichment(extra_fields={
            "website": "https://testcorp.com",
            "phone": "(555) 123-4567",
        })
        hunter_fixture = FixtureEnrichment(extra_fields={
            "employee_estimate": 25,
            "tech_signals": ["wordpress", "google_analytics"],
            "owner_name": "John Owner",
            "owner_email": "john@testcorp.com",
        })
        registry.override("apollo", apollo_fixture)
        registry.override("hunter", hunter_fixture)

        try:
            result = enrichment_service.enrich_company_waterfall(company_id)
            # Should have fields from both providers
            assert result["website"] == "https://testcorp.com"
            assert result["phone"] == "(555) 123-4567"
            assert result["employee_estimate"] == 25
            assert result["tech_signals"] == ["wordpress", "google_analytics"]
            assert result["owner_name"] == "John Owner"
            assert result["owner_email"] == "john@testcorp.com"

            # Verify enrichments table has both attempts
            with db.get_pool().connection() as conn:
                conn.row_factory = psycopg.rows.dict_row
                rows = conn.execute(
                    "SELECT provider, succeeded FROM enrichments WHERE company_id=%s ORDER BY created_at",
                    (company_id,),
                ).fetchall()
            assert len(rows) == 2
            assert rows[0]["provider"] == "apollo"
            assert rows[1]["provider"] == "hunter"
            assert rows[0]["succeeded"] is True
            assert rows[1]["succeeded"] is True
        finally:
            registry.clear_overrides()

    def test_quota_reserve_threshold(self, workspace):
        """Provider at quota-20 → deprioritized → next provider used."""
        ws_id, user_id = workspace
        from datetime import datetime, timezone
        current_period = datetime.now(timezone.utc).strftime("%Y-%m")

        with db.get_pool().connection() as conn:
            conn.row_factory = psycopg.rows.dict_row
            company = conn.execute(
                """INSERT INTO companies (workspace_id, business_name) VALUES (%s,%s) RETURNING id""",
                (ws_id, "Quota Corp"),
            ).fetchone()
            conn.execute(
                """INSERT INTO provider_usage (provider, operation, period, quota, used, reserve_threshold)
                   VALUES ('apollo', 'enrich_company', %s, 100, 85, 20)""",
                (current_period,),
            )
        company_id = str(company["id"])

        apollo_fixture = FixtureEnrichment(extra_fields={"website": "https://apollo.com"})
        hunter_fixture = FixtureEnrichment(extra_fields={"website": "https://hunter.com"})
        registry.override("apollo", apollo_fixture)
        registry.override("hunter", hunter_fixture)

        try:
            result = enrichment_service.enrich_company_waterfall(company_id)
            # Should use hunter since apollo is at quota-reserve (85 >= 100-20=80)
            assert result["website"] == "https://hunter.com"

            # Verify apollo was not called
            with db.get_pool().connection() as conn:
                rows = conn.execute(
                    "SELECT provider FROM enrichments WHERE company_id=%s",
                    (company_id,),
                ).fetchall()
            providers = [r["provider"] for r in rows]
            assert "apollo" not in providers
            assert "hunter" in providers
        finally:
            registry.clear_overrides()

    def test_fallback_on_provider_failure(self, workspace):
        """Apollo raises → hunter used."""
        ws_id, user_id = workspace

        with db.get_pool().connection() as conn:
            conn.row_factory = psycopg.rows.dict_row
            company = conn.execute(
                """INSERT INTO companies (workspace_id, business_name) VALUES (%s,%s) RETURNING id""",
                (ws_id, "Failover Corp"),
            ).fetchone()
        company_id = str(company["id"])

        class FailingApollo:
            def enrich_company(self, company):
                raise RuntimeError("API down")

        hunter_fixture = FixtureEnrichment(extra_fields={"website": "https://hunter.com"})
        registry.override("apollo", FailingApollo())
        registry.override("hunter", hunter_fixture)

        try:
            result = enrichment_service.enrich_company_waterfall(company_id)
            assert result["website"] == "https://hunter.com"
        finally:
            registry.clear_overrides()


class TestEmailVerificationWaterfall:
    def test_local_prechecks_then_provider(self, workspace):
        """Invalid syntax → no provider call → invalid result."""
        ws_id, user_id = workspace

        with db.get_pool().connection() as conn:
            conn.row_factory = psycopg.rows.dict_row
            company = conn.execute(
                """INSERT INTO companies (workspace_id, business_name) VALUES (%s,%s) RETURNING id""",
                (ws_id, "Test Co"),
            ).fetchone()
            contact = conn.execute(
                """INSERT INTO contacts (workspace_id, company_id, email) VALUES (%s,%s,%s) RETURNING id""",
                (ws_id, str(company["id"]), "invalid-email"),
            ).fetchone()
        contact_id = str(contact["id"])

        # Provider should not be called
        verifier = FixtureVerifier(result="valid", confidence=0.95)
        registry.override("zerobounce", verifier)

        try:
            result = enrichment_service.verify_email_waterfall(contact_id)
            assert result.result == "invalid"
            assert result.confidence == 0
            # Provider should not have been called (fixture would have recorded it)
            assert len(verifier.verified) == 0
        finally:
            registry.clear_overrides()

    def test_disposable_domain_blocked_locally(self, workspace):
        """Disposable domain → blocked locally, no provider call."""
        ws_id, user_id = workspace

        with db.get_pool().connection() as conn:
            conn.row_factory = psycopg.rows.dict_row
            company = conn.execute(
                """INSERT INTO companies (workspace_id, business_name) VALUES (%s,%s) RETURNING id""",
                (ws_id, "Test Co"),
            ).fetchone()
            contact = conn.execute(
                """INSERT INTO contacts (workspace_id, company_id, email) VALUES (%s,%s,%s) RETURNING id""",
                (ws_id, str(company["id"]), "test@mailinator.com"),
            ).fetchone()
        contact_id = str(contact["id"])

        verifier = FixtureVerifier(result="valid", confidence=0.95)
        registry.override("zerobounce", verifier)

        try:
            result = enrichment_service.verify_email_waterfall(contact_id)
            assert result.result == "disposable"
            assert result.confidence == 0.6
            assert len(verifier.verified) == 0
        finally:
            registry.clear_overrides()

    def test_mark_provider_verified_wired(self, workspace):
        """Valid result → contact.email_verification_status='verified' + confidence=90."""
        ws_id, user_id = workspace

        with db.get_pool().connection() as conn:
            conn.row_factory = psycopg.rows.dict_row
            company = conn.execute(
                """INSERT INTO companies (workspace_id, business_name) VALUES (%s,%s) RETURNING id""",
                (ws_id, "Verified Co"),
            ).fetchone()
            contact = conn.execute(
                """INSERT INTO contacts (workspace_id, company_id, email) VALUES (%s,%s,%s) RETURNING id""",
                (ws_id, str(company["id"]), "valid@test.com"),
            ).fetchone()
        contact_id = str(contact["id"])

        verifier = FixtureVerifier(result="valid", confidence=0.95)
        registry.override("zerobounce", verifier)

        try:
            result = enrichment_service.verify_email_waterfall(contact_id)
            assert result.result == "valid"
            assert result.confidence == 0.95

            # Check contact was updated
            with db.get_pool().connection() as conn:
                conn.row_factory = psycopg.rows.dict_row
                updated = conn.execute(
                    "SELECT email_verification_status, email_verification_confidence, email_verification_provider FROM contacts WHERE id=%s",
                    (contact_id,),
                ).fetchone()
            assert updated["email_verification_status"] == "verified"
            assert updated["email_verification_confidence"] == 95
            assert updated["email_verification_provider"] == "zerobounce"
        finally:
            registry.clear_overrides()

    def test_verification_waterfall_fallback(self, workspace):
        """ZeroBounce fails → Hunter used."""
        ws_id, user_id = workspace

        with db.get_pool().connection() as conn:
            conn.row_factory = psycopg.rows.dict_row
            company = conn.execute(
                """INSERT INTO companies (workspace_id, business_name) VALUES (%s,%s) RETURNING id""",
                (ws_id, "Fallback Co"),
            ).fetchone()
            contact = conn.execute(
                """INSERT INTO contacts (workspace_id, company_id, email) VALUES (%s,%s,%s) RETURNING id""",
                (ws_id, str(company["id"]), "test@fallback.com"),
            ).fetchone()
        contact_id = str(contact["id"])

        class FailingZeroBounce:
            def verify(self, email):
                raise RuntimeError("API down")

        hunter_fixture = FixtureVerifier(result="valid", confidence=0.9)
        registry.override("zerobounce", FailingZeroBounce())
        registry.override("hunter_verify", hunter_fixture)

        try:
            result = enrichment_service.verify_email_waterfall(contact_id)
            assert result.result == "valid"
            assert result.confidence == 0.9
        finally:
            registry.clear_overrides()


class TestDecisionMakerRanking:
    def test_decision_maker_ranking(self, workspace):
        """Company w/ owner+gm+ops → owner email returned."""
        ws_id, user_id = workspace

        with db.get_pool().connection() as conn:
            conn.row_factory = psycopg.rows.dict_row
            company = conn.execute(
                """INSERT INTO companies (workspace_id, business_name, owner_name) VALUES (%s,%s,%s) RETURNING id""",
                (ws_id, "Ranking Corp", "Jane Owner"),
            ).fetchone()
        company_id = str(company["id"])

        finder = FixtureEmailFinder(addresses={
            ("Ranking Corp", "Jane Owner"): "jane@ranking.com",
            ("Ranking Corp", "GM Name"): "gm@ranking.com",
            ("Ranking Corp", "Ops Name"): "ops@ranking.com",
        })
        registry.override("apollo_email_finder", finder)

        try:
            result = enrichment_service.find_decision_maker_email(company_id)
            assert result is not None
            assert result["email"] == "jane@ranking.com"
            assert result["confidence"] == 0.9
        finally:
            registry.clear_overrides()


class TestWorkerHandlers:
    def test_company_enrichment_worker(self, workspace):
        """Worker handler for company_enrichment."""
        ws_id, user_id = workspace

        with db.get_pool().connection() as conn:
            conn.row_factory = psycopg.rows.dict_row
            company = conn.execute(
                """INSERT INTO companies (workspace_id, business_name) VALUES (%s,%s) RETURNING id""",
                (ws_id, "Worker Corp"),
            ).fetchone()
        company_id = str(company["id"])

        fixture = FixtureEnrichment(extra_fields={"website": "https://worker.com"})
        registry.override("apollo", fixture)

        try:
            job = {"payload": {"company_id": company_id}, "workspace_id": ws_id}
            result = handle_company_enrichment(job)
            assert result["enriched"] is True
            assert result["fields"]["website"] == "https://worker.com"
        finally:
            registry.clear_overrides()

    def test_email_verification_worker(self, workspace):
        """Worker handler for email_verification."""
        ws_id, user_id = workspace

        with db.get_pool().connection() as conn:
            conn.row_factory = psycopg.rows.dict_row
            company = conn.execute(
                """INSERT INTO companies (workspace_id, business_name) VALUES (%s,%s) RETURNING id""",
                (ws_id, "Verify Corp"),
            ).fetchone()
            contact = conn.execute(
                """INSERT INTO contacts (workspace_id, company_id, email) VALUES (%s,%s,%s) RETURNING id""",
                (ws_id, str(company["id"]), "verify@worker.com"),
            ).fetchone()
        contact_id = str(contact["id"])

        fixture = FixtureVerifier(result="valid", confidence=0.95)
        registry.override("zerobounce", fixture)

        try:
            job = {"payload": {"contact_id": contact_id}, "workspace_id": ws_id}
            result = handle_email_verification(job)
            assert result["verified"] is True
            assert result["result"] == "valid"
        finally:
            registry.clear_overrides()

    def test_email_finder_worker(self, workspace):
        """Worker handler for email_finder."""
        ws_id, user_id = workspace

        with db.get_pool().connection() as conn:
            conn.row_factory = psycopg.rows.dict_row
            company = conn.execute(
                """INSERT INTO companies (workspace_id, business_name) VALUES (%s,%s) RETURNING id""",
                (ws_id, "Finder Corp"),
            ).fetchone()
            contact = conn.execute(
                """INSERT INTO contacts (workspace_id, company_id, email) VALUES (%s,%s,%s) RETURNING id""",
                (ws_id, str(company["id"]), "old@finder.com"),
            ).fetchone()
        contact_id = str(contact["id"])

        fixture = FixtureEmailFinder(addresses={
            ("Finder Corp", "Finder Corp"): "owner@finder.com",
        })
        registry.override("apollo_email_finder", fixture)

        try:
            job = {"payload": {"contact_id": contact_id}, "workspace_id": ws_id}
            result = handle_email_finder(job)
            assert result["found"] is True
            assert result["email"] == "owner@finder.com"
        finally:
            registry.clear_overrides()


class TestTrackProviderUsage:
    def test_track_provider_usage_basic(self, workspace):
        """Basic quota tracking works."""
        from app.services.enrichment import track_provider_usage
        from datetime import datetime, timezone
        current_period = datetime.now(timezone.utc).strftime("%Y-%m")

        # Set up provider_usage with quota
        import app.db as db
        with db.get_pool().connection() as conn:
            conn.execute(
                """INSERT INTO provider_usage (provider, operation, period, quota, used, reserve_threshold)
                   VALUES (%s,%s,%s,100,0,20)""",
                ("test_provider", "test_op", current_period),
            )

        # First call - should be available
        available = track_provider_usage("test_provider", "test_op", 1.0)
        assert available is True

        # Fill up to quota - 20 (reserve threshold)
        for _ in range(79):  # quota 100, used 1 + 79 = 80, threshold 20 -> 80 >= 80
            track_provider_usage("test_provider", "test_op", 1.0)

        # Next call should be deprioritized
        available = track_provider_usage("test_provider", "test_op", 1.0)
        assert available is False