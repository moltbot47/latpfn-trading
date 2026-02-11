"""
Strategy theory and psychology explanations for each shot tier.

Used in Discord radar embeds to educate users on the reasoning
behind each trade scenario as it builds toward a trigger.
"""

# GitHub wiki URL for full strategy deep-dives
WIKI_BASE = "https://github.com/moltbot47/latpfn-trading/wiki"

# ── Per-tier strategy explanations ────────────────────────────────────

TIER_THEORY = {
    "layup": {
        "label": "Layup",
        "emoji": "\U0001F3C0",
        "theory": (
            "**High-probability, tight-target trade.** The model sees strong "
            "directional conviction with low uncertainty. Like a layup in basketball "
            "— you're right under the basket."
        ),
        "psychology": (
            "Discipline is key: take the easy points and don't get greedy. "
            "These trades win on *frequency*, not magnitude. "
            "Resist the urge to widen the target — trust the edge."
        ),
        "wiki_slug": "Strategy-Layup",
    },
    "short_range": {
        "label": "Short Range",
        "emoji": "\U0001F3AF",
        "theory": (
            "**Solid setup with moderate target.** The forecast is clearly "
            "directional but not at peak conviction. Like a mid-range jumper "
            "— good position, reliable execution."
        ),
        "psychology": (
            "Patience over impulse: wait for the model to confirm direction "
            "with tightening uncertainty. These trades balance frequency and "
            "payoff — the bread and butter of consistent returns."
        ),
        "wiki_slug": "Strategy-Short-Range",
    },
    "free_throw": {
        "label": "Free Throw",
        "emoji": "\U0001F945",
        "theory": (
            "**Moderate conviction, reduced size.** The signal shows direction "
            "but uncertainty is wider. Position size scales down to 75% to "
            "manage risk while maintaining exposure to the expected move."
        ),
        "psychology": (
            "Emotional control matters most here. The temptation is to size up "
            "because 'it looks right.' The reduced size is a feature, not a bug "
            "— it keeps you in the game through inevitable losing streaks."
        ),
        "wiki_slug": "Strategy-Free-Throw",
    },
    "three_pointer": {
        "label": "3-Pointer",
        "emoji": "\U0001F525",
        "theory": (
            "**Lower probability, higher payoff.** The model sees a directional "
            "bias but with significant uncertainty. Wider stops and targets "
            "at half position size — the math requires a bigger move to compensate "
            "for lower win rate."
        ),
        "psychology": (
            "This is where most traders fail: they either avoid these entirely "
            "(missing big moves) or over-size them (devastating losses). "
            "Half-size discipline lets you take the shot without risking the game."
        ),
        "wiki_slug": "Strategy-Three-Pointer",
    },
    "half_court": {
        "label": "Half Court",
        "emoji": "\U0001F680",
        "theory": (
            "**Low probability, large payoff potential.** The model detects "
            "a possible breakout or trend acceleration, but conviction is low. "
            "Quarter-size position with very wide targets — designed to catch "
            "rare large moves."
        ),
        "psychology": (
            "Accept that most of these will lose. The math works because one "
            "winner covers 4-5 losers. This is portfolio insurance — small bets "
            "on tail events that pay disproportionately when they hit."
        ),
        "wiki_slug": "Strategy-Half-Court",
    },
    "hail_mary": {
        "label": "Hail Mary",
        "emoji": "\U0001F4A5",
        "theory": (
            "**Minimum conviction, maximum target.** The model shows the faintest "
            "directional signal. Minimum position size with extreme targets "
            "— a pure lottery ticket that exploits fat-tailed distributions "
            "in financial returns."
        ),
        "psychology": (
            "The key is emotional detachment. Size so small that a loss is "
            "meaningless, but a win is memorable. Never move the target closer "
            "or add to the position. Set it and forget it."
        ),
        "wiki_slug": "Strategy-Hail-Mary",
    },
}

# ── General strategy concepts ─────────────────────────────────────────

GENERAL_CONCEPTS = {
    "expected_value": {
        "title": "Expected Value (EV)",
        "explanation": (
            "Every tier is designed to be EV-positive: `EV = (win_rate x avg_win) "
            "- (loss_rate x avg_loss)`. Higher tiers win more often with smaller "
            "gains; lower tiers win less often with larger gains. Both can be "
            "profitable if the math is right."
        ),
    },
    "position_sizing": {
        "title": "Position Sizing & Risk Management",
        "explanation": (
            "Position size scales inversely with tier risk. This is not timidity "
            "— it's survival math. On a prop firm with $2,500 drawdown, losing "
            "3 full-size bets in a row ends the evaluation. Scaling down on lower-"
            "conviction trades extends your runway while keeping you exposed to upside."
        ),
    },
    "regime_awareness": {
        "title": "Regime Awareness",
        "explanation": (
            "Markets alternate between trending (momentum works), ranging "
            "(mean-reversion works), and volatile (nothing works reliably). "
            "The system adjusts confidence and sizing based on detected regime "
            "to avoid trading strategies that conflict with current conditions."
        ),
    },
    "zero_shot_forecasting": {
        "title": "Zero-Shot Forecasting (LaT-PFN)",
        "explanation": (
            "Unlike traditional models trained on historical market data, LaT-PFN "
            "was trained on millions of *synthetic* time series. It learns general "
            "patterns (trends, cycles, mean-reversion) without overfitting to "
            "past market behavior. This makes it robust to regime changes that "
            "break historically-fitted models."
        ),
    },
}


def get_tier_explainer(tier_name: str) -> dict | None:
    """Get theory/psychology for a specific tier."""
    return TIER_THEORY.get(tier_name)


def get_tier_wiki_url(tier_name: str) -> str:
    """Get the full wiki URL for a tier's strategy page."""
    tier = TIER_THEORY.get(tier_name)
    if tier:
        return f"{WIKI_BASE}/{tier['wiki_slug']}"
    return f"{WIKI_BASE}/Strategy-Overview"
