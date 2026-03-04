"""Teaching narration script generator for KJ strategy setups."""

from __future__ import annotations

import os

import pandas as pd

from kj_strategy.setup import KJSetup

NARRATION_DIR = "reports/kj_narrations"


def generate_narration(setup: KJSetup, df: pd.DataFrame) -> str:
    """Generate a teaching narration script explaining the setup like a trading mentor."""

    inst = setup.instrument
    direction = setup.trend_direction
    fib_level = setup.active_fib_level
    pattern = setup.patterns[0] if setup.patterns else None
    pattern_name = pattern.pattern_type.replace("_", " ").title() if pattern else "confirmation"

    # Compute swing details
    swing_start = setup.swing_low if direction == "bullish" else setup.swing_high
    swing_end = setup.swing_high if direction == "bullish" else setup.swing_low
    move_pts = abs(swing_end.price - swing_start.price)
    move_pct = move_pts / swing_start.price * 100
    swing_bars = abs(swing_end.index - swing_start.index)
    swing_duration = _format_duration(swing_bars * 5)  # 5-min bars

    # Pullback details
    pullback_pts = abs(setup.entry_price - swing_end.price)
    pullback_pct = pullback_pts / move_pts * 100 if move_pts > 0 else 0

    # Outcome details
    if setup.outcome == "win":
        outcome_desc = f"ran to the take profit target at {setup.take_profit:.2f}"
        outcome_detail = (
            f"That's a {setup.actual_rr:.1f}R winner. "
            f"It took {setup.bars_to_exit} bars ({_format_duration(setup.bars_to_exit * 5)}) to reach target."
        )
    elif setup.outcome == "loss":
        outcome_desc = f"hit the stop loss at {setup.stop_loss:.2f}"
        outcome_detail = (
            f"That's a -1R loss after {setup.bars_to_exit} bars. "
            f"The setup was valid — sometimes good setups lose. That's trading."
        )
    else:
        outcome_desc = f"timed out at {setup.exit_price:.2f}"
        rr_str = f"{setup.actual_rr:+.1f}R" if setup.actual_rr else "flat"
        outcome_detail = f"It ended at {rr_str} after running out of bars. The trade was still working."

    # Classification reasoning
    if setup.classification == "textbook":
        class_reason = (
            f"It scored {setup.textbook_score:.0f}/100 — clean trend, precise Fib touch, "
            f"clear {pattern_name} confirmation, and a {setup.reward_risk_ratio:.1f}:1 reward-to-risk. "
            f"This is the kind of setup you screenshot and study."
        )
    else:
        class_reason = (
            f"It scored {setup.textbook_score:.0f}/100. The setup had the right ingredients "
            f"but wasn't perfect — maybe the pullback was messy, or the pattern wasn't as clean. "
            f"Not every setup will be textbook. The key is the process, not perfection."
        )

    script = f"""=== KJ STRATEGY SETUP: {inst} | {setup.entry_timestamp.strftime('%m/%d/%Y %H:%M') if setup.entry_timestamp else 'N/A'} | {setup.classification.upper()} ===

CONTEXT:
"{inst} was in a {direction} trend, with price running from {swing_start.price:,.2f} to \
{swing_end.price:,.2f} — a {move_pct:.1f}% move ({move_pts:,.2f} points) over {swing_bars} bars \
({swing_duration}). That's the move we're working with."

THE PULLBACK:
"After the swing completed, price began pulling back. This is where most traders make \
their mistake — they chase the move that already happened. In the KJ strategy, we don't \
chase. We let price come to us. We wait for the correction."

FIBONACCI SETUP:
"Drawing our Fibonacci from the swing {'low' if direction == 'bullish' else 'high'} at \
{swing_start.price:,.2f} to the swing {'high' if direction == 'bullish' else 'low'} at \
{swing_end.price:,.2f}, here are the key levels:
  - 38.2% at {setup.fib_levels.levels['38.2']:,.2f}
  - 50.0% at {setup.fib_levels.levels['50.0']:,.2f}
  - 61.8% at {setup.fib_levels.levels['61.8']:,.2f}
Price pulled back {pullback_pct:.0f}% into the {fib_level}% zone. This is a \
high-probability area where price likes to reject."

CONFIRMATION:
"Here's where it gets interesting. At the {fib_level}% Fib level, we see a \
{pattern_name}. {pattern.description if pattern else 'Price showed clear rejection from the level.'}. \
That's our confirmation — that's the green light to enter."

THE TRADE:
"Entry at {setup.entry_price:,.2f}. Stop loss right below the pattern at \
{setup.stop_loss:,.2f} — that's {setup.risk_points:,.2f} points of risk. Target at \
{setup.take_profit:,.2f} gives us {setup.reward_points:,.2f} points of reward. \
Risk-to-reward: 1 to {setup.reward_risk_ratio:.1f}. So I could lose \
{int(setup.reward_risk_ratio)} times in a row, but if I win once, I make it all back and then some."

CLASSIFICATION:
"This is a {setup.classification} setup. {class_reason}"

OUTCOME:
"Price {outcome_desc}. {outcome_detail}"

=== END ===
"""
    setup.narration = script
    return script


def save_narration(setup: KJSetup, output_dir: str = NARRATION_DIR) -> str:
    """Save narration to a text file. Returns file path."""
    os.makedirs(output_dir, exist_ok=True)
    date_str = setup.entry_timestamp.strftime("%Y%m%d_%H%M") if setup.entry_timestamp else "unknown"
    filename = f"{setup.instrument}_{setup.setup_id}_{date_str}.txt"
    path = os.path.join(output_dir, filename)
    with open(path, "w") as f:
        f.write(setup.narration or "No narration generated.")
    return path


def _format_duration(minutes: int) -> str:
    """Format minutes into human-readable duration."""
    if minutes < 60:
        return f"{minutes}min"
    hours = minutes // 60
    mins = minutes % 60
    if hours < 24:
        return f"{hours}h {mins}min" if mins else f"{hours}h"
    days = hours // 24
    hours = hours % 24
    return f"{days}d {hours}h"
