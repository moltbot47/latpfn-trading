"""Discord embed builders for the Business Funding Tracker."""

import discord
from datetime import datetime


# ── Colors ───────────────────────────────────────────────────────────

COLOR_APPROVED = 0x00FF00   # green
COLOR_PENDING = 0xFFD700    # gold
COLOR_DENIED = 0xFF4500     # red
COLOR_STRATEGY = 0x7289DA   # blurple
COLOR_PROFILE = 0x3498DB    # blue
COLOR_MILESTONE = 0xF1C40F  # yellow/gold
COLOR_INQUIRY = 0x9B59B6    # purple


def status_embed(summary: dict, readiness: dict) -> discord.Embed:
    """Build funding status overview embed."""
    score = readiness["score"]
    bar_filled = int(score / 5)
    bar_empty = 20 - bar_filled
    bar = "█" * bar_filled + "░" * bar_empty

    embed = discord.Embed(
        title="Business Funding Dashboard",
        color=COLOR_PROFILE,
        timestamp=datetime.utcnow(),
    )

    embed.add_field(
        name="Readiness Score",
        value=f"`{bar}` **{score}/100**",
        inline=False,
    )

    # Funding totals
    embed.add_field(name="Total Funding", value=f"**${summary['total_funding_approved']:,.0f}**", inline=True)
    embed.add_field(name="Applications", value=str(summary["total_applications"]), inline=True)
    embed.add_field(name="Approval Rate", value=f"{summary['approval_rate']:.0f}%", inline=True)

    # Status breakdown
    status_text = (
        f"Approved: **{summary['approved']}**\n"
        f"Pending: **{summary['pending']}**\n"
        f"Denied: **{summary['denied']}**"
    )
    embed.add_field(name="Status Breakdown", value=status_text, inline=True)

    # Credit score
    if summary["latest_score"]:
        embed.add_field(
            name="Credit Score",
            value=f"**{summary['latest_score']}** ({summary['latest_bureau'].title()})",
            inline=True,
        )

    # Inquiries
    if summary["inquiries_12mo"]:
        inq_lines = [f"{b.title()}: **{c}**" for b, c in summary["inquiries_12mo"].items()]
        embed.add_field(name="Inquiries (12 mo)", value="\n".join(inq_lines), inline=True)

    # Readiness factors
    factor_lines = []
    for factor, detail in readiness["factors"].items():
        factor_lines.append(f"**{factor.replace('_', ' ').title()}**: {detail}")
    if factor_lines:
        embed.add_field(name="Readiness Factors", value="\n".join(factor_lines[:6]), inline=False)

    embed.set_footer(text="Business Funding Tracker")
    return embed


def strategy_embed(recommendations: list) -> discord.Embed:
    """Build strategy recommendations embed."""
    embed = discord.Embed(
        title="Funding Strategy Recommendations",
        color=COLOR_STRATEGY,
        timestamp=datetime.utcnow(),
    )

    for rec in recommendations[:8]:
        icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(rec.impact, "ℹ️")
        embed.add_field(
            name=f"{icon} {rec.title}",
            value=rec.detail[:200],
            inline=False,
        )

    embed.set_footer(text="Business Funding Tracker")
    return embed


def application_embed(app, action: str = "logged") -> discord.Embed:
    """Build application status embed."""
    color = {
        "approved": COLOR_APPROVED,
        "denied": COLOR_DENIED,
        "pending": COLOR_PENDING,
        "applied": COLOR_PENDING,
        "planned": COLOR_PROFILE,
    }.get(app.status, COLOR_PROFILE)

    status_emoji = {
        "approved": "✅",
        "denied": "❌",
        "pending": "⏳",
        "applied": "📋",
        "planned": "📝",
    }.get(app.status, "📋")

    embed = discord.Embed(
        title=f"{status_emoji} Application {action.title()}: {app.lender}",
        description=f"**{app.product_name or app.product_type}**",
        color=color,
        timestamp=datetime.utcnow(),
    )

    embed.add_field(name="Status", value=app.status.upper(), inline=True)
    embed.add_field(name="Type", value=app.product_type.replace("_", " ").title(), inline=True)

    if app.bureau_pulled:
        embed.add_field(name="Bureau", value=app.bureau_pulled.title(), inline=True)

    if app.amount_approved:
        embed.add_field(name="Approved Amount", value=f"**${app.amount_approved:,.0f}**", inline=True)
    elif app.credit_limit:
        embed.add_field(name="Credit Limit", value=f"**${app.credit_limit:,.0f}**", inline=True)
    elif app.amount_requested:
        embed.add_field(name="Requested", value=f"${app.amount_requested:,.0f}", inline=True)

    if app.intro_apr is not None and app.intro_apr == 0.0:
        embed.add_field(
            name="Intro APR",
            value=f"0% for {app.intro_period_months} months" if app.intro_period_months else "0%",
            inline=True,
        )

    if app.denial_reason:
        embed.add_field(name="Denial Reason", value=app.denial_reason, inline=False)

    embed.set_footer(text="Business Funding Tracker")
    return embed


def milestone_embed(app, total_funding: float) -> discord.Embed:
    """Build celebration embed for approved applications."""
    embed = discord.Embed(
        title=f"🎉 APPROVED: {app.lender} — {app.product_name or app.product_type}",
        color=COLOR_MILESTONE,
        timestamp=datetime.utcnow(),
    )

    amount = app.amount_approved or app.credit_limit or 0
    embed.add_field(name="Amount", value=f"**${amount:,.0f}**", inline=True)
    embed.add_field(name="Type", value=app.product_type.replace("_", " ").title(), inline=True)
    embed.add_field(name="Total Funding", value=f"**${total_funding:,.0f}**", inline=True)

    if app.intro_apr is not None and app.intro_apr == 0.0:
        embed.add_field(
            name="Intro APR",
            value=f"0% for {app.intro_period_months} months" if app.intro_period_months else "0%",
            inline=True,
        )

    embed.set_footer(text="Business Funding Tracker")
    return embed


def inquiries_embed(inquiries: list, counts_12mo: dict, counts_24mo: dict) -> discord.Embed:
    """Build inquiry breakdown embed."""
    embed = discord.Embed(
        title="Hard Inquiry Breakdown",
        color=COLOR_INQUIRY,
        timestamp=datetime.utcnow(),
    )

    # Bureau summary
    summary_lines = []
    for bureau in ["experian", "transunion", "equifax"]:
        c12 = counts_12mo.get(bureau, 0)
        c24 = counts_24mo.get(bureau, 0)
        bar = "█" * min(c12, 10) + "░" * max(0, 10 - c12)
        summary_lines.append(f"**{bureau.title()}**: `{bar}` {c12} (12mo) / {c24} (24mo)")

    total_12 = sum(counts_12mo.values())
    total_24 = sum(counts_24mo.values())
    summary_lines.append(f"\n**Total**: {total_12} (12 mo) / {total_24} (24 mo)")

    embed.add_field(name="By Bureau", value="\n".join(summary_lines), inline=False)

    # Recent inquiries
    if inquiries:
        recent_lines = []
        for inq in inquiries[:8]:
            recent_lines.append(f"`{inq.date}` {inq.lender} ({inq.bureau.title()})")
        embed.add_field(name="Recent Inquiries", value="\n".join(recent_lines), inline=False)

    # Fall-off timeline
    upcoming = [i for i in inquiries if i.falls_off_date]
    upcoming.sort(key=lambda x: x.falls_off_date)
    if upcoming:
        falloff_lines = []
        for inq in upcoming[:5]:
            falloff_lines.append(f"`{inq.falls_off_date}` {inq.lender}")
        embed.add_field(name="Next Fall-Off Dates", value="\n".join(falloff_lines), inline=False)

    embed.set_footer(text="Business Funding Tracker")
    return embed
