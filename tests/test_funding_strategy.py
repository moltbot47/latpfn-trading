"""Tests for funding.strategy_engine — readiness scoring, recommendations, round planning."""

from datetime import datetime, timedelta

from funding.models import (
    Application, CreditProfile, FundingProduct, Inquiry, Recommendation, StrategyRound,
)
from funding.strategy_engine import (
    get_readiness_score, get_recommendations, plan_round,
    _score_optimization, _utilization_optimization, _inquiry_management,
    _cooling_period_check, _eligible_products, _application_order,
    _derogatory_check,
)


# ── Readiness Score ──────────────────────────────────────────────────


class TestReadinessScore:
    def test_no_profile(self, funding_db):
        result = get_readiness_score(funding_db)
        assert result["score"] == 0
        assert "no_profile" in result["factors"]

    def test_excellent_credit(self, funding_db):
        funding_db.save_profile(CreditProfile(
            bureau="experian", score=760, utilization_pct=8.0,
            derogatory_marks=0, collections=0))

        result = get_readiness_score(funding_db)
        # score=760 → 25pts, util=8% → 25pts, 0 inqs → 25pts, 0 derogs → 25pts
        assert result["score"] == 100
        assert "Excellent" in result["factors"]["credit_score"]

    def test_low_credit(self, funding_db):
        funding_db.save_profile(CreditProfile(
            bureau="experian", score=600, utilization_pct=55.0,
            derogatory_marks=1, collections=1))

        result = get_readiness_score(funding_db)
        # score=600 → 5pts, util=55% → 5pts, 0 inqs → 25pts, 2 derogs → 10pts = 45
        assert result["score"] == 45
        assert "Needs improvement" in result["factors"]["credit_score"]

    def test_high_utilization_penalty(self, funding_db):
        funding_db.save_profile(CreditProfile(
            bureau="experian", score=720, utilization_pct=60.0,
            derogatory_marks=0, collections=0))

        result = get_readiness_score(funding_db)
        # util=60% → 5pts (too high)
        assert result["factors"]["utilization"].endswith("Too high")

    def test_many_inquiries_penalty(self, funding_db):
        funding_db.save_profile(CreditProfile(bureau="experian", score=720,
                                               derogatory_marks=0, collections=0))
        now = datetime.utcnow().strftime("%Y-%m-%d")
        for i in range(8):
            funding_db.save_inquiry(Inquiry(
                date=now, bureau="experian", lender=f"Lender{i}"))

        result = get_readiness_score(funding_db)
        assert "Heavy" in result["factors"]["inquiries"]

    def test_derogatory_marks_penalty(self, funding_db):
        funding_db.save_profile(CreditProfile(
            bureau="experian", score=720, derogatory_marks=3, collections=2))

        result = get_readiness_score(funding_db)
        assert "Significant" in result["factors"]["derogatories"]


# ── Recommendations ──────────────────────────────────────────────────


class TestRecommendations:
    def test_empty_db_suggests_upload(self, funding_db):
        recs = get_recommendations(funding_db)
        assert len(recs) >= 1
        assert recs[0].title == "Upload Credit Report"
        assert recs[0].category == "action"

    def test_with_profile_generates_recs(self, funding_db):
        funding_db.save_profile(CreditProfile(
            bureau="experian", score=720, utilization_pct=22.0,
            derogatory_marks=0, collections=0))

        recs = get_recommendations(funding_db)
        # Should have inquiry mgmt recs at minimum (clean inquiry profile)
        assert len(recs) >= 1
        categories = {r.category for r in recs}
        assert "inquiry_mgmt" in categories

    def test_high_utilization_recommendation(self, funding_db):
        funding_db.save_profile(CreditProfile(
            bureau="experian", score=720, utilization_pct=55.0,
            derogatory_marks=0, collections=0))

        recs = get_recommendations(funding_db)
        titles = [r.title for r in recs]
        assert any("Utilization" in t or "utilization" in t.lower() for t in titles)


# ── Round Planning ───────────────────────────────────────────────────


class TestPlanRound:
    def test_no_products_returns_empty(self, funding_db):
        funding_db.save_profile(CreditProfile(bureau="experian", score=720))
        result = plan_round(funding_db)
        assert result == []

    def test_no_profile_returns_empty(self, funding_db):
        result = plan_round(funding_db)
        assert result == []

    def test_respects_max_apps(self, seeded_db):
        seeded_db.save_profile(CreditProfile(bureau="experian", score=750))
        result = plan_round(seeded_db, max_apps=3)
        assert len(result) <= 3

    def test_filters_by_score(self, funding_db):
        funding_db.save_profile(CreditProfile(bureau="experian", score=600))
        # Product requires 700+
        funding_db.save_product(FundingProduct(
            lender="Chase", product_name="Premium",
            product_type="credit_card", min_score=700))
        # Product requires 550+
        funding_db.save_product(FundingProduct(
            lender="Starter", product_name="Basic",
            product_type="credit_card", min_score=550))

        result = plan_round(funding_db)
        lenders = [p.lender for p in result]
        assert "Chase" not in lenders
        assert "Starter" in lenders

    def test_inquiry_sensitive_first(self, funding_db):
        funding_db.save_profile(CreditProfile(bureau="experian", score=750))
        funding_db.save_product(FundingProduct(
            lender="Regular", product_name="Card",
            product_type="credit_card", inquiry_sensitive=False,
            recommended_order=1))
        funding_db.save_product(FundingProduct(
            lender="Chase", product_name="Ink",
            product_type="credit_card", inquiry_sensitive=True,
            recommended_order=2))

        result = plan_round(funding_db)
        assert len(result) == 2
        assert result[0].lender == "Chase"  # inquiry-sensitive first

    def test_cooling_period(self, funding_db):
        """Recent completed round should still allow planning (cooling is advisory)."""
        funding_db.save_profile(CreditProfile(bureau="experian", score=750))
        funding_db.save_product(FundingProduct(
            lender="Test", product_name="Card",
            product_type="credit_card"))
        # Recent completed round
        funding_db.save_round(StrategyRound(
            name="R1", status="completed",
            executed_date=datetime.utcnow().strftime("%Y-%m-%d")))

        # plan_round doesn't enforce cooling — it's advisory via recommendations
        result = plan_round(funding_db)
        assert len(result) >= 1

    def test_excludes_already_applied(self, funding_db):
        funding_db.save_profile(CreditProfile(bureau="experian", score=750))
        funding_db.save_product(FundingProduct(
            lender="Chase", product_name="Ink Preferred",
            product_type="credit_card"))
        funding_db.save_product(FundingProduct(
            lender="Amex", product_name="Gold",
            product_type="credit_card"))
        # Already applied to Chase Ink Preferred
        funding_db.save_application(Application(
            product_type="credit_card", lender="Chase",
            product_name="Ink Preferred", status="approved"))

        result = plan_round(funding_db)
        lenders = [p.lender for p in result]
        assert "Chase" not in lenders
        assert "Amex" in lenders


# ── Readiness Score Bands ───────────────────────────────────────────


class TestReadinessScoreBands:
    def test_fair_score_band(self, funding_db):
        funding_db.save_profile(CreditProfile(
            bureau="experian", score=680, derogatory_marks=0, collections=0))
        result = get_readiness_score(funding_db)
        assert "Fair" in result["factors"]["credit_score"]

    def test_below_average_score_band(self, funding_db):
        funding_db.save_profile(CreditProfile(
            bureau="experian", score=630, derogatory_marks=0, collections=0))
        result = get_readiness_score(funding_db)
        assert "Below average" in result["factors"]["credit_score"]

    def test_good_utilization_band(self, funding_db):
        funding_db.save_profile(CreditProfile(
            bureau="experian", score=720, utilization_pct=20.0,
            derogatory_marks=0, collections=0))
        result = get_readiness_score(funding_db)
        assert "Good" in result["factors"]["utilization"]

    def test_high_utilization_band(self, funding_db):
        funding_db.save_profile(CreditProfile(
            bureau="experian", score=720, utilization_pct=40.0,
            derogatory_marks=0, collections=0))
        result = get_readiness_score(funding_db)
        assert "High" in result["factors"]["utilization"]

    def test_good_inquiry_band(self, funding_db):
        funding_db.save_profile(CreditProfile(
            bureau="experian", score=720, derogatory_marks=0, collections=0))
        now = datetime.utcnow().strftime("%Y-%m-%d")
        for i in range(2):
            funding_db.save_inquiry(Inquiry(
                date=now, bureau="experian", lender=f"Lender{i}"))
        result = get_readiness_score(funding_db)
        assert "Good" in result["factors"]["inquiries"]

    def test_moderate_inquiry_band(self, funding_db):
        funding_db.save_profile(CreditProfile(
            bureau="experian", score=720, derogatory_marks=0, collections=0))
        now = datetime.utcnow().strftime("%Y-%m-%d")
        for i in range(5):
            funding_db.save_inquiry(Inquiry(
                date=now, bureau="experian", lender=f"Lender{i}"))
        result = get_readiness_score(funding_db)
        assert "Moderate" in result["factors"]["inquiries"]

    def test_cooling_active(self, funding_db):
        funding_db.save_profile(CreditProfile(
            bureau="experian", score=720, derogatory_marks=0, collections=0))
        recent = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
        funding_db.save_round(StrategyRound(
            name="R1", status="completed", executed_date=recent))
        result = get_readiness_score(funding_db)
        assert "days until" in result["factors"]["cooling"]

    def test_cooling_complete(self, funding_db):
        funding_db.save_profile(CreditProfile(
            bureau="experian", score=720, derogatory_marks=0, collections=0))
        old = (datetime.utcnow() - timedelta(days=120)).strftime("%Y-%m-%d")
        funding_db.save_round(StrategyRound(
            name="R1", status="completed", executed_date=old))
        result = get_readiness_score(funding_db)
        assert "complete" in result["factors"]["cooling"].lower()


# ── Internal Recommendation Functions ───────────────────────────────


class TestScoreOptimization:
    def test_very_low_score(self):
        profile = CreditProfile(bureau="test", score=590)
        recs = _score_optimization(profile, 1)
        assert any("Build" in r.title for r in recs)

    def test_mid_score(self):
        profile = CreditProfile(bureau="test", score=660)
        recs = _score_optimization(profile, 1)
        assert any("Improvement" in r.title or "Improve" in r.title for r in recs)


class TestUtilizationOptimization:
    def test_high_utilization(self):
        profile = CreditProfile(bureau="test", score=720, utilization_pct=35.0)
        recs = _utilization_optimization(profile, 1)
        assert len(recs) >= 1
        assert recs[0].impact == "medium"

    def test_moderate_utilization(self):
        profile = CreditProfile(bureau="test", score=720, utilization_pct=15.0)
        recs = _utilization_optimization(profile, 1)
        assert len(recs) >= 1

    def test_critical_utilization(self):
        profile = CreditProfile(bureau="test", score=720, utilization_pct=60.0)
        recs = _utilization_optimization(profile, 1)
        assert len(recs) >= 1
        assert recs[0].impact == "high"


class TestInquiryManagement:
    def test_with_recent_inquiries_targets_bureau(self):
        now = datetime.utcnow().strftime("%Y-%m-%d")
        inquiries = [
            Inquiry(date=now, bureau="experian", lender="Chase"),
            Inquiry(date=now, bureau="experian", lender="Amex"),
            Inquiry(date=now, bureau="transunion", lender="CapOne"),
        ]
        recs = _inquiry_management(inquiries, [], 1)
        assert any("Target" in r.title for r in recs)

    def test_chase_524_eligible(self):
        now = datetime.utcnow().strftime("%Y-%m-%d")
        inquiries = [Inquiry(date=now, bureau="experian", lender="Test")]
        apps = [
            Application(product_type="credit_card", lender=f"L{i}",
                        status="approved", applied_date=now)
            for i in range(2)
        ]
        recs = _inquiry_management(inquiries, apps, 1)
        assert any("5/24 Eligible" in r.title for r in recs)

    def test_chase_524_locked_out(self):
        now = datetime.utcnow().strftime("%Y-%m-%d")
        inquiries = [Inquiry(date=now, bureau="experian", lender="Test")]
        apps = [
            Application(product_type="credit_card", lender=f"L{i}",
                        status="approved", applied_date=now)
            for i in range(6)
        ]
        recs = _inquiry_management(inquiries, apps, 1)
        assert any("Locked Out" in r.title for r in recs)


class TestCoolingPeriod:
    def test_active_cooling(self):
        recent = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
        rnd = StrategyRound(name="R1", status="completed", executed_date=recent)
        recs = _cooling_period_check(rnd, 1)
        assert len(recs) == 1
        assert "Remaining" in recs[0].title

    def test_cooling_complete(self):
        old = (datetime.utcnow() - timedelta(days=120)).strftime("%Y-%m-%d")
        rnd = StrategyRound(name="R1", status="completed", executed_date=old)
        recs = _cooling_period_check(rnd, 1)
        assert len(recs) == 1
        assert "Complete" in recs[0].title

    def test_bad_date_returns_empty(self):
        rnd = StrategyRound(name="R1", status="completed", executed_date="invalid")
        recs = _cooling_period_check(rnd, 1)
        assert recs == []

    def test_no_round_returns_empty(self):
        recs = _cooling_period_check(None, 1)
        assert recs == []


class TestEligibleProducts:
    def test_with_eligible_products(self, seeded_db):
        seeded_db.save_profile(CreditProfile(bureau="experian", score=750))
        profile = seeded_db.get_latest_profile()
        products = seeded_db.get_products()
        recs = _eligible_products(profile, [], [], products, 1)
        assert len(recs) == 1
        assert "Eligible" in recs[0].title

    def test_no_eligible_products(self, funding_db):
        profile = CreditProfile(bureau="experian", score=400)
        funding_db.save_profile(profile)
        funding_db.save_product(FundingProduct(
            lender="Chase", product_name="Premium",
            product_type="credit_card", min_score=700))
        profile = funding_db.get_latest_profile()
        products = funding_db.get_products()
        recs = _eligible_products(profile, [], [], products, 1)
        assert any("No New" in r.title for r in recs)


class TestApplicationOrder:
    def test_generates_order(self, seeded_db):
        seeded_db.save_profile(CreditProfile(bureau="experian", score=750))
        profile = seeded_db.get_latest_profile()
        products = seeded_db.get_products()
        recs = _application_order(profile, [], [], products, 1)
        assert len(recs) >= 1
        assert "Application Order" in recs[0].title

    def test_empty_when_no_products(self, funding_db):
        profile = CreditProfile(bureau="experian", score=750)
        recs = _application_order(profile, [], [], [], 1)
        assert recs == []


class TestDerogatoryCheck:
    def test_with_derogatory_marks(self):
        profile = CreditProfile(bureau="test", derogatory_marks=2, collections=1)
        recs = _derogatory_check(profile, 1)
        assert len(recs) == 1
        assert "3 Negative" in recs[0].title

    def test_clean_record(self):
        profile = CreditProfile(bureau="test", derogatory_marks=0, collections=0)
        recs = _derogatory_check(profile, 1)
        assert recs == []
