from app.services.scoring import (
    hiring_category,
    hiring_intent_score,
    icp_fit_score,
    fit_status_for,
    priority_score,
    priority_tier,
)


class TestIcpFit:
    def test_perfect_small_contractor_scores_high(self):
        score, detail = icp_fit_score({
            "single_location": True, "owner_visible": True, "family_owned": True,
            "simple_site": True, "residential_focus": True,
            "local_service_area": True, "direct_phone": True,
        })
        assert score >= 8
        assert "single_location" in detail

    def test_franchise_national_rejected(self):
        score, _ = icp_fit_score({
            "franchise": True, "national_brand": True, "careers_page": True,
        })
        assert score == 0

    def test_score_clamped_0_10(self):
        score, _ = icp_fit_score({k: True for k in [
            "single_location", "owner_visible", "family_owned", "simple_site",
            "residential_focus", "local_service_area", "direct_phone"]})
        assert 0 <= score <= 10

    def test_threshold_semantics(self):
        qualified = fit_status_for(7, {}, unclear=False)
        borderline = fit_status_for(5, {}, unclear=False)
        too_large = fit_status_for(9, {"enterprise_signals": True}, unclear=False)
        unclear = fit_status_for(2, {}, unclear=True)
        assert (qualified, borderline, too_large, unclear) == (
            "qualified", "borderline", "rejected_too_large", "rejected_unclear")


class TestPriorityScore:
    def test_weights_compose(self):
        # all maxed -> 100; all zeroed -> 0
        assert priority_score(intent=1, fit=1, contact_quality=1, history=1) == 100
        assert priority_score(intent=0, fit=0, contact_quality=0, history=0) == 0

    def test_tiers(self):
        assert priority_tier(90) == "P1"
        assert priority_tier(70) == "P2"
        assert priority_tier(50) == "P3"
        assert priority_tier(10) == "P4"

    def test_intent_dominates(self):
        high_intent = priority_score(intent=1.0, fit=0.3, contact_quality=0.5, history=0)
        low_intent = priority_score(intent=0.0, fit=0.9, contact_quality=0.5, history=0)
        assert high_intent > low_intent


class TestHiringIntent:
    def test_receptionist_at_icp_company_is_very_high(self):
        score = hiring_intent_score(
            role_key="receptionist", icp_match=True, after_hours=True,
            phone_heavy=True, scheduling_duties=True, multiple_openings=True,
            days_old=2, multiple_locations=False)
        assert score >= 90
        assert hiring_category(score) == "very_high"

    def test_stale_irrelevant_posting_ignored(self):
        score = hiring_intent_score(
            role_key=None, icp_match=False, after_hours=False, phone_heavy=False,
            scheduling_duties=False, multiple_openings=False, days_old=60,
            multiple_locations=False)
        assert hiring_category(score) in ("low", "medium")

    def test_multiple_locations_penalized(self):
        base = hiring_intent_score(
            role_key="dispatcher", icp_match=True, after_hours=False,
            phone_heavy=True, scheduling_duties=False, multiple_openings=False,
            days_old=1, multiple_locations=False)
        penal = hiring_intent_score(
            role_key="dispatcher", icp_match=True, after_hours=False,
            phone_heavy=True, scheduling_duties=False, multiple_openings=False,
            days_old=1, multiple_locations=True)
        assert penal == base - 10

    def test_clamped_to_100(self):
        score = hiring_intent_score(
            role_key="receptionist", icp_match=True, after_hours=True,
            phone_heavy=True, scheduling_duties=True, multiple_openings=True,
            days_old=1, multiple_locations=False)
        assert score <= 100
