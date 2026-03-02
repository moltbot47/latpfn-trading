"""CLI interface for the Business Funding Tracker.

Usage:
    python -m funding.cli <command> [args]

Commands:
    parse <pdf>     Parse a credit report PDF
    profile         Show latest credit profile
    status          Funding dashboard overview
    apply           Log a new application
    update          Update application status
    strategy        Get recommended next actions
    plan            Plan next funding round
    rounds          List all funding rounds
    products        Browse product catalog
    inquiries       Show inquiry breakdown
    history         Full application history
    export          Export all data to JSON
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from typing import Any, Optional

from .database import FundingDB
from .models import Application, Inquiry, StrategyRound
from .product_catalog import seed_catalog
from .strategy_engine import get_readiness_score, get_recommendations, plan_round

logger = logging.getLogger(__name__)

# ── Rich imports (graceful fallback) ─────────────────────────────────

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

console: Optional["Console"] = Console() if HAS_RICH else None  # type: ignore[name-defined]


def _print(msg: str = ""):
    if console:
        console.print(msg)
    else:
        print(msg)


def _print_panel(content: str, title: str = "", style: str = "blue"):
    if console:
        console.print(Panel(content, title=title, border_style=style))
    else:
        print(f"\n=== {title} ===")
        print(content)
        print()


# ── Commands ─────────────────────────────────────────────────────────

def cmd_parse(args, db: FundingDB):
    """Parse a credit report PDF."""
    from .pdf_parser import parse_credit_report

    _print(f"Parsing: {args.pdf_path}")
    try:
        profile, inquiries = parse_credit_report(args.pdf_path)
    except FileNotFoundError as e:
        _print(f"[red]Error:[/red] {e}" if HAS_RICH else f"Error: {e}")
        return
    except ImportError as e:
        _print(f"[red]Missing dependency:[/red] {e}" if HAS_RICH else f"Missing dependency: {e}")
        return

    profile_id = db.save_profile(profile)
    _print(f"Saved profile #{profile_id} — Bureau: {profile.bureau}")

    if profile.score:
        _print(f"  Score: {profile.score}")
    if profile.utilization_pct is not None:
        _print(f"  Utilization: {profile.utilization_pct:.1f}%")
    if profile.total_accounts:
        _print(f"  Total Accounts: {profile.total_accounts}")
    if profile.open_accounts:
        _print(f"  Open Accounts: {profile.open_accounts}")
    if profile.derogatory_marks is not None:
        _print(f"  Derogatory Marks: {profile.derogatory_marks}")

    if inquiries:
        _print(f"\n  Found {len(inquiries)} hard inquiries:")
        for inq in inquiries:
            db.save_inquiry(inq)
            _print(f"    {inq.date} — {inq.lender} ({inq.bureau}) [falls off {inq.falls_off_date}]")
    else:
        _print("  No hard inquiries extracted (you can add them manually)")


def cmd_profile(args, db: FundingDB):
    """Show latest credit profile."""
    profile = db.get_latest_profile()
    if not profile:
        _print("No credit profile found. Run: funding parse <pdf_path>")
        return

    if HAS_RICH and console:
        table = Table(title=f"Credit Profile — {profile.bureau.title()}", show_header=False)
        table.add_column("Field", style="cyan")
        table.add_column("Value", style="white")

        table.add_row("Bureau", profile.bureau.title())
        table.add_row("Score", str(profile.score or "N/A"))
        table.add_row("Total Accounts", str(profile.total_accounts or "N/A"))
        table.add_row("Open Accounts", str(profile.open_accounts or "N/A"))
        util = f"{profile.utilization_pct:.1f}%" if profile.utilization_pct is not None else "N/A"
        table.add_row("Utilization", util)
        pmt = f"{profile.payment_history_pct:.1f}%" if profile.payment_history_pct is not None else "N/A"
        table.add_row("Payment History", pmt)
        derog = profile.derogatory_marks if profile.derogatory_marks is not None else "N/A"
        table.add_row("Derogatory Marks", str(derog))
        coll = profile.collections if profile.collections is not None else "N/A"
        table.add_row("Collections", str(coll))
        avg_age = f"{profile.avg_age_years:.1f} years" if profile.avg_age_years else "N/A"
        table.add_row("Avg Account Age", avg_age)
        oldest = f"{profile.oldest_account_years:.1f} years" if profile.oldest_account_years else "N/A"
        table.add_row("Oldest Account", oldest)
        limit = f"${profile.total_credit_limit:,.0f}" if profile.total_credit_limit else "N/A"
        table.add_row("Total Credit Limit", limit)
        table.add_row("Total Balance", f"${profile.total_balance:,.0f}" if profile.total_balance else "N/A")
        table.add_row("Hard Inquiries", str(profile.hard_inquiries_count or "N/A"))
        table.add_row("Parsed", profile.parsed_at[:10])

        console.print(table)
    else:
        _print(f"\n=== Credit Profile — {profile.bureau.title()} ===")
        _print(f"  Score: {profile.score or 'N/A'}")
        util = f"{profile.utilization_pct:.1f}%" if profile.utilization_pct is not None else "N/A"
        _print(f"  Utilization: {util}")
        _print(f"  Total Accounts: {profile.total_accounts or 'N/A'}")
        _print(f"  Derogatory Marks: {profile.derogatory_marks if profile.derogatory_marks is not None else 'N/A'}")
        _print(f"  Parsed: {profile.parsed_at[:10]}")


def cmd_status(args, db: FundingDB):
    """Funding dashboard overview."""
    summary = db.get_funding_summary()
    readiness = get_readiness_score(db)

    if HAS_RICH and console:
        # Readiness score panel
        score = readiness["score"]
        bar_filled = int(score / 5)
        bar_empty = 20 - bar_filled
        bar = f"[green]{'█' * bar_filled}[/green][dim]{'░' * bar_empty}[/dim]"
        readiness_text = f"Readiness Score: {bar} {score}/100\n"
        for factor, detail in readiness["factors"].items():
            readiness_text += f"  {factor.replace('_', ' ').title()}: {detail}\n"
        border = "green" if score >= 70 else "yellow"
        console.print(Panel(readiness_text.strip(), title="Funding Readiness", border_style=border))

        # Summary table
        table = Table(title="Funding Summary")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="white", justify="right")
        table.add_row("Total Applications", str(summary["total_applications"]))
        table.add_row("Approved", f"[green]{summary['approved']}[/green]")
        table.add_row("Pending", f"[yellow]{summary['pending']}[/yellow]")
        table.add_row("Denied", f"[red]{summary['denied']}[/red]")
        table.add_row("Approval Rate", f"{summary['approval_rate']:.0f}%")
        table.add_row("Total Funding", f"[bold green]${summary['total_funding_approved']:,.0f}[/bold green]")
        table.add_row("Latest Score", str(summary["latest_score"] or "N/A"))

        if summary["inquiries_12mo"]:
            inq_str = ", ".join(f"{b.title()}: {c}" for b, c in summary["inquiries_12mo"].items())
            table.add_row("Inquiries (12 mo)", inq_str)

        console.print(table)
    else:
        _print("\n=== Funding Dashboard ===")
        _print(f"  Readiness Score: {readiness['score']}/100")
        apps = summary['total_applications']
        appr, pend, deny = summary['approved'], summary['pending'], summary['denied']
        _print(f"  Applications: {apps} (Approved: {appr}, Pending: {pend}, Denied: {deny})")
        _print(f"  Total Funding: ${summary['total_funding_approved']:,.0f}")
        _print(f"  Approval Rate: {summary['approval_rate']:.0f}%")


def cmd_apply(args, db: FundingDB):
    """Log a new funding application."""
    product_type = _input_choice(
        "Product type", ["credit_card", "loc", "term_loan", "sba", "balance_transfer"]
    )
    lender = input("Lender name: ").strip()
    if not lender:
        _print("Lender name is required.")
        return

    product_name = input("Product name (optional): ").strip() or None
    amount_str = input("Amount requested (optional, $): ").strip()
    amount = float(amount_str.replace(",", "").replace("$", "")) if amount_str else None

    status = _input_choice(
        "Current status", ["planned", "applied", "pending", "approved", "denied"]
    )

    bureau = input("Bureau pulled (experian/transunion/equifax/multiple, optional): ").strip() or None

    amount_approved = None
    if status == "approved":
        approved_str = input("Amount approved ($): ").strip()
        amount_approved = float(approved_str.replace(",", "").replace("$", "")) if approved_str else None

    app = Application(
        product_type=product_type,
        lender=lender,
        product_name=product_name,
        amount_requested=amount,
        amount_approved=amount_approved,
        status=status,
        applied_date=datetime.utcnow().strftime("%Y-%m-%d") if status != "planned" else None,
        decision_date=datetime.utcnow().strftime("%Y-%m-%d") if status in ("approved", "denied") else None,
        bureau_pulled=bureau,
    )

    app_id = db.save_application(app)
    _print(f"\nApplication #{app_id} saved — {lender} {product_name or product_type} [{status}]")

    # Auto-create inquiry if applied
    if status in ("applied", "pending", "approved") and bureau and bureau != "multiple":
        inq = Inquiry(
            date=datetime.utcnow().strftime("%Y-%m-%d"),
            bureau=bureau,
            lender=lender,
            falls_off_date=_add_years_str(datetime.utcnow().strftime("%Y-%m-%d"), 2),
            source="manual",
            application_id=app_id,
        )
        db.save_inquiry(inq)
        _print(f"  Hard inquiry recorded on {bureau.title()}")


def cmd_update(args, db: FundingDB):
    """Update an application's status."""
    app = db.get_application(args.app_id)
    if not app:
        _print(f"Application #{args.app_id} not found.")
        return

    _print(f"Current: #{app.id} {app.lender} {app.product_name or app.product_type} — [{app.status}]")

    new_status = args.status
    kwargs = {"status": new_status}

    if new_status in ("approved", "denied"):
        kwargs["decision_date"] = datetime.utcnow().strftime("%Y-%m-%d")

    if new_status == "approved":
        amount_str = input("Amount approved ($): ").strip()
        if amount_str:
            kwargs["amount_approved"] = float(amount_str.replace(",", "").replace("$", ""))
        limit_str = input("Credit limit ($ if applicable): ").strip()
        if limit_str:
            kwargs["credit_limit"] = float(limit_str.replace(",", "").replace("$", ""))

    if new_status == "denied":
        reason = input("Denial reason (optional): ").strip()
        if reason:
            kwargs["denial_reason"] = reason

    db.update_application(args.app_id, **kwargs)
    _print(f"\nUpdated #{args.app_id} → [{new_status}]")


def cmd_strategy(args, db: FundingDB):
    """Show strategy recommendations."""
    recs = get_recommendations(db)

    if not recs:
        _print("No recommendations available. Upload a credit report first.")
        return

    if HAS_RICH and console:
        for rec in recs:
            impact_color = {"high": "red", "medium": "yellow", "low": "green"}.get(rec.impact or "", "white")
            title = f"[{impact_color}][{rec.impact.upper() if rec.impact else 'INFO'}][/{impact_color}] {rec.title}"
            console.print(Panel(rec.detail, title=title, border_style=impact_color))
    else:
        for rec in recs:
            _print(f"\n[{rec.impact.upper() if rec.impact else 'INFO'}] {rec.title}")
            _print(f"  {rec.detail}")


def cmd_plan(args, db: FundingDB):
    """Plan next funding round."""
    products = plan_round(db)

    if not products:
        _print("No eligible products for a round. Check strategy recommendations.")
        return

    _print(f"\nPlanned Round: {len(products)} products")
    _print("-" * 60)

    total_low = 0.0
    total_high = 0.0
    for i, prod in enumerate(products, 1):
        limit = ""
        if prod.typical_limit_low and prod.typical_limit_high:
            limit = f"${prod.typical_limit_low:,.0f} – ${prod.typical_limit_high:,.0f}"
            total_low += prod.typical_limit_low
            total_high += prod.typical_limit_high
        bureau = f"({prod.bureau_pulled})" if prod.bureau_pulled else ""
        sensitive = " *INQUIRY SENSITIVE*" if prod.inquiry_sensitive else ""
        _print(f"  {i}. {prod.lender} — {prod.product_name} {bureau}")
        _print(f"     Type: {prod.product_type} | Range: {limit}{sensitive}")
        if prod.notes:
            _print(f"     Note: {prod.notes[:80]}")

    _print("-" * 60)
    _print(f"  Estimated range: ${total_low:,.0f} – ${total_high:,.0f}")

    save = input("\nSave this round? (y/n): ").strip().lower()
    if save == "y":
        name = input("Round name (optional): ").strip() or f"Round {datetime.utcnow().strftime('%Y-%m-%d')}"
        rnd = StrategyRound(
            name=name,
            planned_date=datetime.utcnow().strftime("%Y-%m-%d"),
            status="planning",
            target_total=(total_low + total_high) / 2 if total_low else None,
        )
        round_id = db.save_round(rnd)
        _print(f"\nRound #{round_id} saved: {name}")


def cmd_rounds(args, db: FundingDB):
    """List all funding rounds."""
    rounds = db.get_rounds()

    if not rounds:
        _print("No funding rounds yet. Use: funding plan")
        return

    if HAS_RICH and console:
        table = Table(title="Funding Rounds")
        table.add_column("#", style="dim")
        table.add_column("Name", style="cyan")
        table.add_column("Planned", style="white")
        table.add_column("Status", style="white")
        table.add_column("Target", style="white", justify="right")
        table.add_column("Actual", style="green", justify="right")

        for rnd in rounds:
            status_style = {
                "planning": "[yellow]planning[/yellow]",
                "ready": "[blue]ready[/blue]",
                "executing": "[magenta]executing[/magenta]",
                "completed": "[green]completed[/green]",
            }.get(rnd.status, rnd.status)

            table.add_row(
                str(rnd.id),
                rnd.name or "—",
                rnd.planned_date or "—",
                status_style,
                f"${rnd.target_total:,.0f}" if rnd.target_total else "—",
                f"${rnd.actual_total:,.0f}" if rnd.actual_total else "—",
            )
        console.print(table)
    else:
        for rnd in rounds:
            _print(f"  #{rnd.id} {rnd.name or 'Unnamed'} [{rnd.status}] — Target: ${rnd.target_total or 0:,.0f}")


def cmd_products(args, db: FundingDB):
    """Browse product catalog."""
    products = db.get_products(product_type=args.type if hasattr(args, "type") and args.type else None)

    if not products:
        _print("Product catalog is empty. It will be seeded on first run.")
        return

    if HAS_RICH and console:
        table = Table(title=f"Product Catalog ({len(products)} products)")
        table.add_column("#", style="dim", width=3)
        table.add_column("Lender", style="cyan", width=14)
        table.add_column("Product", style="white", width=28)
        table.add_column("Type", style="white", width=10)
        table.add_column("Min Score", justify="right", width=6)
        table.add_column("Limit Range", justify="right", width=16)
        table.add_column("Bureau", width=12)
        table.add_column("Inq Sens", justify="center", width=5)
        table.add_column("0% APR", justify="right", width=6)

        for prod in products:
            limit = ""
            if prod.typical_limit_low and prod.typical_limit_high:
                limit = f"${prod.typical_limit_low/1000:.0f}k–${prod.typical_limit_high/1000:.0f}k"

            apr = ""
            if prod.intro_apr is not None and prod.intro_apr == 0.0:
                apr = f"{prod.intro_period_months}mo" if prod.intro_period_months else "Yes"

            table.add_row(
                str(prod.id),
                prod.lender,
                prod.product_name,
                prod.product_type,
                str(prod.min_score or "—"),
                limit or "—",
                prod.bureau_pulled or "—",
                "[red]Yes[/red]" if prod.inquiry_sensitive else "No",
                apr or "—",
            )
        console.print(table)
    else:
        for prod in products:
            score = prod.min_score or 'N/A'
            bureau = prod.bureau_pulled or 'N/A'
            _print(f"  {prod.lender} — {prod.product_name} ({prod.product_type}) | Min: {score} | {bureau}")


def cmd_inquiries(args, db: FundingDB):
    """Show inquiry breakdown by bureau."""
    inquiries = db.get_inquiries()
    counts_12mo = db.get_inquiry_counts_by_bureau(12)
    counts_24mo = db.get_inquiry_counts_by_bureau(24)

    if HAS_RICH and console:
        # Bureau summary
        table = Table(title="Inquiry Summary")
        table.add_column("Bureau", style="cyan")
        table.add_column("12 Months", justify="right")
        table.add_column("24 Months", justify="right")

        for bureau in ["experian", "transunion", "equifax"]:
            table.add_row(
                bureau.title(),
                str(counts_12mo.get(bureau, 0)),
                str(counts_24mo.get(bureau, 0)),
            )
        table.add_row(
            "[bold]Total[/bold]",
            f"[bold]{sum(counts_12mo.values())}[/bold]",
            f"[bold]{sum(counts_24mo.values())}[/bold]",
        )
        console.print(table)

        # Individual inquiries
        if inquiries:
            detail = Table(title="All Inquiries")
            detail.add_column("Date", style="white")
            detail.add_column("Bureau", style="cyan")
            detail.add_column("Lender", style="white")
            detail.add_column("Falls Off", style="dim")

            for inq in inquiries[:20]:
                detail.add_row(inq.date, inq.bureau.title(), inq.lender, inq.falls_off_date or "—")
            console.print(detail)
    else:
        _print("\n=== Inquiry Summary ===")
        for bureau in ["experian", "transunion", "equifax"]:
            _print(f"  {bureau.title()}: {counts_12mo.get(bureau, 0)} (12mo) / {counts_24mo.get(bureau, 0)} (24mo)")
        _print(f"  Total: {sum(counts_12mo.values())} (12mo)")


def cmd_history(args, db: FundingDB):
    """Full application history."""
    apps = db.get_all_applications()

    if not apps:
        _print("No applications yet. Use: funding apply")
        return

    if HAS_RICH and console:
        table = Table(title=f"Application History ({len(apps)} applications)")
        table.add_column("#", style="dim", width=3)
        table.add_column("Lender", style="cyan", width=14)
        table.add_column("Product", style="white", width=22)
        table.add_column("Type", width=10)
        table.add_column("Status", width=10)
        table.add_column("Approved", justify="right", width=10)
        table.add_column("Bureau", width=10)
        table.add_column("Date", width=10)

        for app in apps:
            status_style = {
                "approved": "[green]APPROVED[/green]",
                "denied": "[red]DENIED[/red]",
                "pending": "[yellow]PENDING[/yellow]",
                "applied": "[blue]APPLIED[/blue]",
                "planned": "[dim]PLANNED[/dim]",
                "withdrawn": "[dim]WITHDRAWN[/dim]",
            }.get(app.status, app.status)

            amount = ""
            if app.amount_approved:
                amount = f"${app.amount_approved:,.0f}"
            elif app.credit_limit:
                amount = f"${app.credit_limit:,.0f}"

            table.add_row(
                str(app.id),
                app.lender,
                app.product_name or "—",
                app.product_type,
                status_style,
                amount or "—",
                app.bureau_pulled or "—",
                app.applied_date or app.created_at[:10],
            )
        console.print(table)
    else:
        for app in apps:
            amount = f"${app.amount_approved:,.0f}" if app.amount_approved else "—"
            _print(f"  #{app.id} {app.lender} {app.product_name or app.product_type} [{app.status}] {amount}")


def cmd_export(args, db: FundingDB):
    """Export all data to JSON."""
    profiles = db.get_all_profiles()
    apps = db.get_all_applications()
    inquiries = db.get_inquiries()
    rounds = db.get_rounds()

    data = {
        "exported_at": datetime.utcnow().isoformat(),
        "credit_profiles": [p.to_dict() for p in profiles],
        "applications": [a.to_dict() for a in apps],
        "inquiries": [i.to_dict() for i in inquiries],
        "rounds": [r.to_dict() for r in rounds],
    }

    filename = f"data/funding_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)

    _print(f"Exported to {filename} ({len(profiles)} profiles, {len(apps)} applications, {len(inquiries)} inquiries)")


# ── Helpers ──────────────────────────────────────────────────────────

def _input_choice(prompt: str, options: list[str]) -> str:
    """Interactive choice selection."""
    _print(f"\n{prompt}:")
    for i, opt in enumerate(options, 1):
        _print(f"  {i}. {opt}")
    while True:
        choice = input(f"Select (1-{len(options)}): ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                return options[idx]
        except ValueError:
            if choice in options:
                return choice
        _print("Invalid choice, try again.")


def _add_years_str(date_str: str, years: int) -> str:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    try:
        return dt.replace(year=dt.year + years).strftime("%Y-%m-%d")
    except ValueError:
        return dt.replace(year=dt.year + years, day=28).strftime("%Y-%m-%d")


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="funding",
        description="Business Funding Tracker — track applications, manage inquiries, optimize strategy",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # parse
    p_parse = sub.add_parser("parse", help="Parse a credit report PDF")
    p_parse.add_argument("pdf_path", help="Path to credit report PDF")

    # profile
    sub.add_parser("profile", help="Show latest credit profile")

    # status
    sub.add_parser("status", help="Funding dashboard overview")

    # apply
    sub.add_parser("apply", help="Log a new funding application")

    # update
    p_update = sub.add_parser("update", help="Update application status")
    p_update.add_argument("app_id", type=int, help="Application ID")
    p_update.add_argument("status", choices=["planned", "applied", "pending", "approved", "denied", "withdrawn"])

    # strategy
    sub.add_parser("strategy", help="Get strategy recommendations")

    # plan
    sub.add_parser("plan", help="Plan next funding round")

    # rounds
    sub.add_parser("rounds", help="List all funding rounds")

    # products
    p_products = sub.add_parser("products", help="Browse product catalog")
    p_products.add_argument("--type", choices=["credit_card", "loc", "term_loan", "sba", "balance_transfer"])

    # inquiries
    sub.add_parser("inquiries", help="Show inquiry breakdown")

    # history
    sub.add_parser("history", help="Full application history")

    # export
    sub.add_parser("export", help="Export all data to JSON")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Initialize DB and seed catalog
    db = FundingDB()
    seeded = seed_catalog(db)
    if seeded > 0:
        _print(f"Seeded product catalog with {seeded} products")

    # Dispatch
    commands = {
        "parse": cmd_parse,
        "profile": cmd_profile,
        "status": cmd_status,
        "apply": cmd_apply,
        "update": cmd_update,
        "strategy": cmd_strategy,
        "plan": cmd_plan,
        "rounds": cmd_rounds,
        "products": cmd_products,
        "inquiries": cmd_inquiries,
        "history": cmd_history,
        "export": cmd_export,
    }

    cmd_func = commands.get(args.command)
    if cmd_func:
        cmd_func(args, db)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
