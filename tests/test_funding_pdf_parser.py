"""Tests for funding.pdf_parser — bureau detection, score/field extraction, health analysis."""

import pytest

from funding.models import CreditProfile, Inquiry
from funding.pdf_parser import (
    _add_years,
    _detect_bureau,
    _extract_account_ages,
    _extract_balance_breakdown,
    _extract_common_fields,
    _extract_dollar,
    _extract_float,
    _extract_inquiries,
    _extract_number,
    _extract_score,
    _find_section,
    _normalize_date,
    _parse_aggregator,
    _parse_equifax,
    _parse_experian,
    _parse_generic,
    _parse_transunion,
    analyze_credit_health,
)


# ── Bureau Detection ────────────────────────────────────────────────


class TestDetectBureau:
    def test_experian(self):
        assert _detect_bureau("Your Experian credit report") == "experian"

    def test_transunion(self):
        assert _detect_bureau("TransUnion credit file") == "transunion"

    def test_transunion_with_space(self):
        assert _detect_bureau("Trans Union report") == "transunion"

    def test_equifax(self):
        assert _detect_bureau("Equifax credit information") == "equifax"

    def test_credit_karma_priority(self):
        # Credit Karma mentions bureau names but should be detected as aggregator
        assert _detect_bureau("Credit Karma - Your Experian Score") == "credit_karma"

    def test_credit_sesame(self):
        assert _detect_bureau("CreditSesame your free score") == "credit_sesame"

    def test_unknown(self):
        assert _detect_bureau("Some random text with no bureau markers") == "unknown"

    def test_annualcreditreport_experian_dominant(self):
        text = "ANNUALCREDITREPORT Experian Experian Experian TransUnion"
        assert _detect_bureau(text) == "experian"

    def test_annualcreditreport_transunion_dominant(self):
        text = "ANNUALCREDITREPORT TransUnion TransUnion Equifax"
        assert _detect_bureau(text) == "transunion"

    def test_annualcreditreport_equifax_fallback(self):
        text = "ANNUALCREDITREPORT data"
        assert _detect_bureau(text) == "equifax"


# ── Score Extraction ────────────────────────────────────────────────


class TestExtractScore:
    def test_fico_label(self):
        assert _extract_score("FICO Score 8: 742") == 742

    def test_vantagescore_label(self):
        assert _extract_score("VantageScore 3.0: 720") == 720

    def test_your_score_is(self):
        assert _extract_score("Your Credit Score is 685") == 685

    def test_ratio_format(self):
        assert _extract_score("Your score: 710/850") == 710

    def test_out_of_format(self):
        assert _extract_score("Score 730 out of 850") == 730

    def test_score_range(self):
        assert _extract_score("Score Range: 695") == 695

    def test_out_of_range_low(self):
        assert _extract_score("Score: 290") is None

    def test_out_of_range_high(self):
        assert _extract_score("Score: 900") is None

    def test_no_match(self):
        assert _extract_score("No score information here") is None


# ── Extract Helpers ─────────────────────────────────────────────────


class TestExtractNumber:
    def test_basic_match(self):
        assert _extract_number("Total Accounts: 15", [r"Total\s+Accounts?\s*:\s*(\d+)"]) == 15

    def test_na_skipped(self):
        assert _extract_number("Total Accounts: N/A", [r"Total\s+Accounts?\s*:\s*(.+)"]) is None

    def test_no_match(self):
        assert _extract_number("No data", [r"Total\s+Accounts?\s*:\s*(\d+)"]) is None

    def test_comma_separated(self):
        assert _extract_number("Count: 1,234", [r"Count:\s*(\d[\d,]*)"]) == 1234

    def test_fallback_pattern(self):
        assert _extract_number("15 Total Accounts", [
            r"^no_match$",
            r"(\d+)\s+Total\s+Accounts?",
        ]) == 15


class TestExtractFloat:
    def test_basic_match(self):
        assert _extract_float("Utilization: 22.5%", [r"Utilization:\s*([\d.]+)%"]) == 22.5

    def test_percent_stripped(self):
        assert _extract_float("Usage 45%", [r"Usage\s*([\d.]+)%"]) == 45.0

    def test_na_skipped(self):
        assert _extract_float("Utilization: N/A", [r"Utilization:\s*(.+)"]) is None

    def test_no_match(self):
        assert _extract_float("No data", [r"Util:\s*([\d.]+)"]) is None


class TestExtractDollar:
    def test_basic_match(self):
        assert _extract_dollar("Total Limit: $50,000", [r"Total\s+Limit:\s*\$?([\d,]+)"]) == 50000.0

    def test_without_dollar_sign(self):
        assert _extract_dollar("Balance: 12500.00", [r"Balance:\s*\$?([\d,.]+)"]) == 12500.0

    def test_na_skipped(self):
        assert _extract_dollar("Balance: N/A", [r"Balance:\s*(.+)"]) is None

    def test_no_match(self):
        assert _extract_dollar("No data", [r"Limit:\s*\$?([\d,]+)"]) is None


# ── Bureau-Specific Parsers ─────────────────────────────────────────


class TestBureauParsers:
    def _make_profile(self):
        return CreditProfile(bureau="test")

    def test_parse_experian(self):
        text = """
        Experian Credit Report
        FICO Score: 745
        Total Accounts: 15
        Open Accounts: 10
        Closed Accounts: 5
        Utilization: 18.5%
        Payment History: 98%
        Derogatory Marks: 0
        Collections: 0
        Total Credit Limit: $75,000
        Total Balance: $13,500
        Average Age of Accounts: 5 years, 3 months
        Oldest Account: 12 years
        Revolving Balance: $8,500
        Installment Balance: $5,000
        """
        p = self._make_profile()
        _parse_experian(text, p)
        assert p.score == 745
        assert p.total_accounts == 15
        assert p.open_accounts == 10
        assert p.utilization_pct == 18.5
        assert p.payment_history_pct == 98.0
        assert p.derogatory_marks == 0
        assert p.total_credit_limit == 75000.0
        assert p.total_balance == 13500.0

    def test_parse_transunion(self):
        text = """
        TransUnion Credit File
        VantageScore 3.0: 720
        Total Accounts: 12
        Open Accounts: 8
        Closed Accounts: 4
        Credit Utilization: 25.0%
        Payment History: 96%
        Derogatory Items: 1
        Collections: 0
        Total Credit Limit: $60,000
        Total Balances: $15,000
        """
        p = self._make_profile()
        _parse_transunion(text, p)
        assert p.score == 720
        assert p.total_accounts == 12
        assert p.open_accounts == 8
        assert p.utilization_pct == 25.0
        assert p.derogatory_marks == 1
        assert p.total_credit_limit == 60000.0

    def test_parse_equifax(self):
        text = """
        Equifax Credit Report
        FICO Score: 710
        Total Accounts: 10
        Open Accounts: 7
        Utilization: 30.0%
        Payment History: 95%
        Derogatory Marks: 0
        Collections Accounts: 0
        Credit Limit: $45,000
        Total Balance: $13,500
        """
        p = self._make_profile()
        _parse_equifax(text, p)
        assert p.score == 710
        assert p.total_accounts == 10
        assert p.utilization_pct == 30.0
        assert p.total_credit_limit == 45000.0

    def test_parse_aggregator(self):
        text = """
        Credit Karma Report
        Your Credit Score is 735
        Total Accounts: 14
        Open Accounts: 9
        Closed Accounts: 5
        Credit Card Utilization: 12.0%
        On-Time Payments: 99%
        Derogatory Marks: 0
        Collections: 0
        Total Credit Limit: $80,000
        Total Balance: $9,600
        """
        p = self._make_profile()
        _parse_aggregator(text, p)
        assert p.score == 735
        assert p.total_accounts == 14
        assert p.utilization_pct == 12.0
        assert p.payment_history_pct == 99.0

    def test_parse_generic(self):
        text = """
        Credit Report Summary
        Score: 700
        Total Accounts: 8
        Open Accounts: 5
        Utilization: 20%
        Payment History: 97%
        Derogatory: 0
        Collections: 0
        Total Credit Limit: $40,000
        Total Balance: $8,000
        """
        p = self._make_profile()
        _parse_generic(text, p)
        assert p.score == 700
        assert p.total_accounts == 8
        assert p.utilization_pct == 20.0
        assert p.total_credit_limit == 40000.0


# ── Common Field Extraction ─────────────────────────────────────────


class TestCommonFieldExtraction:
    def test_new_accounts_6mo(self):
        p = CreditProfile(bureau="test")
        _extract_common_fields("New Accounts (6mo): 2", p)
        assert p.new_accounts_6mo == 2

    def test_infer_closed_accounts(self):
        p = CreditProfile(bureau="test", total_accounts=15, open_accounts=10)
        _extract_common_fields("some text", p)
        assert p.closed_accounts == 5

    def test_hard_inquiry_count(self):
        p = CreditProfile(bureau="test")
        _extract_common_fields("Hard Inquiries: 4", p)
        assert p.hard_inquiries_count == 4

    def test_does_not_overwrite_existing(self):
        p = CreditProfile(bureau="test", new_accounts_6mo=3, hard_inquiries_count=2)
        _extract_common_fields("New Accounts (6mo): 99\nHard Inquiries: 99", p)
        assert p.new_accounts_6mo == 3
        assert p.hard_inquiries_count == 2


class TestBalanceBreakdown:
    def test_revolving_and_installment(self):
        p = CreditProfile(bureau="test")
        _extract_balance_breakdown("Revolving Balance: $8,500\nInstallment Balance: $5,000", p)
        assert p.revolving_balance == 8500.0
        assert p.installment_balance == 5000.0

    def test_no_match_stays_none(self):
        p = CreditProfile(bureau="test")
        _extract_balance_breakdown("nothing here", p)
        assert p.revolving_balance is None
        assert p.installment_balance is None


class TestAccountAges:
    def test_years_and_months(self):
        p = CreditProfile(bureau="test")
        _extract_account_ages("Average Age of Accounts: 4 years, 6 months\nOldest Account: 12 years", p)
        assert p.avg_age_years == pytest.approx(4.5)
        assert p.oldest_account_years == 12.0

    def test_years_only(self):
        p = CreditProfile(bureau="test")
        _extract_account_ages("Avg Age: 3.5 years", p)
        assert p.avg_age_years == pytest.approx(3.5)

    def test_no_match_stays_none(self):
        p = CreditProfile(bureau="test")
        _extract_account_ages("no age info", p)
        assert p.avg_age_years is None
        assert p.oldest_account_years is None


# ── Inquiry Extraction ──────────────────────────────────────────────


class TestInquiryExtraction:
    def test_lender_date_format(self):
        text = (
            "Hard Inquiries\n"
            "CHASE BANK          01/15/2025\n"
            "AMEX                03/20/2025\n"
            "\n"
            "Account Information\nmore stuff"
        )
        inqs = _extract_inquiries(text, "experian")
        assert len(inqs) >= 1
        lenders = {i.lender for i in inqs}
        assert "AMEX" in lenders or "CHASE BANK" in lenders
        assert inqs[0].bureau == "experian"

    def test_date_first_format(self):
        text = "Hard Inquiries\n01/15/2025  WELLS FARGO\n\nAccount Information\nmore stuff"
        inqs = _extract_inquiries(text, "transunion")
        assert len(inqs) == 1
        assert inqs[0].lender.startswith("WELLS FARGO")

    def test_iso_date_format(self):
        text = "Inquiries\nCAPITAL ONE  2025-02-10\nPersonal Information"
        inqs = _extract_inquiries(text, "equifax")
        assert len(inqs) == 1
        assert inqs[0].date == "2025-02-10"

    def test_deduplication(self):
        text = "Hard Inquiries\nCHASE BANK  01/15/2025\nCHASE BANK  01/15/2025\nAccount Information"
        inqs = _extract_inquiries(text, "experian")
        assert len(inqs) == 1

    def test_aggregator_bureau_unknown(self):
        text = "Credit Inquiries\nCHASE  01/15/2025\nSummary"
        inqs = _extract_inquiries(text, "credit_karma")
        assert len(inqs) == 1
        assert inqs[0].bureau == "unknown"

    def test_no_inquiry_section(self):
        inqs = _extract_inquiries("No inquiry section here at all", "experian")
        assert inqs == []

    def test_falls_off_date_calculated(self):
        text = "Hard Inquiries\nCHASE BANK          01/15/2025\n\nAccount Information\nmore"
        inqs = _extract_inquiries(text, "experian")
        assert len(inqs) >= 1
        assert inqs[0].falls_off_date == "2027-01-15"


class TestNormalizeDate:
    def test_us_format(self):
        assert _normalize_date("01/15/2025") == "2025-01-15"

    def test_us_short_year(self):
        assert _normalize_date("01/15/25") == "2025-01-15"

    def test_month_name_format(self):
        assert _normalize_date("Jan 15, 2025") == "2025-01-15"

    def test_iso_format(self):
        assert _normalize_date("2025-01-15") == "2025-01-15"

    def test_full_month_name(self):
        assert _normalize_date("January 15, 2025") == "2025-01-15"

    def test_invalid_date(self):
        assert _normalize_date("not a date") is None

    def test_year_out_of_range(self):
        assert _normalize_date("01/15/1990") is None


class TestAddYears:
    def test_normal_date(self):
        assert _add_years("2025-01-15", 2) == "2027-01-15"

    def test_leap_year_feb_29(self):
        # Feb 29 + 1 year should handle gracefully
        result = _add_years("2024-02-29", 1)
        assert result == "2025-02-28"


# ── Find Section ────────────────────────────────────────────────────


class TestFindSection:
    def test_finds_section(self):
        text = "Intro text\nHard Inquiries\nCHASE BANK 01/15/2025\nAccount Information\nmore text"
        section = _find_section(text, [r"Hard\s+Inquiries"])
        assert section is not None
        assert "CHASE BANK" in section

    def test_no_match(self):
        assert _find_section("nothing here", [r"Hard\s+Inquiries"]) is None


# ── Credit Health Analysis ──────────────────────────────────────────


class TestAnalyzeCreditHealth:
    def test_excellent_profile(self):
        p = CreditProfile(
            bureau="test", score=760, utilization_pct=5.0,
            payment_history_pct=99.5, derogatory_marks=0, collections=0,
            avg_age_years=8.0, hard_inquiries_count=0,
        )
        result = analyze_credit_health(p)
        assert result["overall_rating"] == "Excellent"
        assert len(result["strengths"]) >= 4
        assert len(result["warnings"]) == 0

    def test_poor_profile(self):
        p = CreditProfile(
            bureau="test", score=580, utilization_pct=70.0,
            payment_history_pct=85.0, derogatory_marks=3, collections=2,
            avg_age_years=0.5, hard_inquiries_count=10,
        )
        result = analyze_credit_health(p)
        assert result["overall_rating"] == "Poor"
        assert len(result["warnings"]) >= 4

    def test_good_score(self):
        p = CreditProfile(bureau="test", score=720)
        result = analyze_credit_health(p)
        assert result["overall_rating"] == "Good"

    def test_fair_score(self):
        p = CreditProfile(bureau="test", score=680)
        result = analyze_credit_health(p)
        assert result["overall_rating"] == "Fair"

    def test_below_average_score(self):
        p = CreditProfile(bureau="test", score=630)
        result = analyze_credit_health(p)
        assert result["overall_rating"] == "Below Average"

    def test_utilization_optimal(self):
        p = CreditProfile(bureau="test", utilization_pct=8.0)
        result = analyze_credit_health(p)
        factors = {f["name"]: f for f in result["factors"]}
        assert factors["Utilization"]["rating"] == "Optimal"

    def test_utilization_good(self):
        p = CreditProfile(bureau="test", utilization_pct=25.0)
        result = analyze_credit_health(p)
        factors = {f["name"]: f for f in result["factors"]}
        assert factors["Utilization"]["rating"] == "Good"

    def test_utilization_high(self):
        p = CreditProfile(bureau="test", utilization_pct=45.0)
        result = analyze_credit_health(p)
        factors = {f["name"]: f for f in result["factors"]}
        assert factors["Utilization"]["rating"] == "High"

    def test_utilization_critical(self):
        p = CreditProfile(bureau="test", utilization_pct=65.0)
        result = analyze_credit_health(p)
        factors = {f["name"]: f for f in result["factors"]}
        assert factors["Utilization"]["rating"] == "Critical"

    def test_payment_perfect(self):
        p = CreditProfile(bureau="test", payment_history_pct=99.5)
        result = analyze_credit_health(p)
        factors = {f["name"]: f for f in result["factors"]}
        assert factors["Payment History"]["rating"] == "Perfect"

    def test_payment_excellent(self):
        p = CreditProfile(bureau="test", payment_history_pct=97.0)
        result = analyze_credit_health(p)
        factors = {f["name"]: f for f in result["factors"]}
        assert factors["Payment History"]["rating"] == "Excellent"

    def test_payment_good(self):
        p = CreditProfile(bureau="test", payment_history_pct=92.0)
        result = analyze_credit_health(p)
        factors = {f["name"]: f for f in result["factors"]}
        assert factors["Payment History"]["rating"] == "Good"

    def test_payment_needs_work(self):
        p = CreditProfile(bureau="test", payment_history_pct=85.0)
        result = analyze_credit_health(p)
        factors = {f["name"]: f for f in result["factors"]}
        assert factors["Payment History"]["rating"] == "Needs Work"

    def test_derogatory_clean(self):
        p = CreditProfile(bureau="test", derogatory_marks=0, collections=0)
        result = analyze_credit_health(p)
        factors = {f["name"]: f for f in result["factors"]}
        assert factors["Derogatory Marks"]["rating"] == "Clean"

    def test_derogatory_warning(self):
        p = CreditProfile(bureau="test", derogatory_marks=1, collections=0)
        result = analyze_credit_health(p)
        factors = {f["name"]: f for f in result["factors"]}
        assert factors["Derogatory Marks"]["rating"] == "Warning"

    def test_derogatory_critical(self):
        p = CreditProfile(bureau="test", derogatory_marks=2, collections=2)
        result = analyze_credit_health(p)
        factors = {f["name"]: f for f in result["factors"]}
        assert factors["Derogatory Marks"]["rating"] == "Critical"

    def test_account_age_excellent(self):
        p = CreditProfile(bureau="test", avg_age_years=8.0)
        result = analyze_credit_health(p)
        factors = {f["name"]: f for f in result["factors"]}
        assert factors["Account Age"]["rating"] == "Excellent"

    def test_account_age_good(self):
        p = CreditProfile(bureau="test", avg_age_years=5.0)
        result = analyze_credit_health(p)
        factors = {f["name"]: f for f in result["factors"]}
        assert factors["Account Age"]["rating"] == "Good"

    def test_account_age_young(self):
        p = CreditProfile(bureau="test", avg_age_years=2.0)
        result = analyze_credit_health(p)
        factors = {f["name"]: f for f in result["factors"]}
        assert factors["Account Age"]["rating"] == "Young"

    def test_account_age_very_new(self):
        p = CreditProfile(bureau="test", avg_age_years=0.5)
        result = analyze_credit_health(p)
        factors = {f["name"]: f for f in result["factors"]}
        assert factors["Account Age"]["rating"] == "Very New"

    def test_inquiries_clean(self):
        p = CreditProfile(bureau="test", hard_inquiries_count=0)
        result = analyze_credit_health(p)
        factors = {f["name"]: f for f in result["factors"]}
        assert factors["Hard Inquiries"]["rating"] == "Clean"

    def test_inquiries_good(self):
        p = CreditProfile(bureau="test", hard_inquiries_count=2)
        result = analyze_credit_health(p)
        factors = {f["name"]: f for f in result["factors"]}
        assert factors["Hard Inquiries"]["rating"] == "Good"

    def test_inquiries_moderate(self):
        p = CreditProfile(bureau="test", hard_inquiries_count=5)
        result = analyze_credit_health(p)
        factors = {f["name"]: f for f in result["factors"]}
        assert factors["Hard Inquiries"]["rating"] == "Moderate"

    def test_inquiries_heavy(self):
        p = CreditProfile(bureau="test", hard_inquiries_count=8)
        result = analyze_credit_health(p)
        factors = {f["name"]: f for f in result["factors"]}
        assert factors["Hard Inquiries"]["rating"] == "Heavy"

    def test_no_data(self):
        p = CreditProfile(bureau="test")
        result = analyze_credit_health(p)
        assert result["overall_rating"] == "unknown"
        # Only derogatory factor (defaults to 0)
        assert len(result["factors"]) == 1
