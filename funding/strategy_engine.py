"""Funding strategy recommendation engine.

Analyzes credit profile, inquiry history, and application history to recommend
optimal application order, timing, and bureau targeting. All strategies are
based on well-documented, publicly available credit optimization knowledge.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from .database import FundingDB
from .models import (
    Application,
    CreditProfile,
    FundingProduct,
    Inquiry,
    Recommendation,
    StrategyRound,
)

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────

COOLING_PERIOD_DAYS = 90       # Min days between heavy application rounds
INQUIRY_AGING_MONTHS = 6       # Months for inquiries to have less impact
INQUIRY_FALLOFF_YEARS = 2      # Years until inquiry drops from report
MAX_APPS_PER_ROUND = 5         # Max applications in a single round
VELOCITY_LIMIT_6MO = 3         # Max new accounts per bureau per 6 months
CHASE_524_WINDOW_MONTHS = 24   # Chase 5/24 rule window
CHASE_524_LIMIT = 5            # Max new accounts for Chase eligibility
UTILIZATION_OPTIMAL = 10.0     # Optimal utilization percentage
UTILIZATION_GOOD = 30.0        # Good utilization threshold
UTILIZATION_WARNING = 50.0     # Warning utilization threshold


def get_recommendations(db: FundingDB) -> list[Recommendation]:
    """Generate prioritized funding strategy recommendations."""
    profile = db.get_latest_profile()
    inquiries = db.get_inquiries(active_only=True)
    all_apps = db.get_all_applications()
    products = db.get_products()
    last_round = db.get_last_completed_round()

    recommendations = []
    priority = 1

    # 1. Check if we have a credit profile
    if not profile:
        recommendations.append(Recommendation(
            priority=priority, category="action",
            title="Upload Credit Report",
            detail="Parse a credit report PDF first: funding parse <pdf_path>",
            impact="high",
        ))
        return recommendations

    # 2. Score optimization
    score_recs = _score_optimization(profile, priority)
    recommendations.extend(score_recs)
    priority += len(score_recs)

    # 3. Utilization optimization
    util_recs = _utilization_optimization(profile, priority)
    recommendations.extend(util_recs)
    priority += len(util_recs)

    # 4. Inquiry management
    inq_recs = _inquiry_management(inquiries, all_apps, priority)
    recommendations.extend(inq_recs)
    priority += len(inq_recs)

    # 5. Cooling period check
    cool_recs = _cooling_period_check(last_round, priority)
    recommendations.extend(cool_recs)
    priority += len(cool_recs)

    # 6. Eligible products
    prod_recs = _eligible_products(profile, inquiries, all_apps, products, priority)
    recommendations.extend(prod_recs)
    priority += len(prod_recs)

    # 7. Application order strategy
    order_recs = _application_order(profile, inquiries, all_apps, products, priority)
    recommendations.extend(order_recs)
    priority += len(order_recs)

    # 8. Derogatory / collections flags
    derog_recs = _derogatory_check(profile, priority)
    recommendations.extend(derog_recs)

    return recommendations


def plan_round(db: FundingDB, max_apps: int = MAX_APPS_PER_ROUND) -> list[FundingProduct]:
    """Plan the next funding round — returns products in optimal application order."""
    profile = db.get_latest_profile()
    if not profile:
        return []

    inquiries = db.get_inquiries(active_only=True)
    all_apps = db.get_all_applications()
    products = db.get_products()

    eligible = _get_eligible_products(profile, inquiries, all_apps, products)
    ordered = _order_for_round(eligible, inquiries)

    return ordered[:max_apps]


def get_readiness_score(db: FundingDB) -> dict:
    """Calculate overall readiness score for a funding round."""
    profile = db.get_latest_profile()
    if not profile:
        return {"score": 0, "max": 100, "factors": {"no_profile": "Upload a credit report first"}}

    factors = {}
    score = 0

    # Score factor (25 points)
    if profile.score:
        if profile.score >= 740:
            score += 25
            factors["credit_score"] = f"{profile.score} — Excellent"
        elif profile.score >= 700:
            score += 20
            factors["credit_score"] = f"{profile.score} — Good"
        elif profile.score >= 670:
            score += 15
            factors["credit_score"] = f"{profile.score} — Fair"
        elif profile.score >= 620:
            score += 10
            factors["credit_score"] = f"{profile.score} — Below average"
        else:
            score += 5
            factors["credit_score"] = f"{profile.score} — Needs improvement"

    # Utilization factor (25 points)
    if profile.utilization_pct is not None:
        if profile.utilization_pct <= UTILIZATION_OPTIMAL:
            score += 25
            factors["utilization"] = f"{profile.utilization_pct:.0f}% — Optimal"
        elif profile.utilization_pct <= UTILIZATION_GOOD:
            score += 20
            factors["utilization"] = f"{profile.utilization_pct:.0f}% — Good"
        elif profile.utilization_pct <= UTILIZATION_WARNING:
            score += 10
            factors["utilization"] = f"{profile.utilization_pct:.0f}% — High"
        else:
            score += 5
            factors["utilization"] = f"{profile.utilization_pct:.0f}% — Too high"

    # Inquiry factor (25 points)
    inq_counts = db.get_inquiry_counts_by_bureau(12)
    total_inq = sum(inq_counts.values())
    if total_inq == 0:
        score += 25
        factors["inquiries"] = "0 inquiries (12 mo) — Clean"
    elif total_inq <= 3:
        score += 20
        factors["inquiries"] = f"{total_inq} inquiries (12 mo) — Good"
    elif total_inq <= 6:
        score += 15
        factors["inquiries"] = f"{total_inq} inquiries (12 mo) — Moderate"
    else:
        score += 5
        factors["inquiries"] = f"{total_inq} inquiries (12 mo) — Heavy"

    # Derogatory factor (25 points)
    derogs = (profile.derogatory_marks or 0) + (profile.collections or 0)
    if derogs == 0:
        score += 25
        factors["derogatories"] = "0 — Clean record"
    elif derogs <= 2:
        score += 10
        factors["derogatories"] = f"{derogs} — Some negative marks"
    else:
        score += 0
        factors["derogatories"] = f"{derogs} — Significant negative marks"

    # Cooling period check
    last_round = db.get_last_completed_round()
    if last_round and last_round.executed_date:
        days_ago = (datetime.utcnow() - datetime.fromisoformat(last_round.executed_date)).days
        if days_ago < COOLING_PERIOD_DAYS:
            factors["cooling"] = f"{COOLING_PERIOD_DAYS - days_ago} days until next round recommended"
        else:
            factors["cooling"] = "Cooling period complete"

    return {"score": score, "max": 100, "factors": factors}


# ── Internal Recommendation Generators ───────────────────────────────

def _score_optimization(profile: CreditProfile, start_priority: int) -> list[Recommendation]:
    recs: list[Recommendation] = []
    if not profile.score:
        return recs

    if profile.score < 620:
        recs.append(Recommendation(
            priority=start_priority, category="score_optimization",
            title="Build Credit Score First",
            detail=f"Score {profile.score} is below most lender minimums (620-700). "
                   "Focus on on-time payments and reducing balances before applying.",
            impact="high",
        ))
    elif profile.score < 680:
        recs.append(Recommendation(
            priority=start_priority, category="score_optimization",
            title="Score Improvement Opportunity",
            detail=f"Score {profile.score} qualifies for starter/mid-tier products. "
                   "Reaching 700+ unlocks premium cards with higher limits.",
            impact="medium",
        ))

    return recs


def _utilization_optimization(profile: CreditProfile, start_priority: int) -> list[Recommendation]:
    recs: list[Recommendation] = []
    if profile.utilization_pct is None:
        return recs

    p = start_priority
    if profile.utilization_pct > UTILIZATION_WARNING:
        recs.append(Recommendation(
            priority=p, category="score_optimization",
            title="Critical: Reduce Utilization",
            detail=f"Utilization at {profile.utilization_pct:.0f}% — severely impacts score and approvals. "
                   f"Pay down to under {UTILIZATION_GOOD:.0f}% before applying. "
                   f"Optimal is under {UTILIZATION_OPTIMAL:.0f}%.",
            impact="high",
        ))
    elif profile.utilization_pct > UTILIZATION_GOOD:
        recs.append(Recommendation(
            priority=p, category="score_optimization",
            title="Reduce Utilization Before Applying",
            detail=f"Utilization at {profile.utilization_pct:.0f}% — pay down to "
                   f"under {UTILIZATION_OPTIMAL:.0f}% for best approval odds.",
            impact="medium",
        ))
    elif profile.utilization_pct > UTILIZATION_OPTIMAL:
        recs.append(Recommendation(
            priority=p, category="score_optimization",
            title="Optimize Utilization",
            detail=f"Utilization at {profile.utilization_pct:.0f}% — good, but "
                   f"reducing to under {UTILIZATION_OPTIMAL:.0f}% could boost score 10-20 points.",
            impact="low",
        ))

    return recs


def _inquiry_management(inquiries: list[Inquiry], apps: list[Application], start_priority: int) -> list[Recommendation]:
    recs: list[Recommendation] = []
    p = start_priority

    # Group by bureau (last 12 months)
    cutoff = (datetime.utcnow() - timedelta(days=365)).strftime("%Y-%m-%d")
    recent = [i for i in inquiries if i.date >= cutoff]
    by_bureau = defaultdict(list)
    for inq in recent:
        by_bureau[inq.bureau].append(inq)

    if not by_bureau:
        recs.append(Recommendation(
            priority=p, category="inquiry_mgmt",
            title="Clean Inquiry Profile",
            detail="No hard inquiries in the last 12 months — excellent position for applications.",
            impact="low",
        ))
        return recs

    # Find least-hit bureau
    bureaus = ["experian", "transunion", "equifax"]
    bureau_counts = {b: len(by_bureau.get(b, [])) for b in bureaus}
    least_hit = min(bureau_counts, key=lambda b: bureau_counts[b])

    recs.append(Recommendation(
        priority=p, category="inquiry_mgmt",
        title=f"Target {least_hit.title()} Lenders",
        detail=f"Inquiry counts (12 mo): {', '.join(f'{b.title()}: {c}' for b, c in bureau_counts.items())}. "
               f"Prioritize lenders that pull {least_hit.title()} ({bureau_counts[least_hit]} inquiries).",
        impact="medium",
    ))
    p += 1

    # Check 5/24 status (Chase rule — counts ALL new accounts, not just inquiries)
    total_new_accounts_24mo = sum(
        1 for a in apps
        if a.status == "approved"
        and a.applied_date
        and a.applied_date >= (datetime.utcnow() - timedelta(days=CHASE_524_WINDOW_MONTHS * 30)).strftime("%Y-%m-%d")
    )

    if total_new_accounts_24mo < CHASE_524_LIMIT:
        remaining = CHASE_524_LIMIT - total_new_accounts_24mo
        recs.append(Recommendation(
            priority=p, category="inquiry_mgmt",
            title=f"Chase 5/24 Eligible ({remaining} Slots)",
            detail=f"{total_new_accounts_24mo}/5 new accounts in 24 months. "
                   f"You have {remaining} slot(s) — apply to Chase cards FIRST before other lenders.",
            impact="high",
        ))
    else:
        recs.append(Recommendation(
            priority=p, category="inquiry_mgmt",
            title="Chase 5/24 Locked Out",
            detail=f"{total_new_accounts_24mo}/5 new accounts in 24 months. "
                   "Skip Chase cards this round — focus on Amex, Capital One, and other non-5/24 lenders.",
            impact="medium",
        ))

    return recs


def _cooling_period_check(last_round: Optional[StrategyRound], start_priority: int) -> list[Recommendation]:
    recs: list[Recommendation] = []
    if not last_round or not last_round.executed_date:
        return recs

    try:
        executed = datetime.fromisoformat(last_round.executed_date)
    except (ValueError, TypeError):
        return recs

    days_since = (datetime.utcnow() - executed).days

    if days_since < COOLING_PERIOD_DAYS:
        remaining = COOLING_PERIOD_DAYS - days_since
        recs.append(Recommendation(
            priority=start_priority, category="cooling",
            title=f"Cooling Period: {remaining} Days Remaining",
            detail=f"Last round completed {days_since} days ago. "
                   f"Wait {remaining} more days for inquiries to age and score to recover. "
                   f"Target date: {(executed + timedelta(days=COOLING_PERIOD_DAYS)).strftime('%Y-%m-%d')}.",
            impact="high",
        ))
    else:
        recs.append(Recommendation(
            priority=start_priority, category="cooling",
            title="Cooling Period Complete",
            detail=f"Last round was {days_since} days ago — you're clear for the next round.",
            impact="low",
        ))

    return recs


def _eligible_products(
    profile: CreditProfile,
    inquiries: list[Inquiry],
    apps: list[Application],
    products: list[FundingProduct],
    start_priority: int,
) -> list[Recommendation]:
    recs: list[Recommendation] = []
    eligible = _get_eligible_products(profile, inquiries, apps, products)

    if not eligible:
        recs.append(Recommendation(
            priority=start_priority, category="product",
            title="No New Eligible Products",
            detail="All catalog products have been applied to or score requirements aren't met.",
            impact="low",
        ))
    else:
        by_type = defaultdict(list)
        for p in eligible:
            by_type[p.product_type].append(p)

        summary_parts = []
        for ptype, prods in by_type.items():
            names = ", ".join(f"{p.lender} {p.product_name}" for p in prods[:3])
            extra = f" (+{len(prods) - 3} more)" if len(prods) > 3 else ""
            summary_parts.append(f"**{ptype.replace('_', ' ').title()}**: {names}{extra}")

        recs.append(Recommendation(
            priority=start_priority, category="product",
            title=f"{len(eligible)} Eligible Products Available",
            detail="\n".join(summary_parts),
            impact="medium",
        ))

    return recs


def _application_order(
    profile: CreditProfile,
    inquiries: list[Inquiry],
    apps: list[Application],
    products: list[FundingProduct],
    start_priority: int,
) -> list[Recommendation]:
    recs: list[Recommendation] = []
    eligible = _get_eligible_products(profile, inquiries, apps, products)
    if not eligible:
        return recs

    ordered = _order_for_round(eligible, inquiries)
    if not ordered:
        return recs

    lines = []
    for i, prod in enumerate(ordered[:MAX_APPS_PER_ROUND], 1):
        sensitive = " [INQUIRY SENSITIVE]" if prod.inquiry_sensitive else ""
        bureau = f"({prod.bureau_pulled})" if prod.bureau_pulled else ""
        limit = ""
        if prod.typical_limit_low and prod.typical_limit_high:
            limit = f" — ${prod.typical_limit_low:,.0f}-${prod.typical_limit_high:,.0f}"
        lines.append(f"{i}. {prod.lender} {prod.product_name} {bureau}{limit}{sensitive}")

    recs.append(Recommendation(
        priority=start_priority, category="action",
        title="Recommended Application Order",
        detail="Apply in this order (inquiry-sensitive first):\n" + "\n".join(lines),
        impact="high",
    ))

    return recs


def _derogatory_check(profile: CreditProfile, start_priority: int) -> list[Recommendation]:
    recs: list[Recommendation] = []
    derogs = (profile.derogatory_marks or 0) + (profile.collections or 0)

    if derogs > 0:
        recs.append(Recommendation(
            priority=start_priority, category="score_optimization",
            title=f"Address {derogs} Negative Mark(s)",
            detail="Derogatory marks and collections significantly reduce approval odds. "
                   "Consider disputing inaccurate items or negotiating pay-for-delete agreements "
                   "before applying for new credit.",
            impact="high",
        ))

    return recs


# ── Internal Helpers ─────────────────────────────────────────────────

def _get_eligible_products(
    profile: CreditProfile,
    inquiries: list[Inquiry],
    apps: list[Application],
    products: list[FundingProduct],
) -> list[FundingProduct]:
    """Filter products to those the user is eligible for and hasn't applied to."""
    already_applied = {
        (a.lender.lower(), (a.product_name or "").lower())
        for a in apps
        if a.status in ("applied", "pending", "approved")
    }

    eligible = []
    for prod in products:
        # Skip if already applied
        if (prod.lender.lower(), prod.product_name.lower()) in already_applied:
            continue

        # Check score requirement
        if prod.min_score and profile.score and profile.score < prod.min_score:
            continue

        # Check Chase 5/24
        if prod.inquiry_sensitive and prod.lender.lower() == "chase":
            new_accounts_24mo = sum(
                1 for a in apps
                if a.status == "approved"
                and a.applied_date
                and a.applied_date >= (datetime.utcnow() - timedelta(days=730)).strftime("%Y-%m-%d")
            )
            if new_accounts_24mo >= CHASE_524_LIMIT:
                continue

        eligible.append(prod)

    return eligible


def _order_for_round(products: list[FundingProduct], inquiries: list[Inquiry]) -> list[FundingProduct]:
    """Order products for optimal application sequence.

    Strategy:
    1. Inquiry-sensitive lenders first (Chase 5/24, etc.) — before new inquiries hit
    2. Within sensitive group: by recommended_order
    3. Same-bureau products together (potential combined pull)
    4. No-pull products last (no inquiry cost)
    """
    def sort_key(prod: FundingProduct):
        # Inquiry-sensitive first (lower = earlier)
        sensitive_rank = 0 if prod.inquiry_sensitive else 1

        # No-pull products last
        if prod.bureau_pulled and prod.bureau_pulled.lower() in ("none", "soft_pull"):
            sensitive_rank = 2

        order = prod.recommended_order or 99
        return (sensitive_rank, order, prod.lender)

    return sorted(products, key=sort_key)
