"""Tests for funding.database CRUD operations, seeding, and security."""

import pytest
from datetime import datetime

from funding.models import (
    Application, CreditProfile, Inquiry, PartnerProgram,
    Referral, ReferralClient, StrategyRound,
)
from funding.product_catalog import seed_catalog, seed_partner_programs


# ── Credit Profiles ──────────────────────────────────────────────────


class TestCreditProfiles:
    def test_save_and_get_profile(self, funding_db, sample_profile):
        pid = funding_db.save_profile(sample_profile)
        assert pid >= 1

        fetched = funding_db.get_latest_profile(bureau="experian")
        assert fetched is not None
        assert fetched.score == 720
        assert fetched.bureau == "experian"
        assert fetched.id == pid

    def test_save_profile_with_inquiries(self, funding_db, sample_profile):
        inquiries = [
            Inquiry(date="2026-01-15", bureau="experian", lender="Chase",
                    falls_off_date="2028-01-15"),
            Inquiry(date="2026-02-01", bureau="transunion", lender="Amex",
                    falls_off_date="2028-02-01"),
        ]
        pid = funding_db.save_profile_with_inquiries(sample_profile, inquiries)
        assert pid >= 1

        # Profile saved
        profile = funding_db.get_latest_profile()
        assert profile.score == 720

        # Inquiries saved
        inqs = funding_db.get_inquiries()
        assert len(inqs) == 2
        bureaus = {i.bureau for i in inqs}
        assert bureaus == {"experian", "transunion"}

    def test_save_profile_with_inquiries_rollback(self, funding_db, sample_profile):
        """If inquiry insert fails, profile should also be rolled back."""

        inquiries = [
            Inquiry(date="2026-01-15", bureau="experian", lender="Chase"),
            Inquiry(date="2026-02-01", bureau="transunion", lender="Amex"),
        ]

        call_count = 0
        original_get_conn = funding_db._get_conn

        class FailingConn:
            """Wraps a real connection, failing on the 2nd inquiry INSERT."""
            def __init__(self, real_conn):
                self._conn = real_conn

            def __getattr__(self, name):
                return getattr(self._conn, name)

            def execute(self, sql, params=()):
                nonlocal call_count
                if "INSERT INTO inquiries" in sql:
                    call_count += 1
                    if call_count >= 2:
                        raise RuntimeError("Simulated DB failure")
                return self._conn.execute(sql, params)

        def patched_get_conn():
            return FailingConn(original_get_conn())

        funding_db._get_conn = patched_get_conn

        with pytest.raises(RuntimeError, match="Simulated"):
            funding_db.save_profile_with_inquiries(sample_profile, inquiries)

        # Restore and check profile was NOT committed
        funding_db._get_conn = original_get_conn
        assert funding_db.get_latest_profile() is None

    def test_get_latest_profile_by_bureau(self, funding_db):
        p1 = CreditProfile(bureau="experian", score=700)
        p2 = CreditProfile(bureau="transunion", score=710)
        funding_db.save_profile(p1)
        funding_db.save_profile(p2)

        exp = funding_db.get_latest_profile(bureau="experian")
        assert exp.score == 700
        tu = funding_db.get_latest_profile(bureau="transunion")
        assert tu.score == 710

    def test_get_all_profiles(self, funding_db):
        funding_db.save_profile(CreditProfile(bureau="experian", score=700))
        funding_db.save_profile(CreditProfile(bureau="transunion", score=710))
        funding_db.save_profile(CreditProfile(bureau="equifax", score=720))

        all_profiles = funding_db.get_all_profiles()
        assert len(all_profiles) == 3


# ── Applications ─────────────────────────────────────────────────────


class TestApplications:
    def test_save_and_get_application(self, funding_db, sample_application):
        app_id = funding_db.save_application(sample_application)
        assert app_id >= 1

        fetched = funding_db.get_application(app_id)
        assert fetched is not None
        assert fetched.lender == "Chase"
        assert fetched.status == "planned"

    def test_update_application(self, funding_db, sample_application):
        app_id = funding_db.save_application(sample_application)
        ok = funding_db.update_application(app_id, status="approved", amount_approved=15000.0)
        assert ok is True

        fetched = funding_db.get_application(app_id)
        assert fetched.status == "approved"
        assert fetched.amount_approved == 15000.0

    def test_get_applications_by_status(self, funding_db):
        funding_db.save_application(Application(product_type="cc", lender="Chase", status="planned"))
        funding_db.save_application(Application(product_type="cc", lender="Amex", status="approved"))
        funding_db.save_application(Application(product_type="cc", lender="CapOne", status="planned"))

        planned = funding_db.get_applications(status="planned")
        assert len(planned) == 2
        approved = funding_db.get_applications(status="approved")
        assert len(approved) == 1

    def test_get_applications_by_round(self, funding_db):
        rnd_id = funding_db.save_round(StrategyRound(name="R1", status="planning"))
        funding_db.save_application(Application(product_type="cc", lender="Chase", round_id=rnd_id))
        funding_db.save_application(Application(product_type="cc", lender="Amex"))

        by_round = funding_db.get_applications(round_id=rnd_id)
        assert len(by_round) == 1
        assert by_round[0].lender == "Chase"


# ── Inquiries ────────────────────────────────────────────────────────


class TestInquiries:
    def test_save_and_get_inquiries(self, funding_db):
        inq = Inquiry(date="2026-01-15", bureau="experian", lender="Chase",
                       falls_off_date="2028-01-15")
        iid = funding_db.save_inquiry(inq)
        assert iid >= 1

        inqs = funding_db.get_inquiries()
        assert len(inqs) == 1
        assert inqs[0].lender == "Chase"

    def test_get_inquiries_active_only(self, funding_db):
        # Active: falls off in the future
        funding_db.save_inquiry(Inquiry(
            date="2026-01-15", bureau="experian", lender="Chase",
            falls_off_date="2028-01-15"))
        # Expired: falls off in the past
        funding_db.save_inquiry(Inquiry(
            date="2024-01-15", bureau="transunion", lender="Amex",
            falls_off_date="2025-01-15"))

        active = funding_db.get_inquiries(active_only=True)
        assert len(active) == 1
        assert active[0].lender == "Chase"

    def test_get_inquiry_counts_by_bureau(self, funding_db):
        now = datetime.utcnow().strftime("%Y-%m-%d")
        funding_db.save_inquiry(Inquiry(date=now, bureau="experian", lender="Chase"))
        funding_db.save_inquiry(Inquiry(date=now, bureau="experian", lender="Amex"))
        funding_db.save_inquiry(Inquiry(date=now, bureau="transunion", lender="CapOne"))

        counts = funding_db.get_inquiry_counts_by_bureau(12)
        assert counts.get("experian") == 2
        assert counts.get("transunion") == 1


# ── Strategy Rounds ──────────────────────────────────────────────────


class TestStrategyRounds:
    def test_save_and_get_round(self, funding_db):
        rnd = StrategyRound(name="Round 1", status="planning", target_total=50000.0)
        rid = funding_db.save_round(rnd)
        assert rid >= 1

        rounds = funding_db.get_rounds()
        assert len(rounds) == 1
        assert rounds[0].name == "Round 1"

    def test_update_round(self, funding_db):
        rid = funding_db.save_round(StrategyRound(name="R1", status="planning"))
        ok = funding_db.update_round(rid, status="completed", actual_total=45000.0)
        assert ok is True

        rounds = funding_db.get_rounds(status="completed")
        assert len(rounds) == 1
        assert rounds[0].actual_total == 45000.0

    def test_get_last_completed_round(self, funding_db):
        funding_db.save_round(StrategyRound(
            name="R1", status="completed",
            executed_date="2025-12-01"))
        funding_db.save_round(StrategyRound(
            name="R2", status="completed",
            executed_date="2026-02-01"))
        funding_db.save_round(StrategyRound(
            name="R3", status="planning"))

        last = funding_db.get_last_completed_round()
        assert last is not None
        assert last.name == "R2"


# ── Referrals ────────────────────────────────────────────────────────


class TestReferrals:
    def _setup_referral(self, db):
        """Create a client + product + referral and return IDs."""
        from funding.models import FundingProduct
        pid = db.save_product(FundingProduct(
            lender="Chase", product_name="Ink Preferred",
            product_type="credit_card", has_referral=True,
            referral_commission_type="points",
            referral_commission_value=20000,
            referral_commission_display="20K UR points",
        ))
        cid = db.save_referral_client(ReferralClient(name="John Doe", email="john@test.com"))
        ref = Referral(client_id=cid, product_id=pid, referral_date="2026-02-01",
                        expected_commission=250.0)
        rid = db.save_referral(ref)
        return rid, cid, pid

    def test_save_and_get_referral(self, funding_db):
        rid, cid, pid = self._setup_referral(funding_db)
        refs = funding_db.get_referrals()
        assert len(refs) == 1
        assert refs[0].client_name == "John Doe"
        assert refs[0].lender == "Chase"

    def test_get_referral_by_id(self, funding_db):
        rid, _, _ = self._setup_referral(funding_db)
        ref = funding_db.get_referral_by_id(rid)
        assert ref is not None
        assert ref.id == rid
        assert ref.client_name == "John Doe"
        assert ref._commission_type == "points"
        assert ref._commission_value == 20000

    def test_update_referral(self, funding_db):
        rid, _, _ = self._setup_referral(funding_db)
        ok = funding_db.update_referral(rid, status="funded", funded_amount=10000.0)
        assert ok is True

        ref = funding_db.get_referral_by_id(rid)
        assert ref.status == "funded"
        assert ref.funded_amount == 10000.0

    def test_get_referral_summary(self, funding_db):
        rid, _, _ = self._setup_referral(funding_db)
        summary = funding_db.get_referral_summary()
        assert summary["total_referrals"] == 1
        assert summary["active"] == 1  # submitted status


# ── Partner Programs ─────────────────────────────────────────────────


class TestPartnerPrograms:
    def test_save_and_get_partner_program(self, funding_db):
        prog = PartnerProgram(
            lender="Chase", program_name="Refer-a-Friend",
            program_type="referral", priority=1,
            commission_display="20K UR points")
        pid = funding_db.save_partner_program(prog)
        assert pid >= 1

        progs = funding_db.get_partner_programs()
        assert len(progs) == 1
        assert progs[0].lender == "Chase"
        assert progs[0].program_type == "referral"

    def test_update_partner_program(self, funding_db):
        prog = PartnerProgram(lender="Chase", program_name="Refer-a-Friend",
                               program_type="referral")
        pid = funding_db.save_partner_program(prog)
        ok = funding_db.update_partner_program(pid, status="active",
                                                portal_url="https://chase.com/portal")
        assert ok is True

        progs = funding_db.get_partner_programs(status="active")
        assert len(progs) == 1
        assert progs[0].portal_url == "https://chase.com/portal"

    def test_get_partner_program_summary(self, funding_db):
        funding_db.save_partner_program(PartnerProgram(
            lender="Chase", program_name="R", program_type="referral", status="active"))
        funding_db.save_partner_program(PartnerProgram(
            lender="Amex", program_name="R", program_type="referral", status="not_started"))
        funding_db.save_partner_program(PartnerProgram(
            lender="Brex", program_name="P", program_type="partner", status="applied",
            has_api=True))

        summary = funding_db.get_partner_program_summary()
        assert summary["total"] == 3
        assert summary["active"] == 1
        assert summary["not_started"] == 1
        assert summary["in_progress"] == 1
        assert summary["api_ready"] == 1


# ── Catalog Seeding ──────────────────────────────────────────────────


class TestCatalogSeeding:
    def test_seed_catalog_populates_products(self, funding_db):
        count = seed_catalog(funding_db)
        assert count > 0
        assert funding_db.product_count() == count

    def test_seed_catalog_idempotent(self, funding_db):
        c1 = seed_catalog(funding_db)
        c2 = seed_catalog(funding_db)
        assert c1 > 0
        assert c2 == 0  # Second call inserts nothing
        assert funding_db.product_count() == c1

    def test_seed_partner_programs(self, funding_db):
        count = seed_partner_programs(funding_db)
        assert count > 0
        assert funding_db.partner_program_count() == count

    def test_seed_partner_programs_idempotent(self, funding_db):
        c1 = seed_partner_programs(funding_db)
        c2 = seed_partner_programs(funding_db)
        assert c1 > 0
        assert c2 == 0
        assert funding_db.partner_program_count() == c1


# ── Security: Column Allowlists ──────────────────────────────────────


class TestColumnAllowlists:
    def test_update_application_rejects_bad_column(self, funding_db, sample_application):
        app_id = funding_db.save_application(sample_application)
        # 'id' is not in the allowlist
        result = funding_db.update_application(app_id, id=999)
        assert result is False  # ValueError caught, returns False

    def test_update_application_rejects_sql_injection(self, funding_db, sample_application):
        app_id = funding_db.save_application(sample_application)
        result = funding_db.update_application(app_id, **{"status; DROP TABLE applications--": "x"})
        assert result is False

    def test_update_round_rejects_bad_column(self, funding_db):
        rid = funding_db.save_round(StrategyRound(name="R1", status="planning"))
        result = funding_db.update_round(rid, id=999)
        assert result is False

    def test_update_referral_rejects_bad_column(self, funding_db):
        from funding.models import FundingProduct
        pid = funding_db.save_product(FundingProduct(
            lender="Chase", product_name="Ink", product_type="cc"))
        cid = funding_db.save_referral_client(ReferralClient(name="Test"))
        rid = funding_db.save_referral(Referral(
            client_id=cid, product_id=pid, referral_date="2026-01-01"))
        result = funding_db.update_referral(rid, client_id=999)
        assert result is False

    def test_update_partner_rejects_bad_column(self, funding_db):
        pid = funding_db.save_partner_program(PartnerProgram(
            lender="Chase", program_name="R", program_type="referral"))
        result = funding_db.update_partner_program(pid, lender="Hack")
        assert result is False

    def test_update_application_allows_valid_columns(self, funding_db, sample_application):
        app_id = funding_db.save_application(sample_application)
        ok = funding_db.update_application(
            app_id, status="approved", amount_approved=25000.0,
            credit_limit=30000.0, notes="Approved!")
        assert ok is True

        fetched = funding_db.get_application(app_id)
        assert fetched.status == "approved"
        assert fetched.amount_approved == 25000.0
        assert fetched.credit_limit == 30000.0

    def test_update_referral_allows_valid_columns(self, funding_db):
        from funding.models import FundingProduct
        pid = funding_db.save_product(FundingProduct(
            lender="Chase", product_name="Ink", product_type="cc"))
        cid = funding_db.save_referral_client(ReferralClient(name="Test"))
        rid = funding_db.save_referral(Referral(
            client_id=cid, product_id=pid, referral_date="2026-01-01"))

        ok = funding_db.update_referral(rid, status="funded",
                                         funded_amount=10000.0,
                                         actual_commission=500.0)
        assert ok is True

    def test_update_partner_allows_valid_columns(self, funding_db):
        pid = funding_db.save_partner_program(PartnerProgram(
            lender="Chase", program_name="R", program_type="referral"))
        ok = funding_db.update_partner_program(
            pid, status="active", portal_url="https://portal.com",
            referral_link="https://ref.link", contact_name="Jane")
        assert ok is True

        progs = funding_db.get_partner_programs(status="active")
        assert len(progs) == 1
        assert progs[0].contact_name == "Jane"


# ── Funding Summary ──────────────────────────────────────────────────


class TestFundingSummary:
    def test_get_funding_summary_empty(self, funding_db):
        summary = funding_db.get_funding_summary()
        assert summary["total_applications"] == 0
        assert summary["approved"] == 0
        assert summary["approval_rate"] == 0
        assert summary["latest_score"] is None

    def test_get_funding_summary_with_data(self, funding_db, sample_profile):
        funding_db.save_profile(sample_profile)
        funding_db.save_application(Application(
            product_type="cc", lender="Chase", status="approved",
            amount_approved=15000.0))
        funding_db.save_application(Application(
            product_type="cc", lender="Amex", status="denied"))

        summary = funding_db.get_funding_summary()
        assert summary["total_applications"] == 2
        assert summary["approved"] == 1
        assert summary["denied"] == 1
        assert summary["total_funding_approved"] == 15000.0
        assert summary["approval_rate"] == 50.0
        assert summary["latest_score"] == 720
