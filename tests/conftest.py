"""
Shared fixtures for latpfn-trading unit tests.

Provides a mock config dict that mirrors the structure in config/settings.yaml
but uses test-friendly values (small numbers, predictable thresholds).
"""

import pytest
import sys
from pathlib import Path

# Ensure project root is on sys.path so `funding` and `scripts` are importable
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from funding.database import FundingDB
from funding.models import (
    Application, CreditProfile, Inquiry, PartnerProgram,
    Referral, ReferralClient, StrategyRound,
)
from funding.product_catalog import seed_catalog, seed_partner_programs


# ── Funding Tracker Fixtures ────────────────────────────────────────


@pytest.fixture
def funding_db(tmp_path):
    """Fresh FundingDB on a temp file — tables created, no seed data."""
    return FundingDB(str(tmp_path / "test.db"))


@pytest.fixture
def seeded_db(funding_db):
    """FundingDB with product catalog + partner programs seeded."""
    seed_catalog(funding_db)
    seed_partner_programs(funding_db)
    return funding_db


@pytest.fixture
def sample_profile():
    """CreditProfile with realistic mid-tier data (720 Experian)."""
    return CreditProfile(
        bureau="experian",
        score=720,
        total_accounts=12,
        open_accounts=8,
        closed_accounts=4,
        hard_inquiries_count=3,
        utilization_pct=22.0,
        payment_history_pct=98.0,
        derogatory_marks=0,
        collections=0,
        avg_age_years=4.5,
        oldest_account_years=9.0,
        total_credit_limit=50000.0,
        total_balance=11000.0,
        new_accounts_6mo=1,
        revolving_balance=8000.0,
        installment_balance=3000.0,
    )


@pytest.fixture
def sample_application():
    """Application in 'planned' status for Chase Ink Preferred."""
    return Application(
        product_type="credit_card",
        lender="Chase",
        product_name="Ink Business Preferred",
        amount_requested=10000.0,
        status="planned",
        bureau_pulled="experian",
        personal_guarantee=True,
    )


@pytest.fixture
def flask_client(tmp_path):
    """Flask test client backed by a seeded temp DB."""
    import scripts.funding_dashboard as dashboard_mod

    test_db = FundingDB(str(tmp_path / "flask_test.db"))
    seed_catalog(test_db)
    seed_partner_programs(test_db)

    # Patch the module-level db used by all endpoints
    original_db = dashboard_mod.db
    dashboard_mod.db = test_db

    dashboard_mod.app.config["TESTING"] = True
    client = dashboard_mod.app.test_client()
    yield client

    dashboard_mod.db = original_db


@pytest.fixture
def mock_config() -> dict:
    """
    Minimal config dict matching the shape expected by all modules under test.

    Values are chosen for easy mental arithmetic in assertions:
      - Account equity: $50,000
      - Max risk per trade: 2% ($1,000)
      - Daily loss cap: 3% or $1,000 USD
      - Max drawdown: 10% or $2,500 USD
      - Max concurrent positions: 3
    """
    return {
        "risk": {
            "max_risk_per_trade_pct": 2.0,
            "max_position_size_contracts": 5,
            "max_daily_loss_pct": 3.0,       # 3% of starting equity
            "max_drawdown_pct": 10.0,         # 10% from peak
            "max_concurrent_positions": 3,
            "stop_loss_atr_multiplier": 1.5,
            "min_reward_risk_ratio": 1.5,
            "trailing_stop_activation_pct": 2.0,
            "trailing_stop_distance_pct": 1.0,
            "prop_firm": {
                "starting_balance": 50000,
                "max_daily_loss_usd": 1000,
                "max_total_drawdown_usd": 2500,
                "profit_target_usd": 3000,
                "flatten_eod": True,
                "flatten_time": "16:55",
                "no_new_trades_after": "16:45",
                "max_risk_reward_ratio": 5.0,
                "mae_pct": 0.30,
                "consistency_pct": 0.30,
            },
        },
        "signal": {
            "min_confidence": 0.25,
            "regime_multipliers": {
                "trending": 1.15,
                "ranging": 0.95,
                "volatile": 0.75,
            },
            "weights": {
                "model_confidence": 0.4,
                "trend_clarity": 0.3,
                "uncertainty_inverse": 0.3,
            },
        },
        "shot_tiers": {
            "layup": {
                "label": "Layup",
                "confidence_min": 0.60,
                "target_multiplier": 0.4,
                "stop_multiplier": 0.8,
                "size_multiplier": 1.0,
                "min_reward_risk": 1.0,
                "enabled": True,
            },
            "short_range": {
                "label": "Short Range",
                "confidence_min": 0.52,
                "target_multiplier": 0.6,
                "stop_multiplier": 0.9,
                "size_multiplier": 1.0,
                "min_reward_risk": 1.2,
                "enabled": True,
            },
            "free_throw": {
                "label": "Free Throw",
                "confidence_min": 0.45,
                "target_multiplier": 0.8,
                "stop_multiplier": 1.0,
                "size_multiplier": 0.75,
                "min_reward_risk": 1.5,
                "enabled": True,
            },
            "three_pointer": {
                "label": "3-Pointer",
                "confidence_min": 0.38,
                "target_multiplier": 1.2,
                "stop_multiplier": 1.2,
                "size_multiplier": 0.5,
                "min_reward_risk": 2.0,
                "enabled": True,
            },
            "half_court": {
                "label": "Half Court",
                "confidence_min": 0.32,
                "target_multiplier": 2.0,
                "stop_multiplier": 1.5,
                "size_multiplier": 0.25,
                "min_reward_risk": 3.0,
                "enabled": False,
            },
            "hail_mary": {
                "label": "Hail Mary",
                "confidence_min": 0.25,
                "target_multiplier": 3.5,
                "stop_multiplier": 1.5,
                "size_multiplier": 0.15,
                "min_reward_risk": 5.0,
                "enabled": False,
            },
        },
        "execution": {
            "mode": "dry_run",
            "default_equity": 50000,
        },
    }


@pytest.fixture
def signal_config(mock_config) -> dict:
    """Shortcut to the signal sub-config."""
    return mock_config["signal"]


@pytest.fixture
def tiers_config(mock_config) -> dict:
    """Shortcut to the shot_tiers sub-config."""
    return mock_config["shot_tiers"]
