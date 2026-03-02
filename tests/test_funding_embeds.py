"""Tests for funding.embeds — Discord embed builders for the Business Funding Tracker."""

import discord
import pytest

from funding.embeds import (
    COLOR_APPROVED,
    COLOR_DENIED,
    COLOR_INQUIRY,
    COLOR_MILESTONE,
    COLOR_PENDING,
    COLOR_PROFILE,
    COLOR_STRATEGY,
    application_embed,
    inquiries_embed,
    milestone_embed,
    status_embed,
    strategy_embed,
)
from funding.models import Application, Inquiry, Recommendation


# ── Helpers ──────────────────────────────────────────────────────────


def _field_by_name(embed: discord.Embed, name: str):
    """Return the first embed field matching *name*, or None."""
    for f in embed.fields:
        if f.name == name:
            return f
    return None


def _field_names(embed: discord.Embed) -> list[str]:
    """Return all field names in the embed."""
    return [f.name for f in embed.fields]


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def base_summary():
    """Minimal status summary dict."""
    return {
        "total_funding_approved": 75000.0,
        "total_applications": 8,
        "approval_rate": 62.5,
        "approved": 5,
        "pending": 2,
        "denied": 1,
        "latest_score": 740,
        "latest_bureau": "experian",
        "inquiries_12mo": {"experian": 3, "transunion": 2},
    }


@pytest.fixture
def base_readiness():
    """Minimal readiness dict."""
    return {
        "score": 80,
        "factors": {
            "credit_score": "740 — Good",
            "utilization": "22% — Healthy",
            "inquiry_count": "5 in 12 mo — Moderate",
        },
    }


@pytest.fixture
def approved_app():
    return Application(
        product_type="credit_card",
        lender="Chase",
        product_name="Ink Business Preferred",
        amount_approved=25000.0,
        status="approved",
        bureau_pulled="experian",
        intro_apr=0.0,
        intro_period_months=12,
    )


@pytest.fixture
def denied_app():
    return Application(
        product_type="term_loan",
        lender="Bluevine",
        product_name="Business Line of Credit",
        amount_requested=50000.0,
        status="denied",
        bureau_pulled="transunion",
        denial_reason="Insufficient time in business",
    )


@pytest.fixture
def pending_app():
    return Application(
        product_type="loc",
        lender="Fundbox",
        product_name=None,
        amount_requested=30000.0,
        status="pending",
        bureau_pulled=None,
    )


@pytest.fixture
def credit_limit_app():
    """Approved app with credit_limit instead of amount_approved."""
    return Application(
        product_type="credit_card",
        lender="Amex",
        product_name="Blue Business Plus",
        credit_limit=15000.0,
        status="approved",
        bureau_pulled="experian",
        intro_apr=0.0,
        intro_period_months=15,
    )


@pytest.fixture
def sample_recommendations():
    return [
        Recommendation(
            priority=1,
            category="score_optimization",
            title="Pay down Chase card",
            detail="Reduce utilization below 10% for score boost.",
            impact="high",
        ),
        Recommendation(
            priority=2,
            category="inquiry_mgmt",
            title="Wait 30 days before next application",
            detail="Cool down period will reduce inquiry clustering.",
            impact="medium",
        ),
        Recommendation(
            priority=3,
            category="product",
            title="Consider secured card for thin file",
            detail="Low risk starter product to build history.",
            impact="low",
        ),
    ]


@pytest.fixture
def sample_inquiries():
    return [
        Inquiry(
            date="2026-01-15",
            bureau="experian",
            lender="Chase",
            falls_off_date="2028-01-15",
        ),
        Inquiry(
            date="2026-02-01",
            bureau="transunion",
            lender="Amex",
            falls_off_date="2028-02-01",
        ),
        Inquiry(
            date="2025-11-10",
            bureau="equifax",
            lender="Capital One",
            falls_off_date="2027-11-10",
        ),
    ]


# ── status_embed ─────────────────────────────────────────────────────


class TestStatusEmbed:
    def test_returns_discord_embed(self, base_summary, base_readiness):
        result = status_embed(base_summary, base_readiness)
        assert isinstance(result, discord.Embed)

    def test_title_and_color(self, base_summary, base_readiness):
        result = status_embed(base_summary, base_readiness)
        assert result.title == "Business Funding Dashboard"
        assert result.colour.value == COLOR_PROFILE

    def test_readiness_bar(self, base_summary, base_readiness):
        result = status_embed(base_summary, base_readiness)
        field = _field_by_name(result, "Readiness Score")
        assert field is not None
        # score=80 → 16 filled, 4 empty
        assert "80/100" in field.value
        assert "█" * 16 in field.value
        assert "░" * 4 in field.value
        assert field.inline is False

    def test_readiness_bar_zero(self, base_summary, base_readiness):
        base_readiness["score"] = 0
        result = status_embed(base_summary, base_readiness)
        field = _field_by_name(result, "Readiness Score")
        assert "0/100" in field.value
        assert "░" * 20 in field.value

    def test_readiness_bar_full(self, base_summary, base_readiness):
        base_readiness["score"] = 100
        result = status_embed(base_summary, base_readiness)
        field = _field_by_name(result, "Readiness Score")
        assert "100/100" in field.value
        assert "█" * 20 in field.value

    def test_funding_totals(self, base_summary, base_readiness):
        result = status_embed(base_summary, base_readiness)
        total = _field_by_name(result, "Total Funding")
        assert "$75,000" in total.value
        assert total.inline is True

        apps = _field_by_name(result, "Applications")
        assert apps.value == "8"

        rate = _field_by_name(result, "Approval Rate")
        assert "62%" in rate.value or "63%" in rate.value

    def test_status_breakdown(self, base_summary, base_readiness):
        result = status_embed(base_summary, base_readiness)
        field = _field_by_name(result, "Status Breakdown")
        assert "Approved: **5**" in field.value
        assert "Pending: **2**" in field.value
        assert "Denied: **1**" in field.value

    def test_credit_score_shown(self, base_summary, base_readiness):
        result = status_embed(base_summary, base_readiness)
        field = _field_by_name(result, "Credit Score")
        assert field is not None
        assert "740" in field.value
        assert "Experian" in field.value

    def test_credit_score_hidden_when_none(self, base_summary, base_readiness):
        base_summary["latest_score"] = None
        result = status_embed(base_summary, base_readiness)
        assert _field_by_name(result, "Credit Score") is None

    def test_inquiries_shown(self, base_summary, base_readiness):
        result = status_embed(base_summary, base_readiness)
        field = _field_by_name(result, "Inquiries (12 mo)")
        assert field is not None
        assert "Experian: **3**" in field.value
        assert "Transunion: **2**" in field.value

    def test_inquiries_hidden_when_none(self, base_summary, base_readiness):
        base_summary["inquiries_12mo"] = None
        result = status_embed(base_summary, base_readiness)
        assert _field_by_name(result, "Inquiries (12 mo)") is None

    def test_readiness_factors(self, base_summary, base_readiness):
        result = status_embed(base_summary, base_readiness)
        field = _field_by_name(result, "Readiness Factors")
        assert field is not None
        assert "Credit Score" in field.value
        assert "Utilization" in field.value
        assert field.inline is False

    def test_factors_max_six(self, base_summary, base_readiness):
        """Only first 6 factors are shown even if more are provided."""
        base_readiness["factors"] = {f"factor_{i}": f"detail {i}" for i in range(10)}
        result = status_embed(base_summary, base_readiness)
        field = _field_by_name(result, "Readiness Factors")
        # Should only contain 6 lines
        lines = [ln for ln in field.value.split("\n") if ln.strip()]
        assert len(lines) == 6

    def test_empty_factors(self, base_summary, base_readiness):
        base_readiness["factors"] = {}
        result = status_embed(base_summary, base_readiness)
        assert _field_by_name(result, "Readiness Factors") is None

    def test_footer(self, base_summary, base_readiness):
        result = status_embed(base_summary, base_readiness)
        assert result.footer.text == "Business Funding Tracker"


# ── strategy_embed ───────────────────────────────────────────────────


class TestStrategyEmbed:
    def test_returns_discord_embed(self, sample_recommendations):
        result = strategy_embed(sample_recommendations)
        assert isinstance(result, discord.Embed)

    def test_title_and_color(self, sample_recommendations):
        result = strategy_embed(sample_recommendations)
        assert result.title == "Funding Strategy Recommendations"
        assert result.colour.value == COLOR_STRATEGY

    def test_high_impact_icon(self, sample_recommendations):
        result = strategy_embed(sample_recommendations)
        field = result.fields[0]
        assert field.name.startswith("\U0001f534")  # red circle
        assert "Pay down Chase card" in field.name

    def test_medium_impact_icon(self, sample_recommendations):
        result = strategy_embed(sample_recommendations)
        field = result.fields[1]
        assert field.name.startswith("\U0001f7e1")  # yellow circle

    def test_low_impact_icon(self, sample_recommendations):
        result = strategy_embed(sample_recommendations)
        field = result.fields[2]
        assert field.name.startswith("\U0001f7e2")  # green circle

    def test_unknown_impact_icon(self):
        rec = Recommendation(
            priority=1, category="misc", title="Test",
            detail="Detail", impact="critical",
        )
        result = strategy_embed([rec])
        assert result.fields[0].name.startswith("\u2139")  # info icon

    def test_no_impact_uses_info_icon(self):
        rec = Recommendation(
            priority=1, category="misc", title="Test",
            detail="Detail", impact=None,
        )
        result = strategy_embed([rec])
        assert result.fields[0].name.startswith("\u2139")

    def test_detail_truncation_at_200(self):
        long_detail = "A" * 300
        rec = Recommendation(
            priority=1, category="test", title="Long rec",
            detail=long_detail, impact="high",
        )
        result = strategy_embed([rec])
        assert len(result.fields[0].value) == 200

    def test_max_eight_recs(self):
        recs = [
            Recommendation(
                priority=i, category="test", title=f"Rec {i}",
                detail=f"Detail {i}", impact="medium",
            )
            for i in range(12)
        ]
        result = strategy_embed(recs)
        assert len(result.fields) == 8

    def test_fields_not_inline(self, sample_recommendations):
        result = strategy_embed(sample_recommendations)
        for field in result.fields:
            assert field.inline is False

    def test_empty_recs(self):
        result = strategy_embed([])
        assert isinstance(result, discord.Embed)
        assert len(result.fields) == 0

    def test_footer(self, sample_recommendations):
        result = strategy_embed(sample_recommendations)
        assert result.footer.text == "Business Funding Tracker"


# ── application_embed ────────────────────────────────────────────────


class TestApplicationEmbed:
    def test_approved_color(self, approved_app):
        result = application_embed(approved_app)
        assert result.colour.value == COLOR_APPROVED

    def test_denied_color(self, denied_app):
        result = application_embed(denied_app)
        assert result.colour.value == COLOR_DENIED

    def test_pending_color(self, pending_app):
        result = application_embed(pending_app)
        assert result.colour.value == COLOR_PENDING

    def test_applied_color(self):
        app = Application(
            product_type="credit_card", lender="Discover",
            status="applied",
        )
        result = application_embed(app)
        assert result.colour.value == COLOR_PENDING

    def test_planned_color(self):
        app = Application(
            product_type="credit_card", lender="Discover",
            status="planned",
        )
        result = application_embed(app)
        assert result.colour.value == COLOR_PROFILE

    def test_unknown_status_defaults_profile_color(self):
        app = Application(
            product_type="credit_card", lender="Unknown",
            status="withdrawn",
        )
        result = application_embed(app)
        assert result.colour.value == COLOR_PROFILE

    def test_title_contains_lender_and_action(self, approved_app):
        result = application_embed(approved_app, action="approved")
        assert "Chase" in result.title
        assert "Approved" in result.title

    def test_title_default_action(self, approved_app):
        result = application_embed(approved_app)
        assert "Logged" in result.title

    def test_description_uses_product_name(self, approved_app):
        result = application_embed(approved_app)
        assert "Ink Business Preferred" in result.description

    def test_description_falls_back_to_product_type(self, pending_app):
        result = application_embed(pending_app)
        # product_name is None, should fall back to product_type
        assert "loc" in result.description.lower()

    def test_status_field_uppercased(self, approved_app):
        result = application_embed(approved_app)
        field = _field_by_name(result, "Status")
        assert field.value == "APPROVED"

    def test_type_field_formatted(self, approved_app):
        result = application_embed(approved_app)
        field = _field_by_name(result, "Type")
        assert field.value == "Credit Card"

    def test_bureau_field_shown(self, approved_app):
        result = application_embed(approved_app)
        field = _field_by_name(result, "Bureau")
        assert field is not None
        assert field.value == "Experian"

    def test_bureau_field_hidden_when_none(self, pending_app):
        result = application_embed(pending_app)
        assert _field_by_name(result, "Bureau") is None

    def test_approved_amount_shown(self, approved_app):
        result = application_embed(approved_app)
        field = _field_by_name(result, "Approved Amount")
        assert field is not None
        assert "$25,000" in field.value

    def test_credit_limit_shown_when_no_approved(self, credit_limit_app):
        result = application_embed(credit_limit_app)
        assert _field_by_name(result, "Approved Amount") is None
        field = _field_by_name(result, "Credit Limit")
        assert field is not None
        assert "$15,000" in field.value

    def test_requested_shown_when_no_approved_or_limit(self, denied_app):
        result = application_embed(denied_app)
        assert _field_by_name(result, "Approved Amount") is None
        assert _field_by_name(result, "Credit Limit") is None
        field = _field_by_name(result, "Requested")
        assert field is not None
        assert "$50,000" in field.value

    def test_no_amount_fields_when_all_none(self):
        app = Application(
            product_type="credit_card", lender="Test", status="planned",
        )
        result = application_embed(app)
        assert _field_by_name(result, "Approved Amount") is None
        assert _field_by_name(result, "Credit Limit") is None
        assert _field_by_name(result, "Requested") is None

    def test_intro_apr_zero_with_period(self, approved_app):
        result = application_embed(approved_app)
        field = _field_by_name(result, "Intro APR")
        assert field is not None
        assert "0%" in field.value
        assert "12 months" in field.value

    def test_intro_apr_zero_without_period(self):
        app = Application(
            product_type="credit_card", lender="Test",
            status="approved", intro_apr=0.0, intro_period_months=None,
        )
        result = application_embed(app)
        field = _field_by_name(result, "Intro APR")
        assert field is not None
        assert field.value == "0%"

    def test_intro_apr_nonzero_not_shown(self):
        app = Application(
            product_type="credit_card", lender="Test",
            status="approved", intro_apr=15.99,
        )
        result = application_embed(app)
        assert _field_by_name(result, "Intro APR") is None

    def test_intro_apr_none_not_shown(self):
        app = Application(
            product_type="credit_card", lender="Test",
            status="approved", intro_apr=None,
        )
        result = application_embed(app)
        assert _field_by_name(result, "Intro APR") is None

    def test_denial_reason_shown(self, denied_app):
        result = application_embed(denied_app)
        field = _field_by_name(result, "Denial Reason")
        assert field is not None
        assert "Insufficient time in business" in field.value
        assert field.inline is False

    def test_denial_reason_hidden_when_none(self, approved_app):
        result = application_embed(approved_app)
        assert _field_by_name(result, "Denial Reason") is None

    def test_status_emojis(self):
        emojis = {
            "approved": "\u2705",
            "denied": "\u274c",
            "pending": "\u23f3",
            "applied": "\U0001f4cb",
            "planned": "\U0001f4dd",
        }
        for status, emoji in emojis.items():
            app = Application(
                product_type="credit_card", lender="Test", status=status,
            )
            result = application_embed(app)
            assert result.title.startswith(emoji), (
                f"Status '{status}' should start with {emoji!r}"
            )

    def test_footer(self, approved_app):
        result = application_embed(approved_app)
        assert result.footer.text == "Business Funding Tracker"


# ── milestone_embed ──────────────────────────────────────────────────


class TestMilestoneEmbed:
    def test_returns_discord_embed(self, approved_app):
        result = milestone_embed(approved_app, total_funding=100000.0)
        assert isinstance(result, discord.Embed)

    def test_color(self, approved_app):
        result = milestone_embed(approved_app, total_funding=100000.0)
        assert result.colour.value == COLOR_MILESTONE

    def test_title_contains_lender_and_product(self, approved_app):
        result = milestone_embed(approved_app, total_funding=100000.0)
        assert "Chase" in result.title
        assert "Ink Business Preferred" in result.title
        assert "APPROVED" in result.title

    def test_title_falls_back_to_product_type(self):
        app = Application(
            product_type="term_loan", lender="Kabbage",
            product_name=None, status="approved",
        )
        result = milestone_embed(app, total_funding=50000.0)
        assert "term_loan" in result.title

    def test_amount_from_approved(self, approved_app):
        result = milestone_embed(approved_app, total_funding=100000.0)
        field = _field_by_name(result, "Amount")
        assert "$25,000" in field.value

    def test_amount_from_credit_limit(self, credit_limit_app):
        result = milestone_embed(credit_limit_app, total_funding=90000.0)
        field = _field_by_name(result, "Amount")
        assert "$15,000" in field.value

    def test_amount_zero_fallback(self):
        app = Application(
            product_type="credit_card", lender="Test", status="approved",
        )
        result = milestone_embed(app, total_funding=50000.0)
        field = _field_by_name(result, "Amount")
        assert "$0" in field.value

    def test_type_field(self, approved_app):
        result = milestone_embed(approved_app, total_funding=100000.0)
        field = _field_by_name(result, "Type")
        assert field.value == "Credit Card"

    def test_total_funding_field(self, approved_app):
        result = milestone_embed(approved_app, total_funding=125000.0)
        field = _field_by_name(result, "Total Funding")
        assert "$125,000" in field.value

    def test_intro_apr_zero_with_period(self, approved_app):
        result = milestone_embed(approved_app, total_funding=100000.0)
        field = _field_by_name(result, "Intro APR")
        assert field is not None
        assert "0%" in field.value
        assert "12 months" in field.value

    def test_intro_apr_nonzero_hidden(self):
        app = Application(
            product_type="credit_card", lender="Test",
            status="approved", intro_apr=5.99,
        )
        result = milestone_embed(app, total_funding=50000.0)
        assert _field_by_name(result, "Intro APR") is None

    def test_footer(self, approved_app):
        result = milestone_embed(approved_app, total_funding=100000.0)
        assert result.footer.text == "Business Funding Tracker"


# ── inquiries_embed ──────────────────────────────────────────────────


class TestInquiriesEmbed:
    def test_returns_discord_embed(self, sample_inquiries):
        counts_12 = {"experian": 3, "transunion": 2, "equifax": 1}
        counts_24 = {"experian": 5, "transunion": 3, "equifax": 2}
        result = inquiries_embed(sample_inquiries, counts_12, counts_24)
        assert isinstance(result, discord.Embed)

    def test_title_and_color(self, sample_inquiries):
        result = inquiries_embed(sample_inquiries, {}, {})
        assert result.title == "Hard Inquiry Breakdown"
        assert result.colour.value == COLOR_INQUIRY

    def test_bureau_bars(self, sample_inquiries):
        counts_12 = {"experian": 3, "transunion": 2, "equifax": 1}
        counts_24 = {"experian": 5, "transunion": 3, "equifax": 2}
        result = inquiries_embed(sample_inquiries, counts_12, counts_24)
        field = _field_by_name(result, "By Bureau")
        assert field is not None
        assert "Experian" in field.value
        assert "Transunion" in field.value
        assert "Equifax" in field.value
        # Experian: 3 filled, 7 empty
        assert "███░░░░░░░" in field.value

    def test_bureau_bar_caps_at_10(self, sample_inquiries):
        counts_12 = {"experian": 15, "transunion": 0, "equifax": 0}
        counts_24 = {"experian": 15, "transunion": 0, "equifax": 0}
        result = inquiries_embed(sample_inquiries, counts_12, counts_24)
        field = _field_by_name(result, "By Bureau")
        # min(15, 10) = 10 filled, 0 empty
        assert "██████████" in field.value

    def test_totals_line(self, sample_inquiries):
        counts_12 = {"experian": 3, "transunion": 2, "equifax": 1}
        counts_24 = {"experian": 5, "transunion": 3, "equifax": 2}
        result = inquiries_embed(sample_inquiries, counts_12, counts_24)
        field = _field_by_name(result, "By Bureau")
        assert "**Total**: 6 (12 mo) / 10 (24 mo)" in field.value

    def test_empty_counts(self, sample_inquiries):
        result = inquiries_embed(sample_inquiries, {}, {})
        field = _field_by_name(result, "By Bureau")
        assert "**Total**: 0 (12 mo) / 0 (24 mo)" in field.value

    def test_recent_inquiries_shown(self, sample_inquiries):
        result = inquiries_embed(sample_inquiries, {}, {})
        field = _field_by_name(result, "Recent Inquiries")
        assert field is not None
        assert "Chase" in field.value
        assert "Amex" in field.value
        assert "Capital One" in field.value
        assert "Experian" in field.value

    def test_recent_inquiries_max_eight(self):
        inqs = [
            Inquiry(date=f"2026-01-{i+1:02d}", bureau="experian", lender=f"Lender{i}")
            for i in range(12)
        ]
        result = inquiries_embed(inqs, {}, {})
        field = _field_by_name(result, "Recent Inquiries")
        lines = [ln for ln in field.value.split("\n") if ln.strip()]
        assert len(lines) == 8

    def test_no_recent_inquiries(self):
        result = inquiries_embed([], {}, {})
        assert _field_by_name(result, "Recent Inquiries") is None

    def test_fall_off_timeline(self, sample_inquiries):
        result = inquiries_embed(sample_inquiries, {}, {})
        field = _field_by_name(result, "Next Fall-Off Dates")
        assert field is not None
        # Sorted by date: 2027-11-10, 2028-01-15, 2028-02-01
        lines = [ln for ln in field.value.split("\n") if ln.strip()]
        assert len(lines) == 3
        assert "Capital One" in lines[0]  # earliest fall-off
        assert "Chase" in lines[1]
        assert "Amex" in lines[2]

    def test_fall_off_max_five(self):
        inqs = [
            Inquiry(
                date=f"2026-01-{i+1:02d}", bureau="experian",
                lender=f"Lender{i}", falls_off_date=f"2028-01-{i+1:02d}",
            )
            for i in range(10)
        ]
        result = inquiries_embed(inqs, {}, {})
        field = _field_by_name(result, "Next Fall-Off Dates")
        lines = [ln for ln in field.value.split("\n") if ln.strip()]
        assert len(lines) == 5

    def test_no_fall_off_when_no_dates(self):
        inqs = [
            Inquiry(date="2026-01-15", bureau="experian", lender="Chase"),
        ]
        result = inquiries_embed(inqs, {}, {})
        assert _field_by_name(result, "Next Fall-Off Dates") is None

    def test_footer(self, sample_inquiries):
        result = inquiries_embed(sample_inquiries, {}, {})
        assert result.footer.text == "Business Funding Tracker"
