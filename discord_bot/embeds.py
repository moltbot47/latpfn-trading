"""
Discord embed builders for trading signals, status, and forecasts.
"""

import discord
from datetime import datetime, timezone
from signals.strategy_explainer import get_tier_explainer, get_tier_wiki_url


# Shot tier colors (Discord embed hex)
TIER_COLORS = {
    "layup": 0x00FF00,        # bright green
    "short_range": 0x7CFC00,  # lawn green
    "free_throw": 0xFFD700,   # gold
    "three_pointer": 0xFF8C00, # dark orange
    "half_court": 0xFF4500,   # orange red
    "hail_mary": 0xFF0000,    # red
    "no_trade": 0x808080,     # gray
}

DIRECTION_COLORS = {
    "long": 0x00CC00,
    "short": 0xCC0000,
    "neutral": 0x808080,
}


def signal_embed(
    instrument: str, signal, prediction: dict, contract_size: float = 0
) -> discord.Embed:
    """Build a rich embed for a trading signal."""
    dir_emoji = "\U0001F7E2" if signal.direction == "long" else "\U0001F534"
    tier_label = signal.shot_type.replace("_", " ").title()
    color = TIER_COLORS.get(signal.shot_type, 0x808080)

    embed = discord.Embed(
        title=f"{dir_emoji} {instrument} {signal.direction.upper()} Signal",
        description=f"**{tier_label}** — Confidence: {signal.confidence:.1%}",
        color=color,
        timestamp=datetime.now(timezone.utc),
    )

    # Win probability (model confidence estimate — not guaranteed)
    win_pct = signal.confidence * 100
    if win_pct >= 60:
        prob_emoji = "\U0001F525"  # fire
    elif win_pct >= 45:
        prob_emoji = "\U0001F4CA"  # chart
    else:
        prob_emoji = "\u26A0\uFE0F"  # warning
    embed.add_field(
        name=f"{prob_emoji} Win Probability",
        value=f"**{win_pct:.1f}%**\n*model estimate*",
        inline=True,
    )

    embed.add_field(name="Entry", value=f"${signal.entry_price:,.2f}", inline=True)
    embed.add_field(name="Stop Loss", value=f"${signal.stop_loss:,.2f}", inline=True)
    embed.add_field(name="Take Profit", value=f"${signal.take_profit:,.2f}", inline=True)
    embed.add_field(name="Contracts", value=str(signal.position_size), inline=True)
    embed.add_field(name="Regime", value=signal.regime.title(), inline=True)

    # Risk/reward in points and dollars
    risk_pts = abs(signal.entry_price - signal.stop_loss)
    reward_pts = abs(signal.take_profit - signal.entry_price)
    rr = reward_pts / risk_pts if risk_pts > 0 else 0
    embed.add_field(name="R:R", value=f"{rr:.1f}:1", inline=True)

    qty = signal.position_size
    cs = contract_size if contract_size > 0 else 1
    risk_usd = risk_pts * cs * qty
    reward_usd = reward_pts * cs * qty

    embed.add_field(
        name="\U0001F6E1 Risk",
        value=f"**${risk_usd:,.2f}**\n{risk_pts:,.2f} pts \u00d7 {qty} ct",
        inline=True,
    )
    embed.add_field(
        name="\U0001F3AF Reward",
        value=f"**${reward_usd:,.2f}**\n{reward_pts:,.2f} pts \u00d7 {qty} ct",
        inline=True,
    )
    embed.add_field(
        name="\U0001F4B0 Per Contract",
        value=f"Risk: ${risk_pts * cs:,.2f}\nReward: ${reward_pts * cs:,.2f}",
        inline=True,
    )

    # Strategy psychology for this tier
    explainer = get_tier_explainer(signal.shot_type)
    if explainer:
        wiki_url = get_tier_wiki_url(signal.shot_type)
        embed.add_field(
            name=f"{explainer['emoji']} Strategy Psychology",
            value=(
                f"*{explainer['psychology']}*\n"
                f"[\U0001F4D6 Full Strategy Guide]({wiki_url})"
            ),
            inline=False,
        )

    embed.set_footer(text="LaT-PFN Trading System")
    return embed


def execution_embed(
    instrument: str, result: dict, signal, contract_size: float = 0
) -> discord.Embed:
    """Build embed for order execution result."""
    if result and "orderId" in result:
        embed = discord.Embed(
            title=f"Order Placed: {instrument}",
            description=f"{signal.direction.upper()} {signal.position_size} contracts via PickMyTrade",
            color=0x00CC00,
            timestamp=datetime.now(timezone.utc),
        )
        # Win probability
        win_pct = signal.confidence * 100
        if win_pct >= 60:
            prob_emoji = "\U0001F525"
        elif win_pct >= 45:
            prob_emoji = "\U0001F4CA"
        else:
            prob_emoji = "\u26A0\uFE0F"

        embed.add_field(name="Order ID", value=str(result["orderId"]), inline=True)
        embed.add_field(name="Entry", value=f"${signal.entry_price:,.2f}", inline=True)
        embed.add_field(
            name=f"{prob_emoji} Win Prob",
            value=f"**{win_pct:.1f}%** *(est.)*",
            inline=True,
        )
        embed.add_field(name="SL / TP", value=f"${signal.stop_loss:,.2f} / ${signal.take_profit:,.2f}", inline=True)

        # Risk/reward breakdown
        risk_pts = abs(signal.entry_price - signal.stop_loss)
        reward_pts = abs(signal.take_profit - signal.entry_price)
        rr = reward_pts / risk_pts if risk_pts > 0 else 0
        qty = signal.position_size
        cs = contract_size if contract_size > 0 else 1
        risk_usd = risk_pts * cs * qty
        reward_usd = reward_pts * cs * qty

        embed.add_field(
            name="\U0001F6E1 Risk",
            value=f"**${risk_usd:,.2f}** ({risk_pts:,.2f} pts)",
            inline=True,
        )
        embed.add_field(
            name="\U0001F3AF Reward",
            value=f"**${reward_usd:,.2f}** ({reward_pts:,.2f} pts)",
            inline=True,
        )
        embed.add_field(name="R:R", value=f"{rr:.1f}:1", inline=True)
    else:
        embed = discord.Embed(
            title=f"Order Failed: {instrument}",
            description="Webhook did not return a valid order ID",
            color=0xCC0000,
            timestamp=datetime.now(timezone.utc),
        )
    embed.set_footer(text="LaT-PFN Trading System")
    return embed


def risk_rejected_embed(instrument: str, reason: str) -> discord.Embed:
    """Build embed for a risk-rejected signal."""
    embed = discord.Embed(
        title=f"Signal Rejected: {instrument}",
        description=reason,
        color=0xFF8C00,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text="Risk Manager")
    return embed


def cycle_summary_embed(
    cycle: int,
    predictions: dict,
    positions: dict,
    account_equity: float,
    daily_pnl: float,
    drawdown_status: dict | None = None,
) -> discord.Embed:
    """Build embed for end-of-cycle summary."""
    pnl_emoji = "\U0001F7E2" if daily_pnl >= 0 else "\U0001F534"
    embed = discord.Embed(
        title=f"Cycle {cycle} Summary",
        color=0x3498DB,
        timestamp=datetime.now(timezone.utc),
    )

    # Predictions summary — compact format for many pairs
    signal_lines = []
    other_lines = []
    for inst, pred in predictions.items():
        if pred is None:
            continue
        direction = pred["direction"].upper()
        conf = pred["confidence"]
        shot = pred.get("shot_type", "")
        emoji = {"LONG": "\U0001F7E2", "SHORT": "\U0001F534"}.get(direction, "\u26AA")

        if shot and shot != "no_trade":
            shot_label = f" [{shot.replace('_', ' ').title()}]"
            signal_lines.append(f"{emoji} **{inst}**: {direction} ({conf:.1%}){shot_label}")
        elif conf >= 0.30:
            other_lines.append(f"{emoji} {inst} {direction} {conf:.0%}")

    if signal_lines:
        embed.add_field(
            name="Signals Generated",
            value="\n".join(signal_lines),
            inline=False,
        )

    # Show top near-threshold pairs compactly (max 10)
    if other_lines:
        shown = other_lines[:10]
        remaining = len(other_lines) - len(shown)
        compact = " | ".join(shown)
        if remaining > 0:
            compact += f" +{remaining} more"
        embed.add_field(
            name=f"Near Threshold ({len(predictions)} pairs scanned)",
            value=compact,
            inline=False,
        )
    elif not signal_lines:
        embed.add_field(
            name=f"Predictions ({len(predictions)} pairs scanned)",
            value="No signals above threshold",
            inline=False,
        )

    # Account
    embed.add_field(name="Equity", value=f"${account_equity:,.2f}", inline=True)
    embed.add_field(name="Daily P&L", value=f"{pnl_emoji} ${daily_pnl:+,.2f}", inline=True)
    embed.add_field(name="Open Positions", value=str(len(positions)), inline=True)

    # Drawdown status
    if drawdown_status:
        dd = drawdown_status
        lock_label = " (LOCKED)" if dd.get("floor_locked") else ""
        cushion_bar_len = 10
        cushion_filled = min(int(dd.get("cushion_pct", 100) / 10), cushion_bar_len)
        cushion_bar = "\U0001F7E9" * cushion_filled + "\U0001F7E5" * (cushion_bar_len - cushion_filled)
        dd_text = (
            f"Floor: **${dd['drawdown_floor']:,.2f}**{lock_label}\n"
            f"Cushion: ${dd['cushion']:,.2f} ({dd.get('cushion_pct', 100):.0f}%)\n"
            f"{cushion_bar}"
        )
        # Only show profit target for prop firm accounts
        if dd.get("profit_to_target") and dd.get("profit_target_balance"):
            dd_text += f"\nTo target (${dd['profit_target_balance']:,.0f}): **${dd['profit_to_target']:,.2f}**"
        embed.add_field(name="Risk Status", value=dd_text, inline=False)

    embed.set_footer(text="LaT-PFN Trading System")
    return embed


def status_embed(
    is_running: bool,
    cycle: int,
    instruments: list,
    account_equity: float,
    positions: dict,
    daily_pnl: float,
    exec_mode: str,
) -> discord.Embed:
    """Build embed for /status command."""
    status_text = "\U0001F7E2 Running" if is_running else "\U0001F534 Stopped"
    embed = discord.Embed(
        title="Trading System Status",
        description=status_text,
        color=0x00CC00 if is_running else 0xCC0000,
        timestamp=datetime.now(timezone.utc),
    )

    embed.add_field(name="Cycle", value=str(cycle), inline=True)
    embed.add_field(name="Execution", value=exec_mode, inline=True)
    embed.add_field(name="Instruments", value=", ".join(instruments), inline=True)
    embed.add_field(name="Equity", value=f"${account_equity:,.2f}", inline=True)
    embed.add_field(name="Daily P&L", value=f"${daily_pnl:+,.2f}", inline=True)
    embed.add_field(name="Positions", value=str(len(positions)), inline=True)

    # List open positions if any
    if positions:
        pos_lines = []
        for inst, pos in positions.items():
            pos_lines.append(
                f"**{inst}** {pos.direction.upper()} {pos.size} @ ${pos.entry_price:,.2f}"
            )
        embed.add_field(name="Open Positions", value="\n".join(pos_lines), inline=False)

    embed.set_footer(text="LaT-PFN Trading System")
    return embed


def forecast_embed(instrument: str, prediction: dict) -> discord.Embed:
    """Build embed for on-demand forecast."""
    direction = prediction["direction"]
    dir_emoji = {
        "long": "\U0001F7E2",
        "short": "\U0001F534",
        "neutral": "\u26AA",
    }.get(direction, "\u26AA")
    color = DIRECTION_COLORS.get(direction, 0x808080)

    embed = discord.Embed(
        title=f"{dir_emoji} {instrument} Forecast",
        color=color,
        timestamp=datetime.now(timezone.utc),
    )

    embed.add_field(name="Direction", value=direction.upper(), inline=True)
    embed.add_field(name="Confidence", value=f"{prediction['confidence']:.1%}", inline=True)
    embed.add_field(name="Regime", value=prediction["regime"].title(), inline=True)
    embed.add_field(
        name="Current Price",
        value=f"${prediction['current_price']:,.2f}",
        inline=True,
    )

    forecast = prediction["forecast_prices"]
    if len(forecast) > 0:
        embed.add_field(name="Forecast End", value=f"${forecast[-1]:,.2f}", inline=True)
        move_pct = (forecast[-1] - prediction["current_price"]) / prediction["current_price"] * 100
        embed.add_field(name="Expected Move", value=f"{move_pct:+.2f}%", inline=True)

    embed.set_footer(text="LaT-PFN Trading System")
    return embed


# ── Pre-Trade Radar ─────────────────────────────────────────────


def radar_embed(radar_items: list) -> discord.Embed:
    """
    Build embed for pre-trade radar — scenarios building toward a trigger.

    Each item dict: instrument, direction, confidence, nearest_tier,
    tier_threshold, regime, current_price, forecast_end
    """
    # Cap at 5 items to stay under Discord's 6000 char embed limit
    capped_items = radar_items[:5]
    extra_count = len(radar_items) - len(capped_items)
    desc = "Top scenarios approaching trade thresholds"
    if extra_count > 0:
        desc += f" (+{extra_count} more on radar)"

    embed = discord.Embed(
        title="\U0001F4E1 Trade Radar",
        description=desc,
        color=0xF1C40F,  # yellow/amber
        timestamp=datetime.now(timezone.utc),
    )

    for item in capped_items:
        inst = item["instrument"]
        direction = item["direction"]
        conf = item["confidence"]
        tier_key = item["nearest_tier"]
        tier = tier_key.replace("_", " ").title()
        threshold = item["tier_threshold"]
        gap = threshold - conf
        regime = item["regime"].title()

        # Progress bar toward threshold
        progress = conf / threshold if threshold > 0 else 0
        bar_len = 10
        filled = min(int(progress * bar_len), bar_len)
        bar = "\u2588" * filled + "\u2591" * (bar_len - filled)

        dir_emoji = {
            "long": "\U0001F7E2",
            "short": "\U0001F534",
        }.get(direction, "\u26AA")

        embed.add_field(
            name=f"{dir_emoji} {inst} — {direction.upper()}",
            value=(
                f"**{conf:.1%}** \u2192 {threshold:.0%} for {tier} "
                f"`{bar}` {progress:.0%}\n"
                f"${item['current_price']:,.2f} \u2192 ${item['forecast_end']:,.2f} | {regime}"
            ),
            inline=False,
        )

    embed.set_footer(text="LaT-PFN Radar \u2014 updated every cycle")
    return embed


# ── Alert-level embeds with @mentions ────────────────────────────


def trade_alert_content(instrument: str, signal, alert_role_id: str = None) -> str:
    """Build the text content (outside embed) for trade alerts with @mentions."""
    dir_emoji = "\U0001F7E2" if signal.direction == "long" else "\U0001F534"
    tier_label = signal.shot_type.replace("_", " ").title()
    mention = f"<@&{alert_role_id}>" if alert_role_id else "@here"
    return (
        f"{mention} {dir_emoji} **TRADE ALERT** \u2014 "
        f"{instrument} {signal.direction.upper()} ({tier_label})"
    )


def execution_alert_content(instrument: str, result: dict, alert_role_id: str = None) -> str:
    """Build text content for order execution alerts."""
    if result and "orderId" in result:
        mention = f"<@&{alert_role_id}>" if alert_role_id else "@here"
        return f"{mention} \u2705 **ORDER PLACED** \u2014 {instrument} (ID: {result['orderId']})"
    return f"\u274C **ORDER FAILED** \u2014 {instrument}"


# ── Sniper Mode Embeds ────────────────────────────────────────────


def sniper_plan_embed(candidates: list, balance: float) -> discord.Embed:
    """
    Build embed showing sniper scan results before execution.

    Args:
        candidates: List of SniperCandidate objects.
        balance: Current account balance.
    """
    total_risk = sum(c.risk_usd for c in candidates[:2])

    embed = discord.Embed(
        title="\U0001F3AF Sniper Mode — Scan Results",
        description=(
            f"Balance: **${balance:,.2f}** | "
            f"Risk (top 2): **${total_risk:,.2f}** ({total_risk / balance * 100:.1f}%)"
        ),
        color=0xE74C3C,  # red — aggressive mode
        timestamp=datetime.now(timezone.utc),
    )

    for i, c in enumerate(candidates[:5]):
        dir_emoji = "\U0001F7E2" if c.direction == "long" else "\U0001F534"
        rr = c.reward_usd / c.risk_usd if c.risk_usd > 0 else 0

        # Confidence bar
        bar_len = 10
        filled = min(int(c.confidence * bar_len / 0.8), bar_len)  # scale to 80% = full
        bar = "\u2588" * filled + "\u2591" * (bar_len - filled)

        rank_marker = "\u2B50" if i < 2 else ""  # star for top 2 (will be executed)
        funding_dir = "+" if c.funding_rate > 0 else ""

        embed.add_field(
            name=f"{rank_marker}{dir_emoji} #{i+1} {c.instrument} — {c.direction.upper()}",
            value=(
                f"Conf: **{c.confidence:.1%}** `{bar}`\n"
                f"Entry: ${c.entry_price:,.2f} | SL: ${c.stop_loss:,.2f} | TP: ${c.take_profit:,.2f}\n"
                f"Size: {c.position_size:.4f} | Risk: ${c.risk_usd:,.2f} | R:R {rr:.1f}:1\n"
                f"Edge: {c.edge_score:.2f} | Chg: {c.price_change_pct:+.1f}% | Fund: {funding_dir}{c.funding_rate*100:.4f}%"
            ),
            inline=False,
        )

    embed.add_field(
        name="\u2139\uFE0F Action",
        value="React \u2705 to execute top 2 | \u274C to cancel (15s timeout)",
        inline=False,
    )

    embed.set_footer(text="LaT-PFN Sniper Mode \u2014 wide stops, user-managed exits")
    return embed


def sniper_result_embed(results: list, balance: float) -> discord.Embed:
    """
    Build embed showing sniper execution results.

    Args:
        results: List of dicts with 'candidate' and 'order_result'.
        balance: Account balance after execution.
    """
    success_count = sum(1 for r in results if r.get("order_result"))
    total_risk = sum(r["candidate"].risk_usd for r in results if r.get("order_result"))

    color = 0x2ECC71 if success_count > 0 else 0xE74C3C

    embed = discord.Embed(
        title=f"\U0001F3AF Sniper Executed — {success_count}/{len(results)} Orders Placed",
        description=f"Balance: **${balance:,.2f}** | Total risk: **${total_risk:,.2f}**",
        color=color,
        timestamp=datetime.now(timezone.utc),
    )

    for r in results:
        c = r["candidate"]
        order = r.get("order_result")
        dir_emoji = "\U0001F7E2" if c.direction == "long" else "\U0001F534"

        if order and "orderId" in order:
            embed.add_field(
                name=f"\u2705 {dir_emoji} {c.instrument} {c.direction.upper()}",
                value=(
                    f"Entry: ${c.entry_price:,.2f} | SL: ${c.stop_loss:,.2f}\n"
                    f"Size: {c.position_size:.4f} | Risk: ${c.risk_usd:,.2f}\n"
                    f"Order ID: {order['orderId']}"
                ),
                inline=True,
            )
        else:
            error = r.get("error", "Unknown error")
            embed.add_field(
                name=f"\u274C {dir_emoji} {c.instrument} {c.direction.upper()}",
                value=f"Failed: {error}",
                inline=True,
            )

    embed.set_footer(text="LaT-PFN Sniper Mode \u2014 manage exits manually via /close")
    return embed


def go_result_embed(result: dict) -> discord.Embed:
    """
    Build embed for /go hot-entry results.

    Shows what was scanned, what passed filters, what was executed,
    and current market context (sentiment, regime, liquidations).
    """
    executed = result.get("executed", [])
    rejected = result.get("rejected", [])
    errors = result.get("errors", [])

    if executed:
        color = 0x00FF00  # green — trades placed
        title = f"\U0001F525 HOT ENTRY \u2014 {len(executed)} Trade{'s' if len(executed) > 1 else ''} Executed"
    elif result.get("candidates_found", 0) > 0:
        color = 0xFF8C00  # orange — candidates found but blocked
        title = "\U0001F525 HOT ENTRY \u2014 Signals Found, Blocked by Risk"
    else:
        color = 0x808080  # gray — nothing found
        title = "\U0001F525 HOT ENTRY \u2014 No Signals"

    embed = discord.Embed(
        title=title,
        color=color,
        timestamp=datetime.now(timezone.utc),
    )

    # Scan summary
    scanned = result.get("scanned", 0)
    candidates = result.get("candidates_found", 0)
    embed.add_field(
        name="Scan",
        value=f"{scanned} pairs scanned \u2192 {candidates} candidates",
        inline=True,
    )

    # Balance
    balance = result.get("balance", 0)
    embed.add_field(
        name="Balance",
        value=f"${balance:,.2f}",
        inline=True,
    )

    # Open positions
    embed.add_field(
        name="Positions",
        value=str(result.get("open_positions", 0)),
        inline=True,
    )

    # Market context
    sentiment = result.get("sentiment")
    if sentiment:
        val = sentiment.get("value", 50)
        label = sentiment.get("label", "unknown")
        # Color-code sentiment
        if val <= 25:
            sent_emoji = "\U0001F630"  # fearful face
        elif val >= 75:
            sent_emoji = "\U0001F911"  # money face
        else:
            sent_emoji = "\U0001F610"  # neutral face
        embed.add_field(
            name="Sentiment",
            value=f"{sent_emoji} {val} ({label})",
            inline=True,
        )

    # Liquidation status
    liq = result.get("liquidation_status")
    if liq:
        liq_str = ", ".join(f"{c} {d}" for c, d in liq.items())
        embed.add_field(
            name="\u26A0\uFE0F Liquidation Cascades",
            value=liq_str,
            inline=False,
        )

    # Executed trades
    for trade in executed:
        dir_emoji = "\U0001F7E2" if trade["direction"] == "long" else "\U0001F534"
        conf_bar = _confidence_bar(trade["confidence"])
        funding = trade.get("funding_rate", 0)
        funding_str = f"  |  Funding: {funding:.4%}" if funding != 0 else ""

        risk_pts = abs(trade["entry_price"] - trade["stop_loss"])
        reward_pts = abs(trade["take_profit"] - trade["entry_price"])
        rr = reward_pts / risk_pts if risk_pts > 0 else 0

        embed.add_field(
            name=f"{dir_emoji} {trade['instrument']} {trade['direction'].upper()}",
            value=(
                f"**{trade['shot_type'].replace('_', ' ').title()}**  |  "
                f"Regime: {trade.get('regime', 'N/A')}\n"
                f"Confidence: {conf_bar} {trade['confidence']:.1%}\n"
                f"Entry: ${trade['entry_price']:,.2f}  |  "
                f"Size: {trade['size']}\n"
                f"SL: ${trade['stop_loss']:,.2f}  |  "
                f"TP: ${trade['take_profit']:,.2f}  |  "
                f"R:R {rr:.1f}:1"
                f"{funding_str}"
            ),
            inline=False,
        )

    # Rejected signals
    for rej in rejected[:3]:  # show max 3
        embed.add_field(
            name=f"\U0001F6AB {rej['instrument']} {rej['direction'].upper()}",
            value=f"Conf: {rej['confidence']:.1%} \u2014 {rej.get('reason', 'blocked')}",
            inline=False,
        )

    # Errors
    if errors:
        embed.add_field(
            name="Errors",
            value="\n".join(errors[:3]),
            inline=False,
        )

    if not executed and not rejected:
        embed.description = (
            "No signals passed the microstructure pipeline.\n"
            "All pairs were below confidence threshold or filtered out by "
            "trend/regime/liquidation checks."
        )

    embed.set_footer(text="LaT-PFN Hot Entry \u2014 full microstructure pipeline")
    return embed


def _confidence_bar(confidence: float, width: int = 10) -> str:
    """Build a text-based confidence bar like [########--]."""
    filled = int(confidence * width)
    empty = width - filled
    return f"[{'#' * filled}{'-' * empty}]"
