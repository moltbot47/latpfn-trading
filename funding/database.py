"""SQLite database layer for the Business Funding Tracker."""

import logging
import os
import sqlite3
from datetime import datetime
from typing import Any, Optional

from .models import (
    Application, CreditProfile, FundingProduct, Inquiry,
    PartnerProgram, Referral, ReferralClient, StrategyRound,
)

logger = logging.getLogger(__name__)

DB_PATH = "data/funding.db"

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS credit_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parsed_at TEXT NOT NULL,
    bureau TEXT NOT NULL,
    score INTEGER,
    total_accounts INTEGER,
    open_accounts INTEGER,
    hard_inquiries_count INTEGER,
    utilization_pct REAL,
    payment_history_pct REAL,
    derogatory_marks INTEGER,
    collections INTEGER,
    avg_age_years REAL,
    oldest_account_years REAL,
    total_credit_limit REAL,
    total_balance REAL,
    closed_accounts INTEGER,
    new_accounts_6mo INTEGER,
    revolving_balance REAL,
    installment_balance REAL,
    pdf_filename TEXT,
    raw_extracted_text TEXT
);

CREATE TABLE IF NOT EXISTS strategy_rounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    planned_date TEXT,
    executed_date TEXT,
    status TEXT DEFAULT 'planning',
    target_total REAL,
    actual_total REAL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    product_type TEXT NOT NULL,
    lender TEXT NOT NULL,
    product_name TEXT,
    amount_requested REAL,
    amount_approved REAL,
    credit_limit REAL,
    apr REAL,
    intro_apr REAL,
    intro_period_months INTEGER,
    status TEXT NOT NULL DEFAULT 'planned',
    applied_date TEXT,
    decision_date TEXT,
    personal_guarantee INTEGER DEFAULT 0,
    bureau_pulled TEXT,
    round_id INTEGER,
    denial_reason TEXT,
    notes TEXT,
    FOREIGN KEY (round_id) REFERENCES strategy_rounds(id)
);

CREATE TABLE IF NOT EXISTS inquiries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    bureau TEXT NOT NULL,
    lender TEXT NOT NULL,
    falls_off_date TEXT,
    source TEXT DEFAULT 'manual',
    application_id INTEGER,
    FOREIGN KEY (application_id) REFERENCES applications(id)
);

CREATE TABLE IF NOT EXISTS funding_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lender TEXT NOT NULL,
    product_name TEXT NOT NULL,
    product_type TEXT NOT NULL,
    min_score INTEGER,
    typical_limit_low REAL,
    typical_limit_high REAL,
    bureau_pulled TEXT,
    inquiry_sensitive INTEGER DEFAULT 0,
    personal_guarantee INTEGER DEFAULT 1,
    intro_apr REAL,
    intro_period_months INTEGER,
    annual_fee REAL,
    recommended_order INTEGER,
    notes TEXT,
    category TEXT,
    reference_url TEXT,
    limit_source_url TEXT,
    docs_level TEXT,
    startup_grade TEXT,
    min_time_months INTEGER,
    max_line REAL
);

CREATE TABLE IF NOT EXISTS referral_clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS referrals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    referral_date TEXT NOT NULL,
    status TEXT DEFAULT 'submitted',
    funded_amount REAL,
    expected_commission REAL,
    actual_commission REAL,
    commission_paid_date TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (client_id) REFERENCES referral_clients(id),
    FOREIGN KEY (product_id) REFERENCES funding_products(id)
);

CREATE TABLE IF NOT EXISTS partner_programs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lender TEXT NOT NULL,
    program_name TEXT NOT NULL,
    program_type TEXT NOT NULL,
    status TEXT DEFAULT 'not_started',
    signup_url TEXT,
    portal_url TEXT,
    referral_link TEXT,
    contact_name TEXT,
    contact_email TEXT,
    commission_display TEXT,
    commission_type TEXT,
    has_api INTEGER DEFAULT 0,
    applied_date TEXT,
    approved_date TEXT,
    notes TEXT,
    priority INTEGER DEFAULT 3,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

_CREATE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_app_status ON applications(status);
CREATE INDEX IF NOT EXISTS idx_app_round ON applications(round_id);
CREATE INDEX IF NOT EXISTS idx_app_lender ON applications(lender);
CREATE INDEX IF NOT EXISTS idx_inq_bureau ON inquiries(bureau, date);
CREATE INDEX IF NOT EXISTS idx_inq_date ON inquiries(date);
CREATE INDEX IF NOT EXISTS idx_profile_bureau ON credit_profiles(bureau, parsed_at);
CREATE INDEX IF NOT EXISTS idx_products_type ON funding_products(product_type);
CREATE INDEX IF NOT EXISTS idx_referrals_status ON referrals(status);
CREATE INDEX IF NOT EXISTS idx_referrals_client ON referrals(client_id);
CREATE INDEX IF NOT EXISTS idx_referrals_product ON referrals(product_id);
CREATE INDEX IF NOT EXISTS idx_partner_status ON partner_programs(status);
"""


class FundingDB:
    """Database interface for the funding tracker."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        conn = self._get_conn()
        try:
            conn.executescript(_CREATE_TABLES)
            conn.executescript(_CREATE_INDEXES)
            # Migrate: add new columns if missing
            cols = [r[1] for r in conn.execute("PRAGMA table_info(funding_products)").fetchall()]
            for col, ctype in [
                ("reference_url", "TEXT"), ("limit_source_url", "TEXT"),
                ("docs_level", "TEXT"), ("startup_grade", "TEXT"),
                ("min_time_months", "INTEGER"), ("max_line", "REAL"),
                ("lender_type", "TEXT"),
                ("has_referral", "INTEGER DEFAULT 0"),
                ("referral_commission_type", "TEXT"),
                ("referral_commission_value", "REAL"),
                ("referral_commission_display", "TEXT"),
                ("referral_url", "TEXT"),
                ("referral_requires_license", "INTEGER DEFAULT 0"),
            ]:
                if col not in cols:
                    conn.execute(f"ALTER TABLE funding_products ADD COLUMN {col} {ctype}")

            # Migrate credit_profiles
            profile_cols = [r[1] for r in conn.execute("PRAGMA table_info(credit_profiles)").fetchall()]
            for col, ctype in [
                ("closed_accounts", "INTEGER"), ("new_accounts_6mo", "INTEGER"),
                ("revolving_balance", "REAL"), ("installment_balance", "REAL"),
            ]:
                if col not in profile_cols:
                    conn.execute(f"ALTER TABLE credit_profiles ADD COLUMN {col} {ctype}")

            conn.commit()
        finally:
            conn.close()

    # ── Credit Profiles ─────────────────────────────────────────────

    def save_profile(self, profile: CreditProfile) -> int:
        conn = self._get_conn()
        try:
            d = profile.to_dict()
            cur = conn.execute(
                """INSERT INTO credit_profiles
                   (parsed_at, bureau, score, total_accounts, open_accounts,
                    hard_inquiries_count, utilization_pct, payment_history_pct,
                    derogatory_marks, collections, avg_age_years, oldest_account_years,
                    total_credit_limit, total_balance, closed_accounts, new_accounts_6mo,
                    revolving_balance, installment_balance, pdf_filename, raw_extracted_text)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    d["parsed_at"], d["bureau"], d["score"], d["total_accounts"],
                    d["open_accounts"], d["hard_inquiries_count"], d["utilization_pct"],
                    d["payment_history_pct"], d["derogatory_marks"], d["collections"],
                    d["avg_age_years"], d["oldest_account_years"], d["total_credit_limit"],
                    d["total_balance"], d["closed_accounts"], d["new_accounts_6mo"],
                    d["revolving_balance"], d["installment_balance"],
                    d["pdf_filename"], d["raw_extracted_text"],
                ),
            )
            conn.commit()
            row_id: int = cur.lastrowid  # type: ignore[assignment]
            logger.info("Saved credit profile id=%d bureau=%s score=%s", row_id, d["bureau"], d["score"])
            return row_id
        finally:
            conn.close()

    def save_profile_with_inquiries(self, profile: CreditProfile, inquiries: list[Inquiry]) -> int:
        """Save profile and inquiries in a single transaction."""
        conn = self._get_conn()
        try:
            d = profile.to_dict()
            cur = conn.execute(
                """INSERT INTO credit_profiles
                   (parsed_at, bureau, score, total_accounts, open_accounts,
                    hard_inquiries_count, utilization_pct, payment_history_pct,
                    derogatory_marks, collections, avg_age_years, oldest_account_years,
                    total_credit_limit, total_balance, closed_accounts, new_accounts_6mo,
                    revolving_balance, installment_balance, pdf_filename, raw_extracted_text)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    d["parsed_at"], d["bureau"], d["score"], d["total_accounts"],
                    d["open_accounts"], d["hard_inquiries_count"], d["utilization_pct"],
                    d["payment_history_pct"], d["derogatory_marks"], d["collections"],
                    d["avg_age_years"], d["oldest_account_years"], d["total_credit_limit"],
                    d["total_balance"], d["closed_accounts"], d["new_accounts_6mo"],
                    d["revolving_balance"], d["installment_balance"],
                    d["pdf_filename"], d["raw_extracted_text"],
                ),
            )
            profile_id: int = cur.lastrowid  # type: ignore[assignment]
            for inq in inquiries:
                di = inq.to_dict()
                conn.execute(
                    """INSERT INTO inquiries (date, bureau, lender, falls_off_date, source, application_id)
                       VALUES (?,?,?,?,?,?)""",
                    (di["date"], di["bureau"], di["lender"], di["falls_off_date"],
                     di["source"], di["application_id"]),
                )
            conn.commit()
            logger.info("Saved profile id=%d with %d inquiries", profile_id, len(inquiries))
            return profile_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_latest_profile(self, bureau: Optional[str] = None) -> Optional[CreditProfile]:
        conn = self._get_conn()
        try:
            if bureau:
                row = conn.execute(
                    "SELECT * FROM credit_profiles WHERE bureau=? ORDER BY parsed_at DESC LIMIT 1",
                    (bureau,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM credit_profiles ORDER BY parsed_at DESC LIMIT 1"
                ).fetchone()
            return CreditProfile.from_row(row) if row else None
        finally:
            conn.close()

    def get_all_profiles(self) -> list[CreditProfile]:
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT * FROM credit_profiles ORDER BY parsed_at DESC").fetchall()
            return [CreditProfile.from_row(r) for r in rows]
        finally:
            conn.close()

    # ── Applications ─────────────────────────────────────────────────

    def save_application(self, app: Application) -> int:
        conn = self._get_conn()
        try:
            d = app.to_dict()
            cur = conn.execute(
                """INSERT INTO applications
                   (created_at, updated_at, product_type, lender, product_name,
                    amount_requested, amount_approved, credit_limit, apr, intro_apr,
                    intro_period_months, status, applied_date, decision_date,
                    personal_guarantee, bureau_pulled, round_id, denial_reason, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    d["created_at"], d["updated_at"], d["product_type"], d["lender"],
                    d["product_name"], d["amount_requested"], d["amount_approved"],
                    d["credit_limit"], d["apr"], d["intro_apr"], d["intro_period_months"],
                    d["status"], d["applied_date"], d["decision_date"],
                    d["personal_guarantee"], d["bureau_pulled"], d["round_id"],
                    d["denial_reason"], d["notes"],
                ),
            )
            conn.commit()
            row_id: int = cur.lastrowid  # type: ignore[assignment]
            logger.info("Saved application id=%d lender=%s status=%s", row_id, d["lender"], d["status"])
            return row_id
        finally:
            conn.close()

    _APPLICATION_COLUMNS = {
        "status", "amount_requested", "amount_approved", "credit_limit",
        "denial_reason", "notes", "applied_date", "decision_date",
        "bureau_pulled", "personal_guarantee", "round_id", "updated_at",
    }

    def update_application(self, app_id: int, **kwargs) -> bool:
        conn = self._get_conn()
        try:
            kwargs["updated_at"] = datetime.utcnow().isoformat()
            bad = set(kwargs) - self._APPLICATION_COLUMNS
            if bad:
                raise ValueError(f"Disallowed columns: {bad}")
            if "personal_guarantee" in kwargs:
                kwargs["personal_guarantee"] = 1 if kwargs["personal_guarantee"] else 0
            sets = ", ".join(f"{k}=?" for k in kwargs)
            vals = list(kwargs.values()) + [app_id]
            conn.execute(f"UPDATE applications SET {sets} WHERE id=?", vals)
            conn.commit()
            return True
        except Exception as e:
            logger.error("Failed to update application %d: %s", app_id, e)
            return False
        finally:
            conn.close()

    def get_application(self, app_id: int) -> Optional[Application]:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
            return Application.from_row(row) if row else None
        finally:
            conn.close()

    def get_applications(self, status: Optional[str] = None, round_id: Optional[int] = None) -> list[Application]:
        conn = self._get_conn()
        try:
            query = "SELECT * FROM applications"
            params: list[Any] = []
            wheres = []
            if status:
                wheres.append("status=?")
                params.append(status)
            if round_id is not None:
                wheres.append("round_id=?")
                params.append(round_id)
            if wheres:
                query += " WHERE " + " AND ".join(wheres)
            query += " ORDER BY created_at DESC"
            rows = conn.execute(query, params).fetchall()
            return [Application.from_row(r) for r in rows]
        finally:
            conn.close()

    def get_all_applications(self) -> list[Application]:
        return self.get_applications()

    # ── Inquiries ────────────────────────────────────────────────────

    def save_inquiry(self, inq: Inquiry) -> int:
        conn = self._get_conn()
        try:
            d = inq.to_dict()
            cur = conn.execute(
                """INSERT INTO inquiries (date, bureau, lender, falls_off_date, source, application_id)
                   VALUES (?,?,?,?,?,?)""",
                (d["date"], d["bureau"], d["lender"], d["falls_off_date"], d["source"], d["application_id"]),
            )
            conn.commit()
            row_id: int = cur.lastrowid  # type: ignore[assignment]
            return row_id
        finally:
            conn.close()

    def get_inquiries(self, bureau: Optional[str] = None, active_only: bool = False) -> list[Inquiry]:
        conn = self._get_conn()
        try:
            query = "SELECT * FROM inquiries"
            params = []
            wheres = []
            if bureau:
                wheres.append("bureau=?")
                params.append(bureau)
            if active_only:
                wheres.append("falls_off_date > ?")
                params.append(datetime.utcnow().strftime("%Y-%m-%d"))
            if wheres:
                query += " WHERE " + " AND ".join(wheres)
            query += " ORDER BY date DESC"
            rows = conn.execute(query, params).fetchall()
            return [Inquiry.from_row(r) for r in rows]
        finally:
            conn.close()

    def get_inquiry_counts_by_bureau(self, months: int = 12) -> dict[str, int]:
        conn = self._get_conn()
        try:
            from datetime import timedelta
            cutoff = (datetime.utcnow() - timedelta(days=months * 30)).strftime("%Y-%m-%d")
            rows = conn.execute(
                "SELECT bureau, COUNT(*) as cnt FROM inquiries WHERE date >= ? GROUP BY bureau",
                (cutoff,),
            ).fetchall()
            return {r["bureau"]: r["cnt"] for r in rows}
        finally:
            conn.close()

    # ── Strategy Rounds ──────────────────────────────────────────────

    def save_round(self, rnd: StrategyRound) -> int:
        conn = self._get_conn()
        try:
            d = rnd.to_dict()
            cur = conn.execute(
                """INSERT INTO strategy_rounds
                   (name, planned_date, executed_date, status, target_total, actual_total, notes)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    d["name"], d["planned_date"], d["executed_date"],
                    d["status"], d["target_total"], d["actual_total"], d["notes"],
                ),
            )
            conn.commit()
            row_id: int = cur.lastrowid  # type: ignore[assignment]
            return row_id
        finally:
            conn.close()

    _ROUND_COLUMNS = {
        "name", "planned_date", "executed_date", "status",
        "target_total", "actual_total", "notes",
    }

    def update_round(self, round_id: int, **kwargs) -> bool:
        conn = self._get_conn()
        try:
            bad = set(kwargs) - self._ROUND_COLUMNS
            if bad:
                raise ValueError(f"Disallowed columns: {bad}")
            sets = ", ".join(f"{k}=?" for k in kwargs)
            vals = list(kwargs.values()) + [round_id]
            conn.execute(f"UPDATE strategy_rounds SET {sets} WHERE id=?", vals)
            conn.commit()
            return True
        except Exception as e:
            logger.error("Failed to update round %d: %s", round_id, e)
            return False
        finally:
            conn.close()

    def get_rounds(self, status: Optional[str] = None) -> list[StrategyRound]:
        conn = self._get_conn()
        try:
            if status:
                rows = conn.execute(
                    "SELECT * FROM strategy_rounds WHERE status=? ORDER BY id DESC", (status,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM strategy_rounds ORDER BY id DESC").fetchall()
            return [StrategyRound.from_row(r) for r in rows]
        finally:
            conn.close()

    def get_last_completed_round(self) -> Optional[StrategyRound]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM strategy_rounds WHERE status='completed' ORDER BY executed_date DESC LIMIT 1"
            ).fetchone()
            return StrategyRound.from_row(row) if row else None
        finally:
            conn.close()

    # ── Funding Products (Catalog) ───────────────────────────────────

    def save_product(self, prod: FundingProduct) -> int:
        conn = self._get_conn()
        try:
            cur = conn.execute(
                """INSERT INTO funding_products
                   (lender, product_name, product_type, min_score, typical_limit_low,
                    typical_limit_high, bureau_pulled, inquiry_sensitive, personal_guarantee,
                    intro_apr, intro_period_months, annual_fee, recommended_order, notes, category,
                    reference_url, limit_source_url, docs_level, startup_grade, min_time_months,
                    max_line, lender_type, has_referral, referral_commission_type,
                    referral_commission_value, referral_commission_display, referral_url,
                    referral_requires_license)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    prod.lender, prod.product_name, prod.product_type, prod.min_score,
                    prod.typical_limit_low, prod.typical_limit_high, prod.bureau_pulled,
                    1 if prod.inquiry_sensitive else 0, 1 if prod.personal_guarantee else 0,
                    prod.intro_apr, prod.intro_period_months, prod.annual_fee,
                    prod.recommended_order, prod.notes, prod.category, prod.reference_url,
                    prod.limit_source_url, prod.docs_level, prod.startup_grade,
                    prod.min_time_months, prod.max_line, prod.lender_type,
                    1 if prod.has_referral else 0, prod.referral_commission_type,
                    prod.referral_commission_value, prod.referral_commission_display,
                    prod.referral_url, 1 if prod.referral_requires_license else 0,
                ),
            )
            conn.commit()
            row_id: int = cur.lastrowid  # type: ignore[assignment]
            return row_id
        finally:
            conn.close()

    def get_products(self, product_type: Optional[str] = None, category: Optional[str] = None) -> list[FundingProduct]:
        conn = self._get_conn()
        try:
            query = "SELECT * FROM funding_products"
            params = []
            wheres = []
            if product_type:
                wheres.append("product_type=?")
                params.append(product_type)
            if category:
                wheres.append("category=?")
                params.append(category)
            if wheres:
                query += " WHERE " + " AND ".join(wheres)
            query += " ORDER BY recommended_order ASC NULLS LAST, lender ASC"
            rows = conn.execute(query, params).fetchall()
            return [FundingProduct.from_row(r) for r in rows]
        finally:
            conn.close()

    def product_count(self) -> int:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT COUNT(*) as cnt FROM funding_products").fetchone()
            return row["cnt"]
        finally:
            conn.close()

    # ── Referral Clients ─────────────────────────────────────────────

    def save_referral_client(self, client: ReferralClient) -> int:
        conn = self._get_conn()
        try:
            d = client.to_dict()
            cur = conn.execute(
                """INSERT INTO referral_clients (name, email, phone, notes, created_at)
                   VALUES (?,?,?,?,?)""",
                (d["name"], d["email"], d["phone"], d["notes"], d["created_at"]),
            )
            conn.commit()
            row_id: int = cur.lastrowid  # type: ignore[assignment]
            logger.info("Saved referral client id=%d name=%s", row_id, d["name"])
            return row_id
        finally:
            conn.close()

    def get_referral_clients(self) -> list[ReferralClient]:
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT * FROM referral_clients ORDER BY name ASC").fetchall()
            return [ReferralClient.from_row(r) for r in rows]
        finally:
            conn.close()

    # ── Referrals ─────────────────────────────────────────────────────

    def save_referral(self, ref: Referral) -> int:
        conn = self._get_conn()
        try:
            d = ref.to_dict()
            cur = conn.execute(
                """INSERT INTO referrals
                   (client_id, product_id, referral_date, status, funded_amount,
                    expected_commission, actual_commission, commission_paid_date,
                    notes, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    d["client_id"], d["product_id"], d["referral_date"], d["status"],
                    d["funded_amount"], d["expected_commission"], d["actual_commission"],
                    d["commission_paid_date"], d["notes"], d["created_at"], d["updated_at"],
                ),
            )
            conn.commit()
            row_id: int = cur.lastrowid  # type: ignore[assignment]
            logger.info("Saved referral id=%d client=%d product=%d", row_id, d["client_id"], d["product_id"])
            return row_id
        finally:
            conn.close()

    def get_referral_by_id(self, referral_id: int) -> Optional[Referral]:
        """Fetch a single referral by ID with joined product data."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                """SELECT r.*, rc.name as client_name,
                          fp.product_name, fp.lender,
                          fp.referral_commission_display as commission_display,
                          fp.referral_commission_type, fp.referral_commission_value
                   FROM referrals r
                   JOIN referral_clients rc ON r.client_id = rc.id
                   JOIN funding_products fp ON r.product_id = fp.id
                   WHERE r.id=?""",
                (referral_id,),
            ).fetchone()
            if not row:
                return None
            ref = Referral.from_row(row)
            # Attach product commission info as extra attrs for convenience
            object.__setattr__(ref, "_commission_type", row["referral_commission_type"])
            object.__setattr__(ref, "_commission_value", row["referral_commission_value"])
            return ref
        finally:
            conn.close()

    _REFERRAL_COLUMNS = {
        "status", "funded_amount", "expected_commission", "actual_commission",
        "commission_paid_date", "notes", "updated_at",
    }

    def update_referral(self, referral_id: int, **kwargs) -> bool:
        conn = self._get_conn()
        try:
            kwargs["updated_at"] = datetime.utcnow().isoformat()
            bad = set(kwargs) - self._REFERRAL_COLUMNS
            if bad:
                raise ValueError(f"Disallowed columns: {bad}")
            sets = ", ".join(f"{k}=?" for k in kwargs)
            vals = list(kwargs.values()) + [referral_id]
            conn.execute(f"UPDATE referrals SET {sets} WHERE id=?", vals)
            conn.commit()
            return True
        except Exception as e:
            logger.error("Failed to update referral %d: %s", referral_id, e)
            return False
        finally:
            conn.close()

    def get_referrals(self, status: Optional[str] = None) -> list[Referral]:
        conn = self._get_conn()
        try:
            query = """
                SELECT r.*, rc.name as client_name,
                       fp.product_name, fp.lender, fp.referral_commission_display as commission_display
                FROM referrals r
                JOIN referral_clients rc ON r.client_id = rc.id
                JOIN funding_products fp ON r.product_id = fp.id
            """
            params = []
            if status:
                query += " WHERE r.status=?"
                params.append(status)
            query += " ORDER BY r.referral_date DESC"
            rows = conn.execute(query, params).fetchall()
            return [Referral.from_row(r) for r in rows]
        finally:
            conn.close()

    def get_referral_summary(self) -> dict:
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT * FROM referrals").fetchall()
            total = len(rows)
            active = sum(1 for r in rows if r["status"] in ("submitted", "in_review"))
            funded = sum(1 for r in rows if r["status"] == "funded")
            earned = sum((r["actual_commission"] or 0) for r in rows if r["commission_paid_date"])
            pending = sum((r["expected_commission"] or 0) for r in rows
                         if r["status"] == "funded" and not r["commission_paid_date"])
            pipeline = sum((r["expected_commission"] or 0) for r in rows
                          if r["status"] in ("submitted", "in_review", "approved"))
            return {
                "total_referrals": total,
                "active": active,
                "funded": funded,
                "commission_earned": round(earned, 2),
                "commission_pending": round(pending, 2),
                "pipeline_value": round(pipeline, 2),
            }
        finally:
            conn.close()

    def get_referral_products(self) -> list[FundingProduct]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM funding_products WHERE has_referral=1 ORDER BY lender ASC"
            ).fetchall()
            return [FundingProduct.from_row(r) for r in rows]
        finally:
            conn.close()

    # ── Partner Programs ────────────────────────────────────────────

    def save_partner_program(self, prog: PartnerProgram) -> int:
        conn = self._get_conn()
        try:
            d = prog.to_dict()
            cur = conn.execute(
                """INSERT INTO partner_programs
                   (lender, program_name, program_type, status, signup_url, portal_url,
                    referral_link, contact_name, contact_email, commission_display,
                    commission_type, has_api, applied_date, approved_date, notes,
                    priority, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    d["lender"], d["program_name"], d["program_type"], d["status"],
                    d["signup_url"], d["portal_url"], d["referral_link"],
                    d["contact_name"], d["contact_email"], d["commission_display"],
                    d["commission_type"], 1 if d["has_api"] else 0,
                    d["applied_date"], d["approved_date"], d["notes"],
                    d["priority"], d["created_at"], d["updated_at"],
                ),
            )
            conn.commit()
            row_id: int = cur.lastrowid  # type: ignore[assignment]
            return row_id
        finally:
            conn.close()

    _PARTNER_COLUMNS = {
        "status", "portal_url", "referral_link", "contact_name",
        "contact_email", "notes", "applied_date", "approved_date",
        "signup_url", "commission_display", "commission_type",
        "has_api", "priority", "program_type", "updated_at",
    }

    def update_partner_program(self, prog_id: int, **kwargs) -> bool:
        conn = self._get_conn()
        try:
            kwargs["updated_at"] = datetime.utcnow().isoformat()
            bad = set(kwargs) - self._PARTNER_COLUMNS
            if bad:
                raise ValueError(f"Disallowed columns: {bad}")
            if "has_api" in kwargs:
                kwargs["has_api"] = 1 if kwargs["has_api"] else 0
            sets = ", ".join(f"{k}=?" for k in kwargs)
            vals = list(kwargs.values()) + [prog_id]
            conn.execute(f"UPDATE partner_programs SET {sets} WHERE id=?", vals)
            conn.commit()
            return True
        except Exception as e:
            logger.error("Failed to update partner program %d: %s", prog_id, e)
            return False
        finally:
            conn.close()

    def get_partner_programs(self, status: Optional[str] = None) -> list[PartnerProgram]:
        conn = self._get_conn()
        try:
            if status:
                rows = conn.execute(
                    "SELECT * FROM partner_programs WHERE status=? ORDER BY priority ASC, lender ASC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM partner_programs ORDER BY priority ASC, lender ASC"
                ).fetchall()
            return [PartnerProgram.from_row(r) for r in rows]
        finally:
            conn.close()

    def get_partner_program_summary(self) -> dict:
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT * FROM partner_programs").fetchall()
            total = len(rows)
            active = sum(1 for r in rows if r["status"] == "active")
            in_progress = sum(1 for r in rows if r["status"] in ("applied", "onboarding"))
            not_started = sum(1 for r in rows if r["status"] == "not_started")
            paused = sum(1 for r in rows if r["status"] == "paused")
            denied = sum(1 for r in rows if r["status"] == "denied")
            api_ready = sum(1 for r in rows if r["has_api"])
            return {
                "total": total,
                "active": active,
                "in_progress": in_progress,
                "not_started": not_started,
                "paused": paused,
                "denied": denied,
                "api_ready": api_ready,
            }
        finally:
            conn.close()

    def partner_program_count(self) -> int:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT COUNT(*) as cnt FROM partner_programs").fetchone()
            return row["cnt"]
        finally:
            conn.close()

    # ── Summary / Stats ──────────────────────────────────────────────

    def get_funding_summary(self) -> dict:
        conn = self._get_conn()
        try:
            apps = conn.execute("SELECT * FROM applications").fetchall()
            total_approved = sum(
                (r["amount_approved"] or r["credit_limit"] or 0)
                for r in apps if r["status"] == "approved"
            )
            total_pending = sum(1 for r in apps if r["status"] in ("applied", "pending"))
            total_denied = sum(1 for r in apps if r["status"] == "denied")
            total_apps = len(apps)
            approved_count = sum(1 for r in apps if r["status"] == "approved")

            profile = self.get_latest_profile()
            inq_counts = self.get_inquiry_counts_by_bureau(12)

            return {
                "total_applications": total_apps,
                "approved": approved_count,
                "pending": total_pending,
                "denied": total_denied,
                "total_funding_approved": total_approved,
                "approval_rate": (approved_count / total_apps * 100) if total_apps > 0 else 0,
                "latest_score": profile.score if profile else None,
                "latest_bureau": profile.bureau if profile else None,
                "inquiries_12mo": inq_counts,
            }
        finally:
            conn.close()
