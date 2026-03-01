"""Credit report PDF parser.

Extracts key data points from Experian, TransUnion, and Equifax credit report
PDFs using pdfplumber for text extraction and regex for field parsing.

Also supports Credit Karma, Credit Sesame, and AnnualCreditReport.com formats.
"""

import logging
import re
from pathlib import Path
from typing import Optional

from .models import CreditProfile, Inquiry

logger = logging.getLogger(__name__)

# Field display names for confidence reporting
FIELD_LABELS = {
    "score": "Credit Score",
    "total_accounts": "Total Accounts",
    "open_accounts": "Open Accounts",
    "closed_accounts": "Closed Accounts",
    "hard_inquiries_count": "Hard Inquiries",
    "utilization_pct": "Utilization %",
    "payment_history_pct": "Payment History %",
    "derogatory_marks": "Derogatory Marks",
    "collections": "Collections",
    "avg_age_years": "Average Account Age",
    "oldest_account_years": "Oldest Account Age",
    "total_credit_limit": "Total Credit Limit",
    "total_balance": "Total Balance",
    "new_accounts_6mo": "New Accounts (6mo)",
    "revolving_balance": "Revolving Balance",
    "installment_balance": "Installment Balance",
}


def parse_credit_report(pdf_path: str) -> tuple[CreditProfile, list[Inquiry]]:
    """Parse a credit report PDF and return a CreditProfile + list of Inquiries.

    Supports Experian, TransUnion, Equifax, Credit Karma, and Credit Sesame formats.
    """
    try:
        import pdfplumber
    except ImportError:
        raise ImportError("pdfplumber is required: pip install pdfplumber")

    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    full_text = ""
    try:
        pdf = pdfplumber.open(pdf_path)
    except Exception:
        raise ValueError(
            "Could not open PDF — the file may be corrupted, password-protected, "
            "or not a valid PDF. Try downloading a fresh copy from your bureau."
        )

    with pdf:
        if not pdf.pages:
            raise ValueError("PDF has no pages — may be corrupted or password-protected")
        for page in pdf.pages:
            text = page.extract_text() or ""
            full_text += text + "\n"

    if len(full_text.strip()) < 50:
        raise ValueError(
            "Could not extract text from PDF. This may be a scanned image — "
            "try uploading a text-based PDF from your bureau's website."
        )

    bureau = _detect_bureau(full_text)
    logger.info("Detected bureau: %s from %s", bureau, path.name)

    profile = CreditProfile(
        bureau=bureau,
        pdf_filename=path.name,
        raw_extracted_text=full_text[:50000],
    )

    # Extract fields based on bureau
    if bureau == "experian":
        _parse_experian(full_text, profile)
    elif bureau == "transunion":
        _parse_transunion(full_text, profile)
    elif bureau == "equifax":
        _parse_equifax(full_text, profile)
    elif bureau in ("credit_karma", "credit_sesame"):
        _parse_aggregator(full_text, profile)
    else:
        _parse_generic(full_text, profile)

    # Common extraction that works across all formats
    _extract_common_fields(full_text, profile)

    inquiries = _extract_inquiries(full_text, bureau)
    profile.hard_inquiries_count = len(inquiries) if inquiries else profile.hard_inquiries_count

    return profile, inquiries


def parse_credit_report_full(pdf_path: str) -> dict:
    """Parse a credit report and return full analysis with confidence scoring.

    Returns dict with:
        profile: CreditProfile object
        inquiries: list of Inquiry objects
        extraction: confidence report dict
        field_details: per-field extraction details
    """
    profile, inquiries = parse_credit_report(pdf_path)
    extraction = profile.extraction_confidence()

    # Build detailed per-field report
    field_details = []
    for f in CreditProfile.EXTRACTABLE_FIELDS:
        val = getattr(profile, f)
        label = FIELD_LABELS.get(f, f.replace("_", " ").title())
        if val is not None:
            if isinstance(val, (int, float)) and f != "score":
                display = f"{val:,.1f}%" if "pct" in f else f"${val:,.0f}" if val > 100 else f"{val:.1f}"
            else:
                display = str(val)
            field_details.append({"field": f, "label": label, "value": display, "found": True})
        else:
            field_details.append({"field": f, "label": label, "value": None, "found": False})

    return {
        "profile": profile,
        "inquiries": inquiries,
        "extraction": extraction,
        "field_details": field_details,
    }


# ── Bureau Detection ──────────────────────────────────────────────────

def _detect_bureau(text: str) -> str:
    """Detect which bureau or service generated the report."""
    text_upper = text.upper()

    # Check aggregators first (they mention bureau names too)
    if "CREDIT KARMA" in text_upper or "CREDITKARMA" in text_upper:
        return "credit_karma"
    if "CREDIT SESAME" in text_upper or "CREDITSESAME" in text_upper:
        return "credit_sesame"

    # Direct bureau reports
    if "EXPERIAN" in text_upper:
        return "experian"
    if "TRANSUNION" in text_upper or "TRANS UNION" in text_upper:
        return "transunion"
    if "EQUIFAX" in text_upper:
        return "equifax"

    # AnnualCreditReport.com mentions all 3 bureaus — detect by format cues
    if "ANNUALCREDITREPORT" in text_upper:
        # Try to identify the specific bureau section
        if text_upper.count("EXPERIAN") > text_upper.count("TRANSUNION"):
            return "experian"
        if text_upper.count("TRANSUNION") > text_upper.count("EQUIFAX"):
            return "transunion"
        return "equifax"

    return "unknown"


# ── Score Extraction ─────────────────────────────────────────────────

def _extract_score(text: str) -> Optional[int]:
    """Extract credit score from report text."""
    patterns = [
        # Explicit labels
        r"(?:FICO|VantageScore)\s*(?:Score)?\s*(?:8|9|3\.0|4\.0)?\s*[:\s]*(\d{3})",
        r"(?:Your\s+)?(?:Credit\s+)?Score\s*(?:is|:)\s*(\d{3})",
        r"Score\s*[:\-]\s*(\d{3})",
        r"Credit\s+Score\s*[:\-]?\s*(\d{3})",
        # Ratio format: "720/850" or "720 out of 850"
        r"\b(\d{3})\s*(?:out\s+of|/)\s*(?:850|900)",
        # Score in context
        r"Score\s+Range.*?(\d{3})",
        r"Your\s+score\s+(?:of\s+)?(\d{3})",
        r"(?:Overall|Total)\s+Score\s*[:\-]?\s*(\d{3})",
        # Standalone 3-digit near score keywords
        r"(?:Score|Rating|FICO)\s{0,5}(\d{3})\b",
    ]
    for pat in patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            score = int(match.group(1))
            if 300 <= score <= 850:
                return score
    return None


def _extract_number(text: str, patterns: list[str]) -> Optional[int]:
    """Extract first integer match from a list of regex patterns."""
    for pat in patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            try:
                val = match.group(1).replace(",", "").strip()
                if val.upper() in ("N/A", "NA", "NOT AVAILABLE", "—", "-"):
                    continue
                return int(val)
            except (ValueError, IndexError):
                continue
    return None


def _extract_float(text: str, patterns: list[str]) -> Optional[float]:
    """Extract first float match from a list of regex patterns."""
    for pat in patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            try:
                val = match.group(1).replace(",", "").replace("%", "").strip()
                if val.upper() in ("N/A", "NA", "NOT AVAILABLE", "—", "-"):
                    continue
                return float(val)
            except (ValueError, IndexError):
                continue
    return None


def _extract_dollar(text: str, patterns: list[str]) -> Optional[float]:
    """Extract dollar amount from text."""
    for pat in patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            try:
                val = match.group(1).replace(",", "").replace("$", "").strip()
                if val.upper() in ("N/A", "NA", "NOT AVAILABLE", "—", "-"):
                    continue
                return float(val)
            except (ValueError, IndexError):
                continue
    return None


# ── Bureau-Specific Parsers ──────────────────────────────────────────

def _parse_experian(text: str, profile: CreditProfile):
    """Parse Experian-specific report format."""
    profile.score = _extract_score(text)

    profile.total_accounts = _extract_number(text, [
        r"Total\s+Accounts?\s*[:\-]?\s*(\d+)",
        r"(\d+)\s+Total\s+Accounts?",
        r"Number\s+of\s+Accounts?\s*[:\-]?\s*(\d+)",
        r"Total\s+(?:Trade\s*)?Lines?\s*[:\-]?\s*(\d+)",
        r"Accounts?\s+Total\s*[:\-]?\s*(\d+)",
    ])

    profile.open_accounts = _extract_number(text, [
        r"Open\s+Accounts?\s*[:\-]?\s*(\d+)",
        r"(\d+)\s+Open\s+Accounts?",
        r"Active\s+Accounts?\s*[:\-]?\s*(\d+)",
        r"Currently\s+Open\s*[:\-]?\s*(\d+)",
    ])

    profile.closed_accounts = _extract_number(text, [
        r"Closed\s+Accounts?\s*[:\-]?\s*(\d+)",
        r"(\d+)\s+Closed\s+Accounts?",
        r"Inactive\s+Accounts?\s*[:\-]?\s*(\d+)",
    ])

    profile.utilization_pct = _extract_float(text, [
        r"(?:Credit\s+)?Utilization\s*[:\-]?\s*([\d.]+)\s*%",
        r"([\d.]+)\s*%\s*(?:utilization|usage)",
        r"Revolving\s+Utilization\s*[:\-]?\s*([\d.]+)\s*%",
        r"Overall\s+(?:Credit\s+)?Usage\s*[:\-]?\s*([\d.]+)\s*%",
        r"Debt[\-\s]to[\-\s]Credit\s*[:\-]?\s*([\d.]+)\s*%",
        r"Credit\s+Usage\s*[:\-]?\s*([\d.]+)\s*%",
    ])

    profile.payment_history_pct = _extract_float(text, [
        r"Payment\s+History\s*[:\-]?\s*([\d.]+)\s*%",
        r"On[\-\s]Time\s+Payments?\s*[:\-]?\s*([\d.]+)\s*%",
        r"Positive\s+Payment\s*[:\-]?\s*([\d.]+)\s*%",
        r"Payments?\s+Made\s+On[\-\s]Time\s*[:\-]?\s*([\d.]+)\s*%",
        r"On[\-\s]Time\s*[:\-]?\s*([\d.]+)\s*%",
    ])

    profile.derogatory_marks = _extract_number(text, [
        r"Derogatory\s+(?:Marks?|Items?)\s*[:\-]?\s*(\d+)",
        r"(\d+)\s+Derogatory",
        r"Negative\s+(?:Marks?|Items?)\s*[:\-]?\s*(\d+)",
        r"(?:Public\s+)?Records?\s*[:\-]?\s*(\d+)",
        r"Derogatory\s*[:\-]?\s*(\d+)",
    ])

    profile.collections = _extract_number(text, [
        r"Collections?\s+Accounts?\s*[:\-]?\s*(\d+)",
        r"Collections?\s*[:\-]?\s*(\d+)",
        r"(\d+)\s+(?:collection|collections)",
        r"In\s+Collections?\s*[:\-]?\s*(\d+)",
        r"Accounts?\s+in\s+Collections?\s*[:\-]?\s*(\d+)",
    ])

    profile.total_credit_limit = _extract_dollar(text, [
        r"Total\s+(?:Credit\s+)?Limit\s*[:\-]?\s*\$?([\d,]+(?:\.\d{2})?)",
        r"Credit\s+Limit\s*[:\-]?\s*\$?([\d,]+(?:\.\d{2})?)",
        r"Available\s+Credit\s+Limit\s*[:\-]?\s*\$?([\d,]+(?:\.\d{2})?)",
        r"Combined\s+Credit\s+Limit\s*[:\-]?\s*\$?([\d,]+(?:\.\d{2})?)",
    ])

    profile.total_balance = _extract_dollar(text, [
        r"Total\s+Balance[s]?\s*[:\-]?\s*\$?([\d,]+(?:\.\d{2})?)",
        r"Balance[s]?\s*[:\-]?\s*\$?([\d,]+(?:\.\d{2})?)",
        r"Outstanding\s+Balance\s*[:\-]?\s*\$?([\d,]+(?:\.\d{2})?)",
        r"Total\s+Debt\s*[:\-]?\s*\$?([\d,]+(?:\.\d{2})?)",
    ])

    _extract_account_ages(text, profile)
    _extract_balance_breakdown(text, profile)


def _parse_transunion(text: str, profile: CreditProfile):
    """Parse TransUnion-specific report format."""
    profile.score = _extract_score(text)

    profile.total_accounts = _extract_number(text, [
        r"Total\s+Accounts?\s*[:\-]?\s*(\d+)",
        r"Number\s+of\s+Accounts?\s*[:\-]?\s*(\d+)",
        r"Total\s+(?:Trade\s*)?Lines?\s*[:\-]?\s*(\d+)",
        r"(\d+)\s+Total\s+Accounts?",
    ])

    profile.open_accounts = _extract_number(text, [
        r"Open\s+Accounts?\s*[:\-]?\s*(\d+)",
        r"Active\s+Accounts?\s*[:\-]?\s*(\d+)",
        r"Currently\s+Open\s*[:\-]?\s*(\d+)",
    ])

    profile.closed_accounts = _extract_number(text, [
        r"Closed\s+Accounts?\s*[:\-]?\s*(\d+)",
        r"(\d+)\s+Closed",
    ])

    profile.utilization_pct = _extract_float(text, [
        r"(?:Credit\s+)?Utilization\s*[:\-]?\s*([\d.]+)\s*%",
        r"Debt[\-\s]to[\-\s]Credit\s*[:\-]?\s*([\d.]+)\s*%",
        r"Usage\s*[:\-]?\s*([\d.]+)\s*%",
        r"Credit\s+Usage\s*[:\-]?\s*([\d.]+)\s*%",
        r"Overall\s+Usage\s*[:\-]?\s*([\d.]+)\s*%",
    ])

    profile.payment_history_pct = _extract_float(text, [
        r"Payment\s+History\s*[:\-]?\s*([\d.]+)\s*%",
        r"On[\-\s]Time\s*[:\-]?\s*([\d.]+)\s*%",
        r"On[\-\s]Time\s+Payments?\s*[:\-]?\s*([\d.]+)\s*%",
        r"Positive\s+Payments?\s*[:\-]?\s*([\d.]+)\s*%",
    ])

    profile.derogatory_marks = _extract_number(text, [
        r"Derogatory\s+(?:Marks?|Items?)\s*[:\-]?\s*(\d+)",
        r"Derogatory\s*[:\-]?\s*(\d+)",
        r"Negative\s+Items?\s*[:\-]?\s*(\d+)",
        r"Adverse\s+Items?\s*[:\-]?\s*(\d+)",
    ])

    profile.collections = _extract_number(text, [
        r"Collections?\s+Accounts?\s*[:\-]?\s*(\d+)",
        r"Collections?\s*[:\-]?\s*(\d+)",
        r"In\s+Collections?\s*[:\-]?\s*(\d+)",
    ])

    profile.total_credit_limit = _extract_dollar(text, [
        r"Total\s+(?:Credit\s+)?Limit\s*[:\-]?\s*\$?([\d,]+(?:\.\d{2})?)",
        r"Credit\s+Limit\s*[:\-]?\s*\$?([\d,]+(?:\.\d{2})?)",
    ])

    profile.total_balance = _extract_dollar(text, [
        r"Total\s+Balance[s]?\s*[:\-]?\s*\$?([\d,]+(?:\.\d{2})?)",
        r"Balance[s]?\s*[:\-]?\s*\$?([\d,]+(?:\.\d{2})?)",
    ])

    _extract_account_ages(text, profile)
    _extract_balance_breakdown(text, profile)


def _parse_equifax(text: str, profile: CreditProfile):
    """Parse Equifax-specific report format."""
    profile.score = _extract_score(text)

    profile.total_accounts = _extract_number(text, [
        r"Total\s+Accounts?\s*[:\-]?\s*(\d+)",
        r"Number\s+of\s+Accounts?\s*[:\-]?\s*(\d+)",
        r"(\d+)\s+Total\s+Accounts?",
    ])

    profile.open_accounts = _extract_number(text, [
        r"Open\s+Accounts?\s*[:\-]?\s*(\d+)",
        r"Active\s+Accounts?\s*[:\-]?\s*(\d+)",
    ])

    profile.closed_accounts = _extract_number(text, [
        r"Closed\s+Accounts?\s*[:\-]?\s*(\d+)",
        r"(\d+)\s+Closed",
    ])

    profile.utilization_pct = _extract_float(text, [
        r"(?:Credit\s+)?Utilization\s*[:\-]?\s*([\d.]+)\s*%",
        r"Usage\s*[:\-]?\s*([\d.]+)\s*%",
        r"Debt[\-\s]to[\-\s]Credit\s*[:\-]?\s*([\d.]+)\s*%",
        r"Credit\s+Usage\s*[:\-]?\s*([\d.]+)\s*%",
    ])

    profile.payment_history_pct = _extract_float(text, [
        r"Payment\s+History\s*[:\-]?\s*([\d.]+)\s*%",
        r"On[\-\s]Time\s*[:\-]?\s*([\d.]+)\s*%",
    ])

    profile.derogatory_marks = _extract_number(text, [
        r"Derogatory\s+(?:Marks?|Items?)\s*[:\-]?\s*(\d+)",
        r"Derogatory\s*[:\-]?\s*(\d+)",
        r"Negative\s+Items?\s*[:\-]?\s*(\d+)",
    ])

    profile.collections = _extract_number(text, [
        r"Collections?\s+Accounts?\s*[:\-]?\s*(\d+)",
        r"Collections?\s*[:\-]?\s*(\d+)",
    ])

    profile.total_credit_limit = _extract_dollar(text, [
        r"Total\s+(?:Credit\s+)?Limit\s*[:\-]?\s*\$?([\d,]+(?:\.\d{2})?)",
        r"Credit\s+Limit\s*[:\-]?\s*\$?([\d,]+(?:\.\d{2})?)",
    ])

    profile.total_balance = _extract_dollar(text, [
        r"Total\s+Balance[s]?\s*[:\-]?\s*\$?([\d,]+(?:\.\d{2})?)",
        r"Balance[s]?\s*[:\-]?\s*\$?([\d,]+(?:\.\d{2})?)",
    ])

    _extract_account_ages(text, profile)
    _extract_balance_breakdown(text, profile)


def _parse_aggregator(text: str, profile: CreditProfile):
    """Parse Credit Karma / Credit Sesame format."""
    profile.score = _extract_score(text)

    # Aggregators often use cleaner formatting
    profile.total_accounts = _extract_number(text, [
        r"Total\s+Accounts?\s*[:\-]?\s*(\d+)",
        r"(\d+)\s+(?:total\s+)?accounts?",
        r"Number\s+of\s+Accounts?\s*[:\-]?\s*(\d+)",
    ])

    profile.open_accounts = _extract_number(text, [
        r"Open\s+Accounts?\s*[:\-]?\s*(\d+)",
        r"(\d+)\s+Open",
    ])

    profile.closed_accounts = _extract_number(text, [
        r"Closed\s+Accounts?\s*[:\-]?\s*(\d+)",
        r"(\d+)\s+Closed",
    ])

    profile.utilization_pct = _extract_float(text, [
        r"(?:Credit\s+(?:Card\s+)?)?(?:Utilization|Usage)\s*[:\-]?\s*([\d.]+)\s*%",
        r"([\d.]+)\s*%\s*(?:utilization|usage|used)",
    ])

    profile.payment_history_pct = _extract_float(text, [
        r"(?:Payment|On[\-\s]Time)\s+(?:History)?\s*[:\-]?\s*([\d.]+)\s*%",
        r"On[\-\s]Time\s+Payments?\s*[:\-]?\s*([\d.]+)\s*%",
    ])

    profile.derogatory_marks = _extract_number(text, [
        r"Derogatory\s+(?:Marks?|Items?)\s*[:\-]?\s*(\d+)",
        r"Negative\s+(?:Marks?|Items?)\s*[:\-]?\s*(\d+)",
    ])

    profile.collections = _extract_number(text, [
        r"Collections?\s*[:\-]?\s*(\d+)",
    ])

    profile.total_credit_limit = _extract_dollar(text, [
        r"Total\s+(?:Credit\s+)?Limit\s*[:\-]?\s*\$?([\d,]+(?:\.\d{2})?)",
    ])

    profile.total_balance = _extract_dollar(text, [
        r"Total\s+(?:Balance|Debt)\s*[:\-]?\s*\$?([\d,]+(?:\.\d{2})?)",
    ])

    _extract_account_ages(text, profile)
    _extract_balance_breakdown(text, profile)


def _parse_generic(text: str, profile: CreditProfile):
    """Fallback parser for unknown bureau format — tries all patterns."""
    profile.score = _extract_score(text)

    profile.total_accounts = _extract_number(text, [
        r"Total\s+Accounts?\s*[:\-]?\s*(\d+)",
        r"(\d+)\s+(?:total\s+)?accounts?",
        r"Number\s+of\s+Accounts?\s*[:\-]?\s*(\d+)",
    ])

    profile.open_accounts = _extract_number(text, [
        r"Open\s+Accounts?\s*[:\-]?\s*(\d+)",
        r"Active\s+Accounts?\s*[:\-]?\s*(\d+)",
    ])

    profile.closed_accounts = _extract_number(text, [
        r"Closed\s+Accounts?\s*[:\-]?\s*(\d+)",
    ])

    profile.utilization_pct = _extract_float(text, [
        r"(?:Credit\s+)?Utilization\s*[:\-]?\s*([\d.]+)\s*%",
        r"Usage\s*[:\-]?\s*([\d.]+)\s*%",
    ])

    profile.payment_history_pct = _extract_float(text, [
        r"Payment\s+History\s*[:\-]?\s*([\d.]+)\s*%",
        r"On[\-\s]Time\s*[:\-]?\s*([\d.]+)\s*%",
    ])

    profile.derogatory_marks = _extract_number(text, [
        r"Derogatory\s*[:\-]?\s*(\d+)",
        r"Negative\s+Items?\s*[:\-]?\s*(\d+)",
    ])

    profile.collections = _extract_number(text, [
        r"Collections?\s*[:\-]?\s*(\d+)",
    ])

    profile.total_credit_limit = _extract_dollar(text, [
        r"Total\s+(?:Credit\s+)?Limit\s*[:\-]?\s*\$?([\d,]+(?:\.\d{2})?)",
    ])

    profile.total_balance = _extract_dollar(text, [
        r"Total\s+Balance\s*[:\-]?\s*\$?([\d,]+(?:\.\d{2})?)",
    ])

    _extract_account_ages(text, profile)
    _extract_balance_breakdown(text, profile)


# ── Common Field Extraction (runs for all bureaus) ────────────────────

def _extract_common_fields(text: str, profile: CreditProfile):
    """Extract fields that work across formats — fills gaps from bureau-specific parsing."""

    # New accounts (last 6 months / recent)
    if profile.new_accounts_6mo is None:
        profile.new_accounts_6mo = _extract_number(text, [
            r"New\s+Accounts?\s*(?:\(6\s*(?:mo|month)s?\))?\s*[:\-]?\s*(\d+)",
            r"(?:Accounts?\s+)?Opened\s+(?:in\s+)?(?:Last|Past)\s+(?:6|12)\s+(?:Mo|Month)\s*[:\-]?\s*(\d+)",
            r"Recent(?:ly)?\s+Opened\s*[:\-]?\s*(\d+)",
            r"New\s+Credit\s*[:\-]?\s*(\d+)",
        ])

    # Infer closed accounts if we have total and open
    if profile.closed_accounts is None and profile.total_accounts and profile.open_accounts:
        profile.closed_accounts = max(0, profile.total_accounts - profile.open_accounts)

    # Hard inquiry count from text if not from inquiry list
    if profile.hard_inquiries_count is None:
        profile.hard_inquiries_count = _extract_number(text, [
            r"Hard\s+(?:Credit\s+)?Inquir(?:y|ies)\s*[:\-]?\s*(\d+)",
            r"(\d+)\s+Hard\s+Inquir(?:y|ies)",
            r"Inquir(?:y|ies)\s*[:\-]?\s*(\d+)",
            r"Credit\s+Inquir(?:y|ies)\s*[:\-]?\s*(\d+)",
            r"Requests?\s+(?:for|Viewed)\s*[:\-]?\s*(\d+)",
        ])


def _extract_balance_breakdown(text: str, profile: CreditProfile):
    """Extract revolving vs installment balance breakdown."""
    if profile.revolving_balance is None:
        profile.revolving_balance = _extract_dollar(text, [
            r"Revolving\s+(?:Balance|Debt)\s*[:\-]?\s*\$?([\d,]+(?:\.\d{2})?)",
            r"Revolving\s+Accounts?\s+Balance\s*[:\-]?\s*\$?([\d,]+(?:\.\d{2})?)",
            r"Credit\s+Card\s+(?:Balance|Debt)\s*[:\-]?\s*\$?([\d,]+(?:\.\d{2})?)",
        ])

    if profile.installment_balance is None:
        profile.installment_balance = _extract_dollar(text, [
            r"Installment\s+(?:Balance|Debt)\s*[:\-]?\s*\$?([\d,]+(?:\.\d{2})?)",
            r"Installment\s+(?:Loan|Account)s?\s+Balance\s*[:\-]?\s*\$?([\d,]+(?:\.\d{2})?)",
            r"(?:Mortgage|Auto|Student)\s+(?:Loan\s+)?Balance\s*[:\-]?\s*\$?([\d,]+(?:\.\d{2})?)",
        ])


# ── Account Age Extraction ───────────────────────────────────────────

def _extract_account_ages(text: str, profile: CreditProfile):
    """Extract average and oldest account age."""
    # Average age — years+months format
    avg_ym = re.search(
        r"(?:Average|Avg)\s+(?:Age|Length)\s+(?:of\s+)?(?:Accounts?|History|Open\s+Accounts?)"
        r".*?(\d+)\s*(?:yr|year)s?\s*(?:,?\s*(\d+)\s*(?:mo|month)s?)?",
        text, re.IGNORECASE,
    )
    if avg_ym:
        years = int(avg_ym.group(1))
        months = int(avg_ym.group(2)) if avg_ym.group(2) else 0
        profile.avg_age_years = years + months / 12
    else:
        # Try simple year-only patterns
        profile.avg_age_years = _extract_float(text, [
            r"(?:Average|Avg)\s+(?:Age|Length)\s*[:\-]?\s*([\d.]+)\s*(?:yr|year)",
            r"Avg\.?\s+Age\s*[:\-]?\s*([\d.]+)",
        ])

    # Oldest account — years+months format
    oldest_ym = re.search(
        r"(?:Oldest|Longest|First)\s+(?:Account|Trade\s*Line|History|Open\s+Account)"
        r".*?(\d+)\s*(?:yr|year)s?\s*(?:,?\s*(\d+)\s*(?:mo|month)s?)?",
        text, re.IGNORECASE,
    )
    if oldest_ym:
        years = int(oldest_ym.group(1))
        months = int(oldest_ym.group(2)) if oldest_ym.group(2) else 0
        profile.oldest_account_years = years + months / 12
    else:
        profile.oldest_account_years = _extract_float(text, [
            r"(?:Oldest|Longest)\s+(?:Account|Trade)\s*[:\-]?\s*([\d.]+)\s*(?:yr|year)",
            r"(?:Oldest|First)\s+Account\s*[:\-]?\s*([\d.]+)",
        ])


# ── Inquiry Extraction ───────────────────────────────────────────────

def _extract_inquiries(text: str, bureau: str) -> list[Inquiry]:
    """Extract hard inquiry list from report text."""
    inquiries = []

    # Look for inquiry section
    inquiry_section = _find_section(text, [
        r"(?:Hard\s+)?Inquiries",
        r"Regular\s+Inquiries",
        r"Requests?\s+Viewed\s+by\s+Others",
        r"Credit\s+Inquiries",
        r"Companies?\s+(?:That|Who)\s+Requested",
        r"Inquiries?\s+(?:That|Which)\s+May\s+Affect",
    ])

    if not inquiry_section:
        return inquiries

    # Extract lender + date pairs — multiple format patterns
    date_patterns = [
        # "LENDER NAME   01/15/2026"
        r"([A-Z][A-Za-z\s&'.,/\-]+?)\s{2,}(\d{1,2}/\d{1,2}/\d{2,4})",
        # "LENDER NAME   Jan 15, 2026"
        r"([A-Z][A-Za-z\s&'.,/\-]+?)\s{2,}(\w{3}\s+\d{1,2},?\s+\d{4})",
        # "LENDER NAME   2026-01-15"
        r"([A-Z][A-Za-z\s&'.,/\-]+?)\s+(\d{4}-\d{2}-\d{2})",
        # "01/15/2026   LENDER NAME" (date first)
        r"(\d{1,2}/\d{1,2}/\d{2,4})\s{2,}([A-Z][A-Za-z\s&'.,/\-]+)",
    ]

    seen = set()  # deduplicate
    for pat in date_patterns:
        matches = re.findall(pat, inquiry_section)
        for groups in matches:
            # Handle date-first vs lender-first formats
            if re.match(r"\d", groups[0]):
                date_str, lender_name = groups
            else:
                lender_name, date_str = groups

            lender_name = lender_name.strip().rstrip(",.")
            if len(lender_name) < 2 or len(lender_name) > 60:
                continue
            # Skip section headers that look like lender names
            if any(kw in lender_name.upper() for kw in [
                "INQUIRY", "REQUEST", "SECTION", "HARD", "SOFT", "PAGE", "REPORT"
            ]):
                continue

            normalized_date = _normalize_date(date_str)
            if not normalized_date:
                continue

            key = (lender_name.lower(), normalized_date)
            if key in seen:
                continue
            seen.add(key)

            falls_off = _add_years(normalized_date, 2)

            inq = Inquiry(
                date=normalized_date,
                bureau=bureau if bureau not in ("credit_karma", "credit_sesame", "unknown") else "unknown",
                lender=lender_name,
                falls_off_date=falls_off,
                source="parsed",
            )
            inquiries.append(inq)

    return inquiries


def _find_section(text: str, header_patterns: list[str]) -> Optional[str]:
    """Find a section of text starting with one of the header patterns."""
    for pat in header_patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            start = match.start()
            remaining = text[start:start + 5000]
            # End at next major section header
            next_section = re.search(
                r"\n\s*(?:Account\s+(?:Information|Details|Summary)|"
                r"Public\s+Records?|Personal\s+(?:Information|Details)|"
                r"Summary|Consumer\s+Statement|"
                r"Promotional\s+Inquiries|Soft\s+Inquiries)",
                remaining[100:], re.IGNORECASE,
            )
            if next_section:
                return remaining[:100 + next_section.start()]
            return remaining
    return None


def _normalize_date(date_str: str) -> Optional[str]:
    """Normalize various date formats to ISO YYYY-MM-DD."""
    from datetime import datetime

    formats = [
        "%m/%d/%Y",
        "%m/%d/%y",
        "%b %d, %Y",
        "%b %d %Y",
        "%Y-%m-%d",
        "%B %d, %Y",
        "%B %d %Y",
        "%d %b %Y",
        "%d %B %Y",
        "%m-%d-%Y",
        "%m-%d-%y",
    ]

    date_str = date_str.strip()
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            # Sanity check year
            if dt.year < 2000 or dt.year > 2030:
                continue
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _add_years(date_str: str, years: int) -> str:
    """Add years to an ISO date string."""
    from datetime import datetime

    dt = datetime.strptime(date_str, "%Y-%m-%d")
    try:
        return dt.replace(year=dt.year + years).strftime("%Y-%m-%d")
    except ValueError:
        return dt.replace(year=dt.year + years, day=28).strftime("%Y-%m-%d")


# ── Credit Health Analysis ───────────────────────────────────────────

def analyze_credit_health(profile: CreditProfile) -> dict:
    """Generate credit health analysis from a parsed profile."""
    analysis = {
        "factors": [],
        "warnings": [],
        "strengths": [],
        "overall_rating": "unknown",
        "overall_color": "var(--text2)",
    }

    # Score analysis
    if profile.score:
        s = profile.score
        if s >= 740:
            rating, color, label = "Excellent", "var(--green)", "excellent"
            analysis["strengths"].append(f"Score {s} — top tier, qualifies for premium products")
        elif s >= 700:
            rating, color, label = "Good", "var(--green)", "good"
            analysis["strengths"].append(f"Score {s} — qualifies for most business products")
        elif s >= 670:
            rating, color, label = "Fair", "var(--yellow)", "fair"
            analysis["warnings"].append(f"Score {s} — some premium products may be out of reach")
        elif s >= 620:
            rating, color, label = "Below Average", "var(--orange)", "below_average"
            analysis["warnings"].append(f"Score {s} — limited to starter/mid-tier products")
        else:
            rating, color, label = "Poor", "var(--red)", "poor"
            analysis["warnings"].append(f"Score {s} — focus on building credit before applying")

        analysis["factors"].append({
            "name": "Credit Score", "value": str(s), "rating": rating,
            "color": color, "label": label, "max": "850",
        })
        analysis["overall_rating"] = rating
        analysis["overall_color"] = color

    # Utilization analysis
    if profile.utilization_pct is not None:
        u = profile.utilization_pct
        if u <= 10:
            rating, color = "Optimal", "var(--green)"
            analysis["strengths"].append(f"Utilization {u:.0f}% — optimal range for approvals")
        elif u <= 30:
            rating, color = "Good", "var(--green)"
            analysis["strengths"].append(f"Utilization {u:.0f}% — within acceptable range")
        elif u <= 50:
            rating, color = "High", "var(--yellow)"
            analysis["warnings"].append(f"Utilization {u:.0f}% — pay down to under 30% before applying")
        else:
            rating, color = "Critical", "var(--red)"
            analysis["warnings"].append(f"Utilization {u:.0f}% — severely hurting score and approvals")

        analysis["factors"].append({
            "name": "Utilization", "value": f"{u:.0f}%", "rating": rating,
            "color": color, "target": "< 10%", "pct": min(u, 100),
        })

    # Payment history
    if profile.payment_history_pct is not None:
        p = profile.payment_history_pct
        if p >= 99:
            rating, color = "Perfect", "var(--green)"
            analysis["strengths"].append("Perfect payment history")
        elif p >= 95:
            rating, color = "Excellent", "var(--green)"
            analysis["strengths"].append(f"Payment history {p:.0f}% — strong track record")
        elif p >= 90:
            rating, color = "Good", "var(--yellow)"
        else:
            rating, color = "Needs Work", "var(--red)"
            analysis["warnings"].append(f"Payment history {p:.0f}% — late payments hurt approvals")

        analysis["factors"].append({
            "name": "Payment History", "value": f"{p:.0f}%", "rating": rating, "color": color,
        })

    # Derogatory marks
    derogs = (profile.derogatory_marks or 0) + (profile.collections or 0)
    if derogs == 0:
        analysis["strengths"].append("No derogatory marks — clean record")
        analysis["factors"].append({
            "name": "Derogatory Marks", "value": "0", "rating": "Clean", "color": "var(--green)",
        })
    elif derogs <= 2:
        analysis["warnings"].append(f"{derogs} negative mark(s) — consider disputing or pay-for-delete")
        analysis["factors"].append({
            "name": "Derogatory Marks", "value": str(derogs), "rating": "Warning", "color": "var(--yellow)",
        })
    else:
        analysis["warnings"].append(f"{derogs} negative marks — significant barrier to approvals")
        analysis["factors"].append({
            "name": "Derogatory Marks", "value": str(derogs), "rating": "Critical", "color": "var(--red)",
        })

    # Account age
    if profile.avg_age_years is not None:
        a = profile.avg_age_years
        if a >= 7:
            rating, color = "Excellent", "var(--green)"
            analysis["strengths"].append(f"Average account age {a:.1f} years — strong history")
        elif a >= 3:
            rating, color = "Good", "var(--blue)"
        elif a >= 1:
            rating, color = "Young", "var(--yellow)"
            analysis["warnings"].append(f"Average age {a:.1f} years — thin file may limit approvals")
        else:
            rating, color = "Very New", "var(--red)"
            analysis["warnings"].append(f"Average age under 1 year — very thin file")

        analysis["factors"].append({
            "name": "Account Age", "value": f"{a:.1f} yrs",
            "oldest": f"{profile.oldest_account_years:.1f} yrs" if profile.oldest_account_years else None,
            "rating": rating, "color": color,
        })

    # Inquiries
    if profile.hard_inquiries_count is not None:
        h = profile.hard_inquiries_count
        if h == 0:
            rating, color = "Clean", "var(--green)"
            analysis["strengths"].append("No hard inquiries — excellent for applications")
        elif h <= 3:
            rating, color = "Good", "var(--green)"
        elif h <= 6:
            rating, color = "Moderate", "var(--yellow)"
            analysis["warnings"].append(f"{h} hard inquiries — some inquiry-sensitive lenders may decline")
        else:
            rating, color = "Heavy", "var(--red)"
            analysis["warnings"].append(f"{h} hard inquiries — consider a cooling period before applying")

        analysis["factors"].append({
            "name": "Hard Inquiries", "value": str(h), "rating": rating, "color": color,
        })

    return analysis
