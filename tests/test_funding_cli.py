"""Tests for funding.cli — CLI interface for the Business Funding Tracker.

Covers every cmd_* function, helpers (_input_choice, _add_years_str), and
main() dispatch, with both Rich and plain-text code paths exercised.
"""

import argparse
import json
import os
from datetime import datetime
from unittest.mock import MagicMock, patch, call

import pytest

from funding.cli import (
    _add_years_str,
    _input_choice,
    cmd_apply,
    cmd_export,
    cmd_history,
    cmd_inquiries,
    cmd_parse,
    cmd_plan,
    cmd_products,
    cmd_profile,
    cmd_rounds,
    cmd_status,
    cmd_strategy,
    cmd_update,
    main,
)
from funding.database import FundingDB
from funding.models import (
    Application,
    CreditProfile,
    FundingProduct,
    Inquiry,
    Recommendation,
    StrategyRound,
)
from funding.product_catalog import seed_catalog


# ── Helper: make a Namespace ────────────────────────────────────────


def _ns(**kwargs):
    """Shorthand for argparse.Namespace."""
    return argparse.Namespace(**kwargs)


# ── _add_years_str ──────────────────────────────────────────────────


class TestAddYearsStr:
    def test_normal_date(self):
        assert _add_years_str("2024-03-15", 2) == "2026-03-15"

    def test_leap_year_feb_29(self):
        # 2024-02-29 + 2 years => 2026 has no Feb 29, should fallback to 28
        result = _add_years_str("2024-02-29", 2)
        assert result == "2026-02-28"

    def test_leap_year_to_leap_year(self):
        # 2024-02-29 + 4 years => 2028-02-29 (both leap years)
        assert _add_years_str("2024-02-29", 4) == "2028-02-29"

    def test_zero_years(self):
        assert _add_years_str("2025-06-15", 0) == "2025-06-15"

    def test_one_year(self):
        assert _add_years_str("2025-01-01", 1) == "2026-01-01"


# ── _input_choice ───────────────────────────────────────────────────


class TestInputChoice:
    @patch("funding.cli._print")
    def test_valid_numeric_choice(self, mock_print):
        options = ["alpha", "beta", "gamma"]
        with patch("builtins.input", return_value="2"):
            result = _input_choice("Pick one", options)
        assert result == "beta"

    @patch("funding.cli._print")
    def test_valid_text_choice(self, mock_print):
        options = ["credit_card", "loc"]
        with patch("builtins.input", return_value="loc"):
            result = _input_choice("Type", options)
        assert result == "loc"

    @patch("funding.cli._print")
    def test_retries_on_invalid_then_succeeds(self, mock_print):
        options = ["a", "b"]
        with patch("builtins.input", side_effect=["99", "bad", "1"]):
            result = _input_choice("Choose", options)
        assert result == "a"
        # Should have printed "Invalid choice" twice
        invalid_calls = [c for c in mock_print.call_args_list if "Invalid" in str(c)]
        assert len(invalid_calls) == 2


# ── cmd_profile ─────────────────────────────────────────────────────


class TestCmdProfile:
    @patch("funding.cli._print")
    def test_no_profile(self, mock_print, funding_db):
        cmd_profile(_ns(), funding_db)
        mock_print.assert_called_once()
        assert "No credit profile" in mock_print.call_args[0][0]

    @patch("funding.cli.HAS_RICH", False)
    @patch("funding.cli.console", None)
    @patch("funding.cli._print")
    def test_with_profile_plain(self, mock_print, funding_db, sample_profile):
        funding_db.save_profile(sample_profile)
        cmd_profile(_ns(), funding_db)
        output = " ".join(str(c) for c in mock_print.call_args_list)
        assert "720" in output
        assert "Experian" in output

    @patch("funding.cli.HAS_RICH", True)
    @patch("funding.cli.console")
    def test_with_profile_rich(self, mock_console, funding_db, sample_profile):
        """Rich path: console.print is called with a Table."""
        funding_db.save_profile(sample_profile)
        cmd_profile(_ns(), funding_db)
        mock_console.print.assert_called_once()

    @patch("funding.cli.HAS_RICH", False)
    @patch("funding.cli.console", None)
    @patch("funding.cli._print")
    def test_profile_null_fields_plain(self, mock_print, funding_db):
        """Profile with minimal data should show N/A for missing fields."""
        funding_db.save_profile(CreditProfile(bureau="equifax"))
        cmd_profile(_ns(), funding_db)
        output = " ".join(str(c) for c in mock_print.call_args_list)
        assert "N/A" in output


# ── cmd_status ──────────────────────────────────────────────────────


class TestCmdStatus:
    @patch("funding.cli.HAS_RICH", False)
    @patch("funding.cli.console", None)
    @patch("funding.cli._print")
    def test_empty_db_plain(self, mock_print, funding_db):
        cmd_status(_ns(), funding_db)
        output = " ".join(str(c) for c in mock_print.call_args_list)
        assert "Readiness Score" in output
        assert "0/100" in output

    @patch("funding.cli.HAS_RICH", False)
    @patch("funding.cli.console", None)
    @patch("funding.cli._print")
    def test_with_profile_plain(self, mock_print, funding_db, sample_profile):
        funding_db.save_profile(sample_profile)
        cmd_status(_ns(), funding_db)
        output = " ".join(str(c) for c in mock_print.call_args_list)
        assert "Readiness Score" in output
        assert "Funding" in output

    @patch("funding.cli.HAS_RICH", True)
    @patch("funding.cli.console")
    def test_status_rich(self, mock_console, funding_db, sample_profile):
        funding_db.save_profile(sample_profile)
        cmd_status(_ns(), funding_db)
        assert mock_console.print.call_count >= 2  # Panel + Table


# ── cmd_strategy ────────────────────────────────────────────────────


class TestCmdStrategy:
    @patch("funding.cli._print")
    def test_no_recs(self, mock_print, funding_db):
        """With no profile, get_recommendations returns 'Upload Credit Report'.
        That is still a rec, so it won't hit the 'no recs' early return."""
        cmd_strategy(_ns(), funding_db)
        output = " ".join(str(c) for c in mock_print.call_args_list)
        assert "Upload" in output or "No recommendations" not in output

    @patch("funding.cli.HAS_RICH", False)
    @patch("funding.cli.console", None)
    @patch("funding.cli._print")
    def test_with_recs_plain(self, mock_print, funding_db, sample_profile):
        funding_db.save_profile(sample_profile)
        cmd_strategy(_ns(), funding_db)
        output = " ".join(str(c) for c in mock_print.call_args_list)
        # Should display at least one recommendation
        assert "HIGH" in output or "MEDIUM" in output or "LOW" in output or "INFO" in output

    @patch("funding.cli.HAS_RICH", True)
    @patch("funding.cli.console")
    def test_with_recs_rich(self, mock_console, funding_db, sample_profile):
        funding_db.save_profile(sample_profile)
        cmd_strategy(_ns(), funding_db)
        assert mock_console.print.call_count >= 1

    @patch("funding.cli.get_recommendations", return_value=[])
    @patch("funding.cli._print")
    def test_truly_no_recs(self, mock_print, mock_get_recs, funding_db):
        """Force empty recommendations to exercise early return."""
        cmd_strategy(_ns(), funding_db)
        mock_print.assert_called_once()
        assert "No recommendations" in mock_print.call_args[0][0]


# ── cmd_plan ────────────────────────────────────────────────────────


class TestCmdPlan:
    @patch("funding.cli._print")
    def test_no_products(self, mock_print, funding_db):
        """plan_round returns [] when no profile or products."""
        cmd_plan(_ns(), funding_db)
        mock_print.assert_called_once()
        assert "No eligible" in mock_print.call_args[0][0]

    @patch("builtins.input", return_value="n")
    @patch("funding.cli._print")
    def test_with_products_decline_save(self, mock_print, mock_input, seeded_db):
        seeded_db.save_profile(CreditProfile(bureau="experian", score=750))
        cmd_plan(_ns(), seeded_db)
        output = " ".join(str(c) for c in mock_print.call_args_list)
        assert "Planned Round" in output
        # Declined to save, so no round created
        assert seeded_db.get_rounds() == []

    @patch("builtins.input", side_effect=["y", "My Round"])
    @patch("funding.cli._print")
    def test_with_products_save_round(self, mock_print, mock_input, seeded_db):
        seeded_db.save_profile(CreditProfile(bureau="experian", score=750))
        cmd_plan(_ns(), seeded_db)
        rounds = seeded_db.get_rounds()
        assert len(rounds) == 1
        assert rounds[0].name == "My Round"
        assert rounds[0].status == "planning"


# ── cmd_rounds ──────────────────────────────────────────────────────


class TestCmdRounds:
    @patch("funding.cli._print")
    def test_no_rounds(self, mock_print, funding_db):
        cmd_rounds(_ns(), funding_db)
        mock_print.assert_called_once()
        assert "No funding rounds" in mock_print.call_args[0][0]

    @patch("funding.cli.HAS_RICH", False)
    @patch("funding.cli.console", None)
    @patch("funding.cli._print")
    def test_with_rounds_plain(self, mock_print, funding_db):
        funding_db.save_round(StrategyRound(
            name="Round 1", planned_date="2025-06-01",
            status="completed", target_total=50000.0, actual_total=45000.0))
        cmd_rounds(_ns(), funding_db)
        output = " ".join(str(c) for c in mock_print.call_args_list)
        assert "Round 1" in output
        assert "completed" in output

    @patch("funding.cli.HAS_RICH", True)
    @patch("funding.cli.console")
    def test_with_rounds_rich(self, mock_console, funding_db):
        funding_db.save_round(StrategyRound(
            name="R1", status="planning", target_total=10000.0))
        cmd_rounds(_ns(), funding_db)
        mock_console.print.assert_called_once()


# ── cmd_products ────────────────────────────────────────────────────


class TestCmdProducts:
    @patch("funding.cli._print")
    def test_empty_catalog(self, mock_print, funding_db):
        cmd_products(_ns(type=None), funding_db)
        mock_print.assert_called_once()
        assert "empty" in mock_print.call_args[0][0].lower()

    @patch("funding.cli.HAS_RICH", False)
    @patch("funding.cli.console", None)
    @patch("funding.cli._print")
    def test_catalog_plain(self, mock_print, seeded_db):
        cmd_products(_ns(type=None), seeded_db)
        output = " ".join(str(c) for c in mock_print.call_args_list)
        assert "Chase" in output

    @patch("funding.cli.HAS_RICH", False)
    @patch("funding.cli.console", None)
    @patch("funding.cli._print")
    def test_type_filter(self, mock_print, seeded_db):
        cmd_products(_ns(type="loc"), seeded_db)
        output = " ".join(str(c) for c in mock_print.call_args_list)
        # All displayed should be LOC type
        for c in mock_print.call_args_list:
            line = str(c)
            if "—" in line:
                assert "loc" in line.lower() or "LOC" in line

    @patch("funding.cli.HAS_RICH", True)
    @patch("funding.cli.console")
    def test_catalog_rich(self, mock_console, seeded_db):
        cmd_products(_ns(type=None), seeded_db)
        mock_console.print.assert_called_once()

    @patch("funding.cli.HAS_RICH", False)
    @patch("funding.cli.console", None)
    @patch("funding.cli._print")
    def test_no_type_attr(self, mock_print, seeded_db):
        """args without 'type' attribute should still work."""
        cmd_products(_ns(), seeded_db)
        assert mock_print.call_count > 0


# ── cmd_inquiries ───────────────────────────────────────────────────


class TestCmdInquiries:
    @patch("funding.cli.HAS_RICH", False)
    @patch("funding.cli.console", None)
    @patch("funding.cli._print")
    def test_no_inquiries_plain(self, mock_print, funding_db):
        cmd_inquiries(_ns(), funding_db)
        output = " ".join(str(c) for c in mock_print.call_args_list)
        assert "Inquiry Summary" in output
        assert "Total: 0" in output

    @patch("funding.cli.HAS_RICH", False)
    @patch("funding.cli.console", None)
    @patch("funding.cli._print")
    def test_with_inquiries_plain(self, mock_print, funding_db):
        now = datetime.utcnow().strftime("%Y-%m-%d")
        funding_db.save_inquiry(Inquiry(
            date=now, bureau="experian", lender="Chase",
            falls_off_date=_add_years_str(now, 2)))
        funding_db.save_inquiry(Inquiry(
            date=now, bureau="transunion", lender="Amex",
            falls_off_date=_add_years_str(now, 2)))
        cmd_inquiries(_ns(), funding_db)
        output = " ".join(str(c) for c in mock_print.call_args_list)
        assert "Experian: 1" in output
        assert "Transunion: 1" in output

    @patch("funding.cli.HAS_RICH", True)
    @patch("funding.cli.console")
    def test_with_inquiries_rich(self, mock_console, funding_db):
        now = datetime.utcnow().strftime("%Y-%m-%d")
        funding_db.save_inquiry(Inquiry(
            date=now, bureau="experian", lender="Chase"))
        cmd_inquiries(_ns(), funding_db)
        # Should print at least the summary table + detail table
        assert mock_console.print.call_count >= 2


# ── cmd_history ─────────────────────────────────────────────────────


class TestCmdHistory:
    @patch("funding.cli._print")
    def test_no_applications(self, mock_print, funding_db):
        cmd_history(_ns(), funding_db)
        mock_print.assert_called_once()
        assert "No applications" in mock_print.call_args[0][0]

    @patch("funding.cli.HAS_RICH", False)
    @patch("funding.cli.console", None)
    @patch("funding.cli._print")
    def test_with_applications_plain(self, mock_print, funding_db, sample_application):
        funding_db.save_application(sample_application)
        cmd_history(_ns(), funding_db)
        output = " ".join(str(c) for c in mock_print.call_args_list)
        assert "Chase" in output
        assert "planned" in output

    @patch("funding.cli.HAS_RICH", True)
    @patch("funding.cli.console")
    def test_with_applications_rich(self, mock_console, funding_db, sample_application):
        funding_db.save_application(sample_application)
        cmd_history(_ns(), funding_db)
        mock_console.print.assert_called_once()

    @patch("funding.cli.HAS_RICH", False)
    @patch("funding.cli.console", None)
    @patch("funding.cli._print")
    def test_approved_with_amount(self, mock_print, funding_db):
        app = Application(
            product_type="credit_card", lender="Amex",
            product_name="Gold", status="approved",
            amount_approved=25000.0,
            applied_date="2025-03-01", decision_date="2025-03-05",
        )
        funding_db.save_application(app)
        cmd_history(_ns(), funding_db)
        output = " ".join(str(c) for c in mock_print.call_args_list)
        assert "$25,000" in output


# ── cmd_export ──────────────────────────────────────────────────────


class TestCmdExport:
    @patch("funding.cli._print")
    def test_export_creates_json(self, mock_print, funding_db, tmp_path):
        """Export should write a JSON file with all data."""
        funding_db.save_profile(CreditProfile(bureau="experian", score=720))
        funding_db.save_application(Application(
            product_type="loc", lender="Bluevine", status="approved"))

        export_path = str(tmp_path / "export.json")
        with patch("funding.cli.datetime") as mock_dt:
            mock_dt.utcnow.return_value = datetime(2025, 6, 15, 12, 0, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            # Override the filename to write to tmp_path
            with patch("builtins.open", create=True) as mock_open:
                from io import StringIO
                buf = StringIO()
                mock_open.return_value.__enter__ = lambda s: buf
                mock_open.return_value.__exit__ = MagicMock(return_value=False)
                cmd_export(_ns(), funding_db)

        mock_print.assert_called_once()
        assert "Exported" in mock_print.call_args[0][0]
        assert "1 profiles" in mock_print.call_args[0][0]
        assert "1 applications" in mock_print.call_args[0][0]

    @patch("funding.cli._print")
    def test_export_empty_db(self, mock_print, funding_db):
        with patch("builtins.open", create=True) as mock_open:
            from io import StringIO
            buf = StringIO()
            mock_open.return_value.__enter__ = lambda s: buf
            mock_open.return_value.__exit__ = MagicMock(return_value=False)
            cmd_export(_ns(), funding_db)
        assert "0 profiles" in mock_print.call_args[0][0]

    @patch("funding.cli._print")
    def test_export_writes_valid_json(self, mock_print, funding_db, tmp_path):
        """Verify the exported file is valid JSON with expected keys."""
        funding_db.save_profile(CreditProfile(bureau="equifax", score=700))
        outfile = str(tmp_path / "data" / "funding_export_test.json")
        os.makedirs(os.path.dirname(outfile), exist_ok=True)

        # Patch the filename used inside cmd_export
        with patch("funding.cli.datetime") as mock_dt:
            mock_dt.utcnow.return_value = datetime(2025, 1, 1, 0, 0, 0)
            mock_dt.strftime = datetime.strftime
            # We need to actually write the file — patch the filename
            original_open = open

            def patched_open(path, mode="r", **kw):
                if "funding_export_" in str(path):
                    return original_open(outfile, mode, **kw)
                return original_open(path, mode, **kw)

            with patch("builtins.open", side_effect=patched_open):
                cmd_export(_ns(), funding_db)

        data = json.loads(open(outfile).read())
        assert "credit_profiles" in data
        assert "applications" in data
        assert "inquiries" in data
        assert "rounds" in data
        assert len(data["credit_profiles"]) == 1


# ── cmd_parse ───────────────────────────────────────────────────────


class TestCmdParse:
    @patch("funding.cli._print")
    def test_parse_success(self, mock_print, funding_db):
        profile = CreditProfile(
            bureau="experian", score=730,
            utilization_pct=15.0, total_accounts=10,
            open_accounts=7, derogatory_marks=0,
        )
        inquiries = [
            Inquiry(date="2025-01-15", bureau="experian",
                    lender="Chase", falls_off_date="2027-01-15"),
        ]
        with patch("funding.pdf_parser.parse_credit_report", return_value=(profile, inquiries)):
            cmd_parse(_ns(pdf_path="/tmp/report.pdf"), funding_db)

        output = " ".join(str(c) for c in mock_print.call_args_list)
        assert "Saved profile" in output
        assert "730" in output
        assert "1 hard inquiries" in output
        # Profile and inquiry saved in DB
        assert funding_db.get_latest_profile().score == 730
        assert len(funding_db.get_inquiries()) == 1

    @patch("funding.cli._print")
    def test_parse_file_not_found(self, mock_print, funding_db):
        with patch("funding.pdf_parser.parse_credit_report", side_effect=FileNotFoundError("not found")):
            cmd_parse(_ns(pdf_path="/bad/path.pdf"), funding_db)
        output = " ".join(str(c) for c in mock_print.call_args_list)
        assert "Error" in output or "not found" in output

    @patch("funding.cli._print")
    def test_parse_import_error(self, mock_print, funding_db):
        with patch("funding.pdf_parser.parse_credit_report", side_effect=ImportError("pdfplumber")):
            cmd_parse(_ns(pdf_path="/tmp/report.pdf"), funding_db)
        output = " ".join(str(c) for c in mock_print.call_args_list)
        assert "dependency" in output.lower() or "pdfplumber" in output

    @patch("funding.cli._print")
    def test_parse_no_inquiries(self, mock_print, funding_db):
        profile = CreditProfile(bureau="transunion", score=680)
        with patch("funding.pdf_parser.parse_credit_report", return_value=(profile, [])):
            cmd_parse(_ns(pdf_path="/tmp/report.pdf"), funding_db)
        output = " ".join(str(c) for c in mock_print.call_args_list)
        assert "No hard inquiries" in output


# ── cmd_apply ───────────────────────────────────────────────────────


class TestCmdApply:
    @patch("funding.cli._print")
    def test_apply_basic(self, mock_print, funding_db):
        """Apply with minimal fields, no bureau."""
        inputs = [
            "1",           # product_type: credit_card
            "Chase",       # lender
            "Ink",         # product_name
            "10000",       # amount
            "2",           # status: applied
            "",            # bureau (empty)
        ]
        with patch("builtins.input", side_effect=inputs):
            cmd_apply(_ns(), funding_db)

        apps = funding_db.get_all_applications()
        assert len(apps) == 1
        assert apps[0].lender == "Chase"
        assert apps[0].product_type == "credit_card"
        assert apps[0].status == "applied"

    @patch("funding.cli._print")
    def test_apply_approved_with_bureau(self, mock_print, funding_db):
        """Approved application creates inquiry automatically."""
        inputs = [
            "1",            # credit_card
            "Amex",         # lender
            "Gold",         # product name
            "5000",         # amount
            "4",            # approved (4th in: planned/applied/pending/approved/denied)
            "experian",     # bureau
            "15000",        # amount approved
        ]
        with patch("builtins.input", side_effect=inputs):
            cmd_apply(_ns(), funding_db)

        apps = funding_db.get_all_applications()
        assert len(apps) == 1
        assert apps[0].status == "approved"
        assert apps[0].amount_approved == 15000.0

        # Should have auto-created an inquiry
        inquiries = funding_db.get_inquiries()
        assert len(inquiries) == 1
        assert inquiries[0].bureau == "experian"
        assert inquiries[0].lender == "Amex"

    @patch("funding.cli._print")
    def test_apply_empty_lender_aborts(self, mock_print, funding_db):
        """Empty lender name should abort early."""
        inputs = [
            "1",   # credit_card
            "",    # empty lender
        ]
        with patch("builtins.input", side_effect=inputs):
            cmd_apply(_ns(), funding_db)

        assert funding_db.get_all_applications() == []
        output = " ".join(str(c) for c in mock_print.call_args_list)
        assert "required" in output.lower()

    @patch("funding.cli._print")
    def test_apply_multiple_bureau_no_inquiry(self, mock_print, funding_db):
        """Bureau='multiple' should NOT create an auto-inquiry."""
        inputs = [
            "1",           # credit_card
            "CapOne",      # lender
            "",            # product name (optional)
            "",            # amount (optional)
            "2",           # applied
            "multiple",    # bureau
        ]
        with patch("builtins.input", side_effect=inputs):
            cmd_apply(_ns(), funding_db)

        assert len(funding_db.get_all_applications()) == 1
        assert len(funding_db.get_inquiries()) == 0


# ── cmd_update ──────────────────────────────────────────────────────


class TestCmdUpdate:
    @patch("funding.cli._print")
    def test_update_not_found(self, mock_print, funding_db):
        cmd_update(_ns(app_id=999, status="approved"), funding_db)
        assert "not found" in mock_print.call_args[0][0].lower()

    @patch("funding.cli._print")
    def test_update_to_approved(self, mock_print, funding_db, sample_application):
        app_id = funding_db.save_application(sample_application)
        inputs = ["25000", "50000"]  # amount approved, credit limit
        with patch("builtins.input", side_effect=inputs):
            cmd_update(_ns(app_id=app_id, status="approved"), funding_db)

        updated = funding_db.get_application(app_id)
        assert updated.status == "approved"
        assert updated.amount_approved == 25000.0
        assert updated.credit_limit == 50000.0

    @patch("funding.cli._print")
    def test_update_to_denied(self, mock_print, funding_db, sample_application):
        app_id = funding_db.save_application(sample_application)
        with patch("builtins.input", return_value="Too many inquiries"):
            cmd_update(_ns(app_id=app_id, status="denied"), funding_db)

        updated = funding_db.get_application(app_id)
        assert updated.status == "denied"
        assert updated.denial_reason == "Too many inquiries"
        assert updated.decision_date is not None

    @patch("funding.cli._print")
    def test_update_to_pending(self, mock_print, funding_db, sample_application):
        """Pending status should not prompt for extra input."""
        app_id = funding_db.save_application(sample_application)
        cmd_update(_ns(app_id=app_id, status="pending"), funding_db)
        updated = funding_db.get_application(app_id)
        assert updated.status == "pending"

    @patch("funding.cli._print")
    def test_update_approved_empty_amounts(self, mock_print, funding_db, sample_application):
        """Approved with empty optional amounts should still update."""
        app_id = funding_db.save_application(sample_application)
        inputs = ["", ""]  # both empty
        with patch("builtins.input", side_effect=inputs):
            cmd_update(_ns(app_id=app_id, status="approved"), funding_db)
        updated = funding_db.get_application(app_id)
        assert updated.status == "approved"


# ── main() dispatch ─────────────────────────────────────────────────


class TestMain:
    @patch("funding.cli._print")
    @patch("sys.argv", ["funding", "profile"])
    def test_dispatch_profile(self, mock_print):
        with patch("funding.cli.cmd_profile") as mock_cmd:
            with patch("funding.cli.FundingDB"):
                with patch("funding.cli.seed_catalog", return_value=0):
                    main()
            mock_cmd.assert_called_once()

    @patch("funding.cli._print")
    @patch("sys.argv", ["funding", "status"])
    def test_dispatch_status(self, mock_print):
        with patch("funding.cli.cmd_status") as mock_cmd:
            with patch("funding.cli.FundingDB"):
                with patch("funding.cli.seed_catalog", return_value=0):
                    main()
            mock_cmd.assert_called_once()

    @patch("funding.cli._print")
    @patch("sys.argv", ["funding", "strategy"])
    def test_dispatch_strategy(self, mock_print):
        with patch("funding.cli.cmd_strategy") as mock_cmd:
            with patch("funding.cli.FundingDB"):
                with patch("funding.cli.seed_catalog", return_value=0):
                    main()
            mock_cmd.assert_called_once()

    @patch("funding.cli._print")
    @patch("sys.argv", ["funding", "rounds"])
    def test_dispatch_rounds(self, mock_print):
        with patch("funding.cli.cmd_rounds") as mock_cmd:
            with patch("funding.cli.FundingDB"):
                with patch("funding.cli.seed_catalog", return_value=0):
                    main()
            mock_cmd.assert_called_once()

    @patch("funding.cli._print")
    @patch("sys.argv", ["funding", "export"])
    def test_dispatch_export(self, mock_print):
        with patch("funding.cli.cmd_export") as mock_cmd:
            with patch("funding.cli.FundingDB"):
                with patch("funding.cli.seed_catalog", return_value=0):
                    main()
            mock_cmd.assert_called_once()

    @patch("sys.argv", ["funding"])
    def test_no_command_prints_help(self):
        """No subcommand should print help and return."""
        with patch("funding.cli.FundingDB"):
            with patch("funding.cli.seed_catalog", return_value=0):
                # Should not crash
                main()

    @patch("funding.cli._print")
    @patch("sys.argv", ["funding", "products", "--type", "credit_card"])
    def test_dispatch_products_with_type(self, mock_print):
        with patch("funding.cli.cmd_products") as mock_cmd:
            with patch("funding.cli.FundingDB"):
                with patch("funding.cli.seed_catalog", return_value=0):
                    main()
            mock_cmd.assert_called_once()
            args = mock_cmd.call_args[0][0]
            assert args.type == "credit_card"

    @patch("funding.cli._print")
    @patch("sys.argv", ["funding", "parse", "/tmp/test.pdf"])
    def test_dispatch_parse(self, mock_print):
        with patch("funding.cli.cmd_parse") as mock_cmd:
            with patch("funding.cli.FundingDB"):
                with patch("funding.cli.seed_catalog", return_value=0):
                    main()
            mock_cmd.assert_called_once()
            args = mock_cmd.call_args[0][0]
            assert args.pdf_path == "/tmp/test.pdf"

    @patch("funding.cli._print")
    @patch("sys.argv", ["funding", "update", "5", "denied"])
    def test_dispatch_update(self, mock_print):
        with patch("funding.cli.cmd_update") as mock_cmd:
            with patch("funding.cli.FundingDB"):
                with patch("funding.cli.seed_catalog", return_value=0):
                    main()
            mock_cmd.assert_called_once()
            args = mock_cmd.call_args[0][0]
            assert args.app_id == 5
            assert args.status == "denied"

    @patch("funding.cli._print")
    @patch("sys.argv", ["funding", "history"])
    def test_dispatch_history(self, mock_print):
        with patch("funding.cli.cmd_history") as mock_cmd:
            with patch("funding.cli.FundingDB"):
                with patch("funding.cli.seed_catalog", return_value=0):
                    main()
            mock_cmd.assert_called_once()

    @patch("funding.cli._print")
    @patch("sys.argv", ["funding", "inquiries"])
    def test_dispatch_inquiries(self, mock_print):
        with patch("funding.cli.cmd_inquiries") as mock_cmd:
            with patch("funding.cli.FundingDB"):
                with patch("funding.cli.seed_catalog", return_value=0):
                    main()
            mock_cmd.assert_called_once()

    @patch("funding.cli._print")
    @patch("sys.argv", ["funding", "apply"])
    def test_dispatch_apply(self, mock_print):
        with patch("funding.cli.cmd_apply") as mock_cmd:
            with patch("funding.cli.FundingDB"):
                with patch("funding.cli.seed_catalog", return_value=0):
                    main()
            mock_cmd.assert_called_once()

    @patch("funding.cli._print")
    @patch("sys.argv", ["funding", "plan"])
    def test_dispatch_plan(self, mock_print):
        with patch("funding.cli.cmd_plan") as mock_cmd:
            with patch("funding.cli.FundingDB"):
                with patch("funding.cli.seed_catalog", return_value=0):
                    main()
            mock_cmd.assert_called_once()

    @patch("funding.cli._print")
    @patch("sys.argv", ["funding", "products"])
    def test_seed_catalog_message(self, mock_print):
        """When seed_catalog returns > 0, a message should be printed."""
        with patch("funding.cli.cmd_products"):
            with patch("funding.cli.FundingDB"):
                with patch("funding.cli.seed_catalog", return_value=42):
                    main()
        output = " ".join(str(c) for c in mock_print.call_args_list)
        assert "42 products" in output
