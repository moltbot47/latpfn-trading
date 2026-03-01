"""Data models for the Business Funding Tracker."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class CreditProfile:
    """A parsed credit report snapshot."""
    bureau: str  # experian / transunion / equifax
    score: Optional[int] = None
    total_accounts: Optional[int] = None
    open_accounts: Optional[int] = None
    hard_inquiries_count: Optional[int] = None
    utilization_pct: Optional[float] = None
    payment_history_pct: Optional[float] = None
    derogatory_marks: Optional[int] = None
    collections: Optional[int] = None
    avg_age_years: Optional[float] = None
    oldest_account_years: Optional[float] = None
    total_credit_limit: Optional[float] = None
    total_balance: Optional[float] = None
    closed_accounts: Optional[int] = None
    new_accounts_6mo: Optional[int] = None
    revolving_balance: Optional[float] = None
    installment_balance: Optional[float] = None
    pdf_filename: Optional[str] = None
    raw_extracted_text: Optional[str] = None
    parsed_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    id: Optional[int] = None

    # All extractable field names for confidence scoring
    EXTRACTABLE_FIELDS = [
        "score", "total_accounts", "open_accounts", "closed_accounts",
        "hard_inquiries_count", "utilization_pct", "payment_history_pct",
        "derogatory_marks", "collections", "avg_age_years", "oldest_account_years",
        "total_credit_limit", "total_balance", "new_accounts_6mo",
        "revolving_balance", "installment_balance",
    ]

    def to_dict(self) -> dict:
        return {
            "parsed_at": self.parsed_at,
            "bureau": self.bureau,
            "score": self.score,
            "total_accounts": self.total_accounts,
            "open_accounts": self.open_accounts,
            "closed_accounts": self.closed_accounts,
            "hard_inquiries_count": self.hard_inquiries_count,
            "utilization_pct": self.utilization_pct,
            "payment_history_pct": self.payment_history_pct,
            "derogatory_marks": self.derogatory_marks,
            "collections": self.collections,
            "avg_age_years": self.avg_age_years,
            "oldest_account_years": self.oldest_account_years,
            "total_credit_limit": self.total_credit_limit,
            "total_balance": self.total_balance,
            "new_accounts_6mo": self.new_accounts_6mo,
            "revolving_balance": self.revolving_balance,
            "installment_balance": self.installment_balance,
            "pdf_filename": self.pdf_filename,
            "raw_extracted_text": self.raw_extracted_text,
        }

    def extraction_confidence(self) -> dict:
        """Return extraction confidence report."""
        found = []
        missing = []
        for f in self.EXTRACTABLE_FIELDS:
            if getattr(self, f) is not None:
                found.append(f)
            else:
                missing.append(f)
        total = len(self.EXTRACTABLE_FIELDS)
        return {
            "fields_found": len(found),
            "fields_total": total,
            "pct": round(len(found) / total * 100) if total else 0,
            "found": found,
            "missing": missing,
        }

    @classmethod
    def from_row(cls, row) -> "CreditProfile":
        keys = row.keys()
        return cls(
            id=row["id"],
            parsed_at=row["parsed_at"],
            bureau=row["bureau"],
            score=row["score"],
            total_accounts=row["total_accounts"],
            open_accounts=row["open_accounts"],
            hard_inquiries_count=row["hard_inquiries_count"],
            utilization_pct=row["utilization_pct"],
            payment_history_pct=row["payment_history_pct"],
            derogatory_marks=row["derogatory_marks"],
            collections=row["collections"],
            avg_age_years=row["avg_age_years"],
            oldest_account_years=row["oldest_account_years"],
            total_credit_limit=row["total_credit_limit"],
            total_balance=row["total_balance"],
            pdf_filename=row["pdf_filename"],
            raw_extracted_text=row["raw_extracted_text"],
            closed_accounts=row["closed_accounts"] if "closed_accounts" in keys else None,
            new_accounts_6mo=row["new_accounts_6mo"] if "new_accounts_6mo" in keys else None,
            revolving_balance=row["revolving_balance"] if "revolving_balance" in keys else None,
            installment_balance=row["installment_balance"] if "installment_balance" in keys else None,
        )


@dataclass
class Application:
    """A funding application."""
    product_type: str  # credit_card / loc / term_loan / sba / balance_transfer
    lender: str
    product_name: Optional[str] = None
    amount_requested: Optional[float] = None
    amount_approved: Optional[float] = None
    credit_limit: Optional[float] = None
    apr: Optional[float] = None
    intro_apr: Optional[float] = None
    intro_period_months: Optional[int] = None
    status: str = "planned"  # planned / applied / pending / approved / denied / withdrawn
    applied_date: Optional[str] = None
    decision_date: Optional[str] = None
    personal_guarantee: bool = False
    bureau_pulled: Optional[str] = None
    round_id: Optional[int] = None
    denial_reason: Optional[str] = None
    notes: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    id: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "product_type": self.product_type,
            "lender": self.lender,
            "product_name": self.product_name,
            "amount_requested": self.amount_requested,
            "amount_approved": self.amount_approved,
            "credit_limit": self.credit_limit,
            "apr": self.apr,
            "intro_apr": self.intro_apr,
            "intro_period_months": self.intro_period_months,
            "status": self.status,
            "applied_date": self.applied_date,
            "decision_date": self.decision_date,
            "personal_guarantee": 1 if self.personal_guarantee else 0,
            "bureau_pulled": self.bureau_pulled,
            "round_id": self.round_id,
            "denial_reason": self.denial_reason,
            "notes": self.notes,
        }

    @classmethod
    def from_row(cls, row) -> "Application":
        return cls(
            id=row["id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            product_type=row["product_type"],
            lender=row["lender"],
            product_name=row["product_name"],
            amount_requested=row["amount_requested"],
            amount_approved=row["amount_approved"],
            credit_limit=row["credit_limit"],
            apr=row["apr"],
            intro_apr=row["intro_apr"],
            intro_period_months=row["intro_period_months"],
            status=row["status"],
            applied_date=row["applied_date"],
            decision_date=row["decision_date"],
            personal_guarantee=bool(row["personal_guarantee"]),
            bureau_pulled=row["bureau_pulled"],
            round_id=row["round_id"],
            denial_reason=row["denial_reason"],
            notes=row["notes"],
        )


@dataclass
class Inquiry:
    """A hard credit inquiry."""
    date: str  # ISO date
    bureau: str  # experian / transunion / equifax
    lender: str
    falls_off_date: Optional[str] = None
    source: str = "manual"  # manual / parsed
    application_id: Optional[int] = None
    id: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "bureau": self.bureau,
            "lender": self.lender,
            "falls_off_date": self.falls_off_date,
            "source": self.source,
            "application_id": self.application_id,
        }

    @classmethod
    def from_row(cls, row) -> "Inquiry":
        return cls(
            id=row["id"],
            date=row["date"],
            bureau=row["bureau"],
            lender=row["lender"],
            falls_off_date=row["falls_off_date"],
            source=row["source"],
            application_id=row["application_id"],
        )


@dataclass
class StrategyRound:
    """A planned funding round."""
    name: Optional[str] = None
    planned_date: Optional[str] = None
    executed_date: Optional[str] = None
    status: str = "planning"  # planning / ready / executing / completed
    target_total: Optional[float] = None
    actual_total: Optional[float] = None
    notes: Optional[str] = None
    id: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "planned_date": self.planned_date,
            "executed_date": self.executed_date,
            "status": self.status,
            "target_total": self.target_total,
            "actual_total": self.actual_total,
            "notes": self.notes,
        }

    @classmethod
    def from_row(cls, row) -> "StrategyRound":
        return cls(
            id=row["id"],
            name=row["name"],
            planned_date=row["planned_date"],
            executed_date=row["executed_date"],
            status=row["status"],
            target_total=row["target_total"],
            actual_total=row["actual_total"],
            notes=row["notes"],
        )


@dataclass
class FundingProduct:
    """A funding product in the catalog."""
    lender: str
    product_name: str
    product_type: str  # credit_card / loc / term_loan / sba / balance_transfer
    min_score: Optional[int] = None
    typical_limit_low: Optional[float] = None
    typical_limit_high: Optional[float] = None
    bureau_pulled: Optional[str] = None
    inquiry_sensitive: bool = False
    personal_guarantee: bool = True
    intro_apr: Optional[float] = None
    intro_period_months: Optional[int] = None
    annual_fee: Optional[float] = None
    recommended_order: Optional[int] = None
    notes: Optional[str] = None
    category: Optional[str] = None  # starter / mid_tier / premium / ultra_premium
    reference_url: Optional[str] = None
    limit_source_url: Optional[str] = None  # source for limit range data
    docs_level: Optional[str] = None  # very_low / low / moderate / high
    startup_grade: Optional[str] = None  # A+ / A / B+ / B / B- / C+ / C / D / F
    min_time_months: Optional[int] = None  # minimum months in business (0 = day-1)
    max_line: Optional[float] = None  # maximum credit line available
    lender_type: Optional[str] = None  # bank / credit_union / fintech / marketplace / vendor / government
    has_referral: bool = False
    referral_commission_type: Optional[str] = None  # percentage / flat_fee / points / recurring
    referral_commission_value: Optional[float] = None  # e.g. 2.0 for 2%, 250.0 for $250
    referral_commission_display: Optional[str] = None  # human-readable, e.g. "2% of funded amount"
    referral_url: Optional[str] = None  # partner signup / referral portal link
    referral_requires_license: bool = False  # True if ISO/broker license required
    id: Optional[int] = None

    @classmethod
    def from_row(cls, row) -> "FundingProduct":
        keys = row.keys()
        return cls(
            id=row["id"],
            lender=row["lender"],
            product_name=row["product_name"],
            product_type=row["product_type"],
            min_score=row["min_score"],
            typical_limit_low=row["typical_limit_low"],
            typical_limit_high=row["typical_limit_high"],
            bureau_pulled=row["bureau_pulled"],
            inquiry_sensitive=bool(row["inquiry_sensitive"]),
            personal_guarantee=bool(row["personal_guarantee"]),
            intro_apr=row["intro_apr"],
            intro_period_months=row["intro_period_months"],
            annual_fee=row["annual_fee"],
            recommended_order=row["recommended_order"],
            notes=row["notes"],
            category=row["category"],
            reference_url=row["reference_url"] if "reference_url" in keys else None,
            limit_source_url=row["limit_source_url"] if "limit_source_url" in keys else None,
            docs_level=row["docs_level"] if "docs_level" in keys else None,
            startup_grade=row["startup_grade"] if "startup_grade" in keys else None,
            min_time_months=row["min_time_months"] if "min_time_months" in keys else None,
            max_line=row["max_line"] if "max_line" in keys else None,
            lender_type=row["lender_type"] if "lender_type" in keys else None,
            has_referral=bool(row["has_referral"]) if "has_referral" in keys and row["has_referral"] is not None else False,
            referral_commission_type=row["referral_commission_type"] if "referral_commission_type" in keys else None,
            referral_commission_value=row["referral_commission_value"] if "referral_commission_value" in keys else None,
            referral_commission_display=row["referral_commission_display"] if "referral_commission_display" in keys else None,
            referral_url=row["referral_url"] if "referral_url" in keys else None,
            referral_requires_license=bool(row["referral_requires_license"]) if "referral_requires_license" in keys and row["referral_requires_license"] is not None else False,
        )


@dataclass
class Recommendation:
    """A strategy recommendation."""
    priority: int  # 1 = highest
    category: str  # score_optimization / inquiry_mgmt / cooling / product / action
    title: str
    detail: str
    impact: Optional[str] = None  # high / medium / low


@dataclass
class ReferralClient:
    """A person referred to a funding product."""
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    id: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "notes": self.notes,
            "created_at": self.created_at,
        }

    @classmethod
    def from_row(cls, row) -> "ReferralClient":
        return cls(
            id=row["id"],
            name=row["name"],
            email=row["email"],
            phone=row["phone"],
            notes=row["notes"],
            created_at=row["created_at"],
        )


@dataclass
class Referral:
    """A referral of a client to a funding product."""
    client_id: int
    product_id: int
    referral_date: str  # ISO date
    status: str = "submitted"  # submitted / in_review / approved / funded / denied / expired
    funded_amount: Optional[float] = None
    expected_commission: Optional[float] = None
    actual_commission: Optional[float] = None
    commission_paid_date: Optional[str] = None
    notes: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    id: Optional[int] = None
    # Populated via JOIN (not stored):
    client_name: Optional[str] = None
    product_name: Optional[str] = None
    lender: Optional[str] = None
    commission_display: Optional[str] = None

    def to_dict(self) -> dict:
        d = {
            "client_id": self.client_id,
            "product_id": self.product_id,
            "referral_date": self.referral_date,
            "status": self.status,
            "funded_amount": self.funded_amount,
            "expected_commission": self.expected_commission,
            "actual_commission": self.actual_commission,
            "commission_paid_date": self.commission_paid_date,
            "notes": self.notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        # Include JOIN fields if populated
        if self.client_name is not None:
            d["client_name"] = self.client_name
        if self.product_name is not None:
            d["product_name"] = self.product_name
        if self.lender is not None:
            d["lender"] = self.lender
        if self.commission_display is not None:
            d["commission_display"] = self.commission_display
        return d

    @classmethod
    def from_row(cls, row) -> "Referral":
        keys = row.keys()
        return cls(
            id=row["id"],
            client_id=row["client_id"],
            product_id=row["product_id"],
            referral_date=row["referral_date"],
            status=row["status"],
            funded_amount=row["funded_amount"],
            expected_commission=row["expected_commission"],
            actual_commission=row["actual_commission"],
            commission_paid_date=row["commission_paid_date"],
            notes=row["notes"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            client_name=row["client_name"] if "client_name" in keys else None,
            product_name=row["product_name"] if "product_name" in keys else None,
            lender=row["lender"] if "lender" in keys else None,
            commission_display=row["commission_display"] if "commission_display" in keys else None,
        )


@dataclass
class PartnerProgram:
    """Tracks signup/onboarding status with a referral partner program."""
    lender: str
    program_name: str  # e.g. "ISO Program", "Refer-a-Friend"
    program_type: str  # iso / affiliate / referral / partner / broker
    status: str = "not_started"  # not_started / applied / onboarding / active / paused / denied
    signup_url: Optional[str] = None
    portal_url: Optional[str] = None
    referral_link: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    commission_display: Optional[str] = None
    commission_type: Optional[str] = None  # percentage / flat_fee / points / recurring
    has_api: bool = False
    applied_date: Optional[str] = None
    approved_date: Optional[str] = None
    notes: Optional[str] = None
    priority: int = 3  # 1=high, 2=medium, 3=low
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    id: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "lender": self.lender,
            "program_name": self.program_name,
            "program_type": self.program_type,
            "status": self.status,
            "signup_url": self.signup_url,
            "portal_url": self.portal_url,
            "referral_link": self.referral_link,
            "contact_name": self.contact_name,
            "contact_email": self.contact_email,
            "commission_display": self.commission_display,
            "commission_type": self.commission_type,
            "has_api": self.has_api,
            "applied_date": self.applied_date,
            "approved_date": self.approved_date,
            "notes": self.notes,
            "priority": self.priority,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row) -> "PartnerProgram":
        return cls(
            id=row["id"],
            lender=row["lender"],
            program_name=row["program_name"],
            program_type=row["program_type"],
            status=row["status"],
            signup_url=row["signup_url"],
            portal_url=row["portal_url"],
            referral_link=row["referral_link"],
            contact_name=row["contact_name"],
            contact_email=row["contact_email"],
            commission_display=row["commission_display"],
            commission_type=row["commission_type"],
            has_api=bool(row["has_api"]),
            applied_date=row["applied_date"],
            approved_date=row["approved_date"],
            notes=row["notes"],
            priority=row["priority"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
