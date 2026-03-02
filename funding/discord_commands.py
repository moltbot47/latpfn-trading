"""Discord slash commands for the Business Funding Tracker.

Register these commands in the existing bot's setup_hook().
"""

import logging
from datetime import datetime
from typing import Any, Optional

import discord
from discord import app_commands

from .database import FundingDB
from .embeds import (
    application_embed,
    inquiries_embed,
    milestone_embed,
    status_embed,
    strategy_embed,
)
from .product_catalog import seed_catalog
from .strategy_engine import get_readiness_score, get_recommendations

logger = logging.getLogger(__name__)

# Shared DB instance
_db: Optional[FundingDB] = None


def get_db() -> FundingDB:
    global _db
    if _db is None:
        _db = FundingDB()
        seed_catalog(_db)
    return _db


# ── Slash Commands ───────────────────────────────────────────────────

@app_commands.command(name="funding_status", description="Business funding dashboard overview")
async def funding_status_cmd(interaction: discord.Interaction):
    """Show funding status overview."""
    await interaction.response.defer(thinking=True)
    try:
        db = get_db()
        summary = db.get_funding_summary()
        readiness = get_readiness_score(db)
        embed = status_embed(summary, readiness)
        await interaction.followup.send(embed=embed)
    except Exception as e:
        logger.error("funding_status error: %s", e)
        await interaction.followup.send(f"Error: {e}", ephemeral=True)


@app_commands.command(name="funding_strategy", description="Get funding strategy recommendations")
async def funding_strategy_cmd(interaction: discord.Interaction):
    """Show strategy recommendations."""
    await interaction.response.defer(thinking=True)
    try:
        db = get_db()
        recs = get_recommendations(db)
        if not recs:
            msg = "No recommendations yet. Upload a credit report first via CLI."
            await interaction.followup.send(msg, ephemeral=True)
            return
        embed = strategy_embed(recs)
        await interaction.followup.send(embed=embed)
    except Exception as e:
        logger.error("funding_strategy error: %s", e)
        await interaction.followup.send(f"Error: {e}", ephemeral=True)


@app_commands.command(name="funding_apply", description="Log a new funding application")
@app_commands.describe(
    lender="Lender name (e.g., Chase, Amex)",
    product="Product name (e.g., Ink Business Preferred)",
    product_type="Type of funding product",
    status="Current application status",
    amount="Amount requested or approved ($)",
    bureau="Bureau pulled for this application",
)
@app_commands.choices(product_type=[
    app_commands.Choice(name="Credit Card", value="credit_card"),
    app_commands.Choice(name="Line of Credit", value="loc"),
    app_commands.Choice(name="Term Loan", value="term_loan"),
    app_commands.Choice(name="SBA Loan", value="sba"),
    app_commands.Choice(name="Balance Transfer", value="balance_transfer"),
])
@app_commands.choices(status=[
    app_commands.Choice(name="Planned", value="planned"),
    app_commands.Choice(name="Applied", value="applied"),
    app_commands.Choice(name="Pending", value="pending"),
    app_commands.Choice(name="Approved", value="approved"),
    app_commands.Choice(name="Denied", value="denied"),
])
@app_commands.choices(bureau=[
    app_commands.Choice(name="Experian", value="experian"),
    app_commands.Choice(name="TransUnion", value="transunion"),
    app_commands.Choice(name="Equifax", value="equifax"),
    app_commands.Choice(name="Multiple", value="multiple"),
])
async def funding_apply_cmd(
    interaction: discord.Interaction,
    lender: str,
    product: str,
    product_type: app_commands.Choice[str],
    status: app_commands.Choice[str],
    amount: Optional[float] = None,
    bureau: Optional[app_commands.Choice[str]] = None,
):
    """Log a new funding application."""
    await interaction.response.defer(thinking=True)
    try:
        from .models import Application, Inquiry

        db = get_db()
        now = datetime.utcnow()

        app = Application(
            product_type=product_type.value,
            lender=lender,
            product_name=product,
            amount_requested=amount if status.value != "approved" else None,
            amount_approved=amount if status.value == "approved" else None,
            status=status.value,
            applied_date=now.strftime("%Y-%m-%d") if status.value != "planned" else None,
            decision_date=now.strftime("%Y-%m-%d") if status.value in ("approved", "denied") else None,
            bureau_pulled=bureau.value if bureau else None,
        )

        app_id = db.save_application(app)
        app.id = app_id

        # Auto-create inquiry
        if status.value in ("applied", "pending", "approved") and bureau and bureau.value not in ("multiple",):
            inq = Inquiry(
                date=now.strftime("%Y-%m-%d"),
                bureau=bureau.value,
                lender=lender,
                falls_off_date=_add_years(now.strftime("%Y-%m-%d"), 2),
                source="manual",
                application_id=app_id,
            )
            db.save_inquiry(inq)

        embed = application_embed(app, action="logged")
        await interaction.followup.send(embed=embed)

    except Exception as e:
        logger.error("funding_apply error: %s", e)
        await interaction.followup.send(f"Error: {e}", ephemeral=True)


@app_commands.command(name="funding_update", description="Update application status")
@app_commands.describe(
    app_id="Application ID number",
    status="New status",
    amount="Approved amount (for approvals)",
)
@app_commands.choices(status=[
    app_commands.Choice(name="Applied", value="applied"),
    app_commands.Choice(name="Pending", value="pending"),
    app_commands.Choice(name="Approved", value="approved"),
    app_commands.Choice(name="Denied", value="denied"),
    app_commands.Choice(name="Withdrawn", value="withdrawn"),
])
async def funding_update_cmd(
    interaction: discord.Interaction,
    app_id: int,
    status: app_commands.Choice[str],
    amount: Optional[float] = None,
):
    """Update an application status."""
    await interaction.response.defer(thinking=True)
    try:
        db = get_db()
        app = db.get_application(app_id)
        if not app:
            await interaction.followup.send(f"Application #{app_id} not found.", ephemeral=True)
            return

        kwargs: dict[str, Any] = {"status": status.value}
        if status.value in ("approved", "denied"):
            kwargs["decision_date"] = datetime.utcnow().strftime("%Y-%m-%d")
        if amount and status.value == "approved":
            kwargs["amount_approved"] = amount

        db.update_application(app_id, **kwargs)

        # Refresh
        app = db.get_application(app_id)
        embed = application_embed(app, action="updated")
        await interaction.followup.send(embed=embed)

    except Exception as e:
        logger.error("funding_update error: %s", e)
        await interaction.followup.send(f"Error: {e}", ephemeral=True)


@app_commands.command(name="funding_milestone", description="Celebrate a funding approval")
@app_commands.describe(app_id="Application ID of the approved product")
async def funding_milestone_cmd(interaction: discord.Interaction, app_id: int):
    """Post a celebration embed for an approved application."""
    await interaction.response.defer(thinking=True)
    try:
        db = get_db()
        app = db.get_application(app_id)
        if not app:
            await interaction.followup.send(f"Application #{app_id} not found.", ephemeral=True)
            return

        if app.status != "approved":
            msg = f"Application #{app_id} is not approved (status: {app.status})."
            await interaction.followup.send(msg, ephemeral=True)
            return

        summary = db.get_funding_summary()
        embed = milestone_embed(app, summary["total_funding_approved"])

        content = f"🎉 **FUNDING MILESTONE** — {app.lender} {app.product_name or app.product_type} APPROVED!"
        await interaction.followup.send(content=content, embed=embed)

    except Exception as e:
        logger.error("funding_milestone error: %s", e)
        await interaction.followup.send(f"Error: {e}", ephemeral=True)


@app_commands.command(name="funding_inquiries", description="Show hard inquiry breakdown by bureau")
async def funding_inquiries_cmd(interaction: discord.Interaction):
    """Show inquiry breakdown."""
    await interaction.response.defer(thinking=True)
    try:
        db = get_db()
        inqs = db.get_inquiries()
        counts_12 = db.get_inquiry_counts_by_bureau(12)
        counts_24 = db.get_inquiry_counts_by_bureau(24)
        embed = inquiries_embed(inqs, counts_12, counts_24)
        await interaction.followup.send(embed=embed)
    except Exception as e:
        logger.error("funding_inquiries error: %s", e)
        await interaction.followup.send(f"Error: {e}", ephemeral=True)


# ── Registration ─────────────────────────────────────────────────────

FUNDING_COMMANDS = [
    funding_status_cmd,
    funding_strategy_cmd,
    funding_apply_cmd,
    funding_update_cmd,
    funding_milestone_cmd,
    funding_inquiries_cmd,
]


def register_funding_commands(bot):
    """Register all funding slash commands with the bot's command tree."""
    for cmd in FUNDING_COMMANDS:
        bot.tree.add_command(cmd)
    logger.info("Registered %d funding slash commands", len(FUNDING_COMMANDS))


# ── Helpers ──────────────────────────────────────────────────────────

def _add_years(date_str: str, years: int) -> str:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    try:
        return dt.replace(year=dt.year + years).strftime("%Y-%m-%d")
    except ValueError:
        return dt.replace(year=dt.year + years, day=28).strftime("%Y-%m-%d")
