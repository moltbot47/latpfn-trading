"""Tests for funding.models dataclass serialization (to_dict, from_row, etc.)."""

import sqlite3

from funding.models import (
    Application, CreditProfile, FundingProduct, Inquiry,
    PartnerProgram, Referral, StrategyRound,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _make_row(table_sql: str, insert_sql: str, values: tuple) -> sqlite3.Row:
    """Create an in-memory SQLite row matching a real table schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(table_sql)
    conn.execute(insert_sql, values)
    row = conn.execute(f"SELECT * FROM {_extract_table_name(table_sql)}").fetchone()
    conn.close()
    return row


def _extract_table_name(sql: str) -> str:
    """Pull table name from 'CREATE TABLE IF NOT EXISTS <name>'."""
    for token in sql.split():
        if token not in ("CREATE", "TABLE", "IF", "NOT", "EXISTS", "("):
            return token.rstrip("(")
    raise ValueError("Could not extract table name")


# ── CreditProfile ────────────────────────────────────────────────────


class TestCreditProfile:
    def test_to_dict(self, sample_profile):
        d = sample_profile.to_dict()
        assert d["bureau"] == "experian"
        assert d["score"] == 720
        assert d["utilization_pct"] == 22.0
        assert d["derogatory_marks"] == 0
        assert d["total_credit_limit"] == 50000.0
        assert d["closed_accounts"] == 4
        assert d["new_accounts_6mo"] == 1
        assert "id" not in d  # id excluded from to_dict

    def test_from_row(self, sample_profile):
        # Save → fetch → from_row round-trip via real DB
        row = _make_row(
            """CREATE TABLE IF NOT EXISTS credit_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parsed_at TEXT, bureau TEXT, score INTEGER,
                total_accounts INTEGER, open_accounts INTEGER,
                hard_inquiries_count INTEGER, utilization_pct REAL,
                payment_history_pct REAL, derogatory_marks INTEGER,
                collections INTEGER, avg_age_years REAL,
                oldest_account_years REAL, total_credit_limit REAL,
                total_balance REAL, pdf_filename TEXT, raw_extracted_text TEXT,
                closed_accounts INTEGER, new_accounts_6mo INTEGER,
                revolving_balance REAL, installment_balance REAL
            )""",
            """INSERT INTO credit_profiles
               (parsed_at, bureau, score, total_accounts, open_accounts,
                hard_inquiries_count, utilization_pct, payment_history_pct,
                derogatory_marks, collections, avg_age_years, oldest_account_years,
                total_credit_limit, total_balance, pdf_filename, raw_extracted_text,
                closed_accounts, new_accounts_6mo, revolving_balance, installment_balance)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("2026-02-28T00:00:00", "experian", 720, 12, 8, 3, 22.0, 98.0,
             0, 0, 4.5, 9.0, 50000.0, 11000.0, None, None, 4, 1, 8000.0, 3000.0),
        )
        profile = CreditProfile.from_row(row)
        assert profile.id == 1
        assert profile.bureau == "experian"
        assert profile.score == 720
        assert profile.closed_accounts == 4

    def test_extraction_confidence_all_fields(self, sample_profile):
        """All extractable fields set → 100% confidence."""
        conf = sample_profile.extraction_confidence()
        assert conf["fields_found"] == conf["fields_total"]
        assert conf["pct"] == 100
        assert conf["missing"] == []

    def test_extraction_confidence_partial(self):
        """Only bureau + score set → low confidence."""
        p = CreditProfile(bureau="experian", score=700)
        conf = p.extraction_confidence()
        assert conf["fields_found"] == 1  # only score
        assert conf["pct"] < 100
        assert "utilization_pct" in conf["missing"]


# ── Application ──────────────────────────────────────────────────────


class TestApplication:
    def test_to_dict(self, sample_application):
        d = sample_application.to_dict()
        assert d["lender"] == "Chase"
        assert d["product_type"] == "credit_card"
        assert d["status"] == "planned"
        assert d["personal_guarantee"] == 1  # bool → int in to_dict
        assert "id" not in d

    def test_from_row(self):
        row = _make_row(
            """CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT, updated_at TEXT, product_type TEXT,
                lender TEXT, product_name TEXT, amount_requested REAL,
                amount_approved REAL, credit_limit REAL, apr REAL,
                intro_apr REAL, intro_period_months INTEGER,
                status TEXT, applied_date TEXT, decision_date TEXT,
                personal_guarantee INTEGER, bureau_pulled TEXT,
                round_id INTEGER, denial_reason TEXT, notes TEXT
            )""",
            """INSERT INTO applications
               (created_at, updated_at, product_type, lender, product_name,
                amount_requested, amount_approved, credit_limit, apr, intro_apr,
                intro_period_months, status, applied_date, decision_date,
                personal_guarantee, bureau_pulled, round_id, denial_reason, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("2026-01-01", "2026-01-01", "credit_card", "Chase",
             "Ink Preferred", 10000, None, None, None, None, None,
             "planned", None, None, 1, "experian", None, None, None),
        )
        app = Application.from_row(row)
        assert app.id == 1
        assert app.lender == "Chase"
        assert app.personal_guarantee is True


# ── Inquiry ──────────────────────────────────────────────────────────


class TestInquiry:
    def test_to_dict(self):
        inq = Inquiry(date="2026-01-15", bureau="experian", lender="Chase",
                       falls_off_date="2028-01-15")
        d = inq.to_dict()
        assert d["date"] == "2026-01-15"
        assert d["bureau"] == "experian"
        assert d["source"] == "manual"
        assert "id" not in d

    def test_from_row(self):
        row = _make_row(
            """CREATE TABLE IF NOT EXISTS inquiries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT, bureau TEXT, lender TEXT,
                falls_off_date TEXT, source TEXT, application_id INTEGER
            )""",
            "INSERT INTO inquiries (date, bureau, lender, falls_off_date, source, application_id) VALUES (?,?,?,?,?,?)",
            ("2026-01-15", "experian", "Chase", "2028-01-15", "manual", None),
        )
        inq = Inquiry.from_row(row)
        assert inq.id == 1
        assert inq.bureau == "experian"


# ── StrategyRound ────────────────────────────────────────────────────


class TestStrategyRound:
    def test_to_dict(self):
        rnd = StrategyRound(name="Round 1", status="planning", target_total=50000.0)
        d = rnd.to_dict()
        assert d["name"] == "Round 1"
        assert d["status"] == "planning"
        assert d["target_total"] == 50000.0
        assert "id" not in d


# ── Referral & ReferralClient ────────────────────────────────────────


class TestReferral:
    def test_to_dict_without_joins(self):
        ref = Referral(client_id=1, product_id=2, referral_date="2026-02-01",
                        status="submitted", expected_commission=250.0)
        d = ref.to_dict()
        assert d["client_id"] == 1
        assert d["status"] == "submitted"
        # JOIN fields not included when None
        assert "client_name" not in d
        assert "lender" not in d

    def test_to_dict_with_joins(self):
        ref = Referral(client_id=1, product_id=2, referral_date="2026-02-01",
                        client_name="John Doe", lender="Chase",
                        product_name="Ink Preferred", commission_display="$250 per referral")
        d = ref.to_dict()
        assert d["client_name"] == "John Doe"
        assert d["lender"] == "Chase"
        assert d["commission_display"] == "$250 per referral"

    def test_from_row(self):
        row = _make_row(
            """CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER, product_id INTEGER,
                referral_date TEXT, status TEXT, funded_amount REAL,
                expected_commission REAL, actual_commission REAL,
                commission_paid_date TEXT, notes TEXT,
                created_at TEXT, updated_at TEXT
            )""",
            """INSERT INTO referrals
               (client_id, product_id, referral_date, status, funded_amount,
                expected_commission, actual_commission, commission_paid_date,
                notes, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (1, 2, "2026-02-01", "submitted", None, 250.0, None, None, None,
             "2026-02-01", "2026-02-01"),
        )
        ref = Referral.from_row(row)
        assert ref.id == 1
        assert ref.client_id == 1
        assert ref.expected_commission == 250.0


# ── PartnerProgram ───────────────────────────────────────────────────


class TestPartnerProgram:
    def test_to_dict(self):
        prog = PartnerProgram(
            lender="Chase", program_name="Refer-a-Friend",
            program_type="referral", status="not_started", priority=1,
            has_api=False, commission_display="20K UR points per referral",
        )
        d = prog.to_dict()
        assert d["lender"] == "Chase"
        assert d["program_type"] == "referral"
        assert d["has_api"] is False
        assert d["priority"] == 1

    def test_from_row(self):
        row = _make_row(
            """CREATE TABLE IF NOT EXISTS partner_programs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lender TEXT, program_name TEXT, program_type TEXT,
                status TEXT, signup_url TEXT, portal_url TEXT,
                referral_link TEXT, contact_name TEXT, contact_email TEXT,
                commission_display TEXT, commission_type TEXT,
                has_api INTEGER, applied_date TEXT, approved_date TEXT,
                notes TEXT, priority INTEGER, created_at TEXT, updated_at TEXT
            )""",
            """INSERT INTO partner_programs
               (lender, program_name, program_type, status, signup_url,
                portal_url, referral_link, contact_name, contact_email,
                commission_display, commission_type, has_api, applied_date,
                approved_date, notes, priority, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("Chase", "Refer-a-Friend", "referral", "not_started",
             "https://chase.com/refer", None, None, None, None,
             "20K UR points", "points", 0, None, None, None, 1,
             "2026-02-28", "2026-02-28"),
        )
        prog = PartnerProgram.from_row(row)
        assert prog.id == 1
        assert prog.lender == "Chase"
        assert prog.has_api is False
        assert prog.priority == 1


# ── FundingProduct ───────────────────────────────────────────────────


class TestFundingProduct:
    def test_from_row(self):
        row = _make_row(
            """CREATE TABLE IF NOT EXISTS funding_products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lender TEXT, product_name TEXT, product_type TEXT,
                min_score INTEGER, typical_limit_low REAL, typical_limit_high REAL,
                bureau_pulled TEXT, inquiry_sensitive INTEGER,
                personal_guarantee INTEGER, intro_apr REAL,
                intro_period_months INTEGER, annual_fee REAL,
                recommended_order INTEGER, notes TEXT, category TEXT,
                reference_url TEXT, limit_source_url TEXT, docs_level TEXT,
                startup_grade TEXT, min_time_months INTEGER, max_line REAL,
                lender_type TEXT, has_referral INTEGER,
                referral_commission_type TEXT, referral_commission_value REAL,
                referral_commission_display TEXT, referral_url TEXT,
                referral_requires_license INTEGER
            )""",
            """INSERT INTO funding_products
               (lender, product_name, product_type, min_score,
                typical_limit_low, typical_limit_high, bureau_pulled,
                inquiry_sensitive, personal_guarantee, intro_apr,
                intro_period_months, annual_fee, recommended_order, notes,
                category, reference_url, limit_source_url, docs_level,
                startup_grade, min_time_months, max_line, lender_type,
                has_referral, referral_commission_type, referral_commission_value,
                referral_commission_display, referral_url, referral_requires_license)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("Chase", "Ink Preferred", "credit_card", 700,
             5000, 50000, "Experian", 1, 1, None, None, 95, 1,
             "5/24 rule", "premium", None, None, None, None, 0, None, "bank",
             1, "points", 20000, "20K UR per referral", None, 0),
        )
        prod = FundingProduct.from_row(row)
        assert prod.id == 1
        assert prod.lender == "Chase"
        assert prod.inquiry_sensitive is True
        assert prod.has_referral is True
        assert prod.referral_commission_value == 20000


# ── Optional Fields Default ──────────────────────────────────────────


class TestOptionalDefaults:
    def test_optional_fields_default_none(self):
        """Minimal construction — all Optional fields should be None in dict."""
        p = CreditProfile(bureau="experian")
        d = p.to_dict()
        assert d["score"] is None
        assert d["utilization_pct"] is None
        assert d["total_credit_limit"] is None
        assert d["pdf_filename"] is None

        a = Application(product_type="loc", lender="OnDeck")
        d2 = a.to_dict()
        assert d2["amount_requested"] is None
        assert d2["amount_approved"] is None
        assert d2["notes"] is None
