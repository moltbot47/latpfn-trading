#!/usr/bin/env python3
"""
Business Funding Tracker — Web Dashboard.

Serves a live dashboard at http://localhost:5055 showing credit profile,
applications, strategy recommendations, inquiry management, and round planning.

Usage:
    python scripts/funding_dashboard.py
    python scripts/funding_dashboard.py --port 5055
"""

import argparse
import logging
import os
import platform
import sys
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, Response

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from funding.database import FundingDB
from funding.models import PartnerProgram, Referral, ReferralClient
from funding.product_catalog import seed_catalog, seed_partner_programs
from funding.strategy_engine import get_recommendations, get_readiness_score, plan_round

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB upload limit
db = FundingDB(str(ROOT / "data" / "funding.db"))
seed_catalog(db)
seed_partner_programs(db)

_START_TIME = time.time()
_VERSION = "1.0.0"


# ── Monitoring: Request Logging ──────────────────────────────────────

@app.before_request
def _before_request():
    request._start_time = time.time()


@app.after_request
def _after_request(response):
    # Skip logging for health checks to reduce noise
    if request.path.startswith("/health"):
        return response
    duration_ms = (time.time() - getattr(request, "_start_time", time.time())) * 1000
    logger.info("%s %s %s %.0fms", request.method, request.path,
                response.status_code, duration_ms)
    return response


# ── Monitoring: Error Handlers ───────────────────────────────────────

@app.errorhandler(404)
def _handle_404(e):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(Exception)
def _handle_500(e):
    logger.error("Unhandled exception on %s %s: %s", request.method, request.path,
                 e, exc_info=True)
    return jsonify({"error": "Internal server error"}), 500


# ── Monitoring: Health Endpoints ─────────────────────────────────────

@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "uptime_seconds": round(time.time() - _START_TIME),
        "version": _VERSION,
    })


@app.route("/health/detail")
def health_detail():
    try:
        products = db.product_count()
        partners = db.partner_program_count()
        db_ok = True
    except Exception:
        products = partners = 0
        db_ok = False

    import resource
    mem_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)
    # macOS reports bytes, Linux reports KB
    if platform.system() == "Darwin":
        mem_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)
    else:
        mem_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024

    status = "ok" if db_ok else "degraded"
    return jsonify({
        "status": status,
        "uptime_seconds": round(time.time() - _START_TIME),
        "version": _VERSION,
        "db": {"ok": db_ok, "products": products, "partner_programs": partners},
        "memory_mb": round(mem_mb, 1),
        "python_version": platform.python_version(),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    })


# ── API Endpoints ────────────────────────────────────────────────────

@app.route("/api/summary")
def api_summary():
    summary = db.get_funding_summary()
    readiness = get_readiness_score(db)
    return jsonify({"summary": summary, "readiness": readiness})


@app.route("/api/profile")
def api_profile():
    profile = db.get_latest_profile()
    if not profile:
        return jsonify(None)
    return jsonify(profile.to_dict())


@app.route("/api/applications")
def api_applications():
    apps = db.get_all_applications()
    result = []
    for a in apps:
        d = a.to_dict()
        d["id"] = a.id
        result.append(d)
    return jsonify(result)


@app.route("/api/applications", methods=["POST"])
def api_add_application():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    from funding.models import Application, Inquiry

    lender = (data.get("lender") or "").strip()
    if not lender:
        return jsonify({"error": "lender is required"}), 400
    status = data.get("status", "planned")
    _VALID_APP_STATUSES = {"planned", "applied", "pending", "approved", "denied", "withdrawn"}
    if status not in _VALID_APP_STATUSES:
        return jsonify({"error": f"Invalid status: {status}. Must be one of: {', '.join(sorted(_VALID_APP_STATUSES))}"}), 400

    app_obj = Application(
        product_type=data.get("product_type", "credit_card"),
        lender=lender,
        product_name=data.get("product_name"),
        amount_requested=data.get("amount_requested"),
        amount_approved=data.get("amount_approved"),
        credit_limit=data.get("credit_limit"),
        status=status,
        applied_date=data.get("applied_date"),
        bureau_pulled=data.get("bureau_pulled"),
        personal_guarantee=data.get("personal_guarantee", False),
        notes=data.get("notes"),
    )
    app_id = db.save_application(app_obj)

    # Auto-create inquiry
    if app_obj.status in ("applied", "pending", "approved") and app_obj.bureau_pulled:
        bureau = app_obj.bureau_pulled
        if bureau not in ("multiple", "none", "soft_pull"):
            for b in bureau.split(","):
                b = b.strip().lower()
                if b:
                    inq = Inquiry(
                        date=datetime.utcnow().strftime("%Y-%m-%d"),
                        bureau=b,
                        lender=app_obj.lender,
                        falls_off_date=_add_years(datetime.utcnow().strftime("%Y-%m-%d"), 2),
                        source="manual",
                        application_id=app_id,
                    )
                    db.save_inquiry(inq)

    return jsonify({"id": app_id, "status": "created"})


@app.route("/api/applications/<int:app_id>", methods=["PATCH"])
def api_update_application(app_id):
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    kwargs = {}
    if "status" in data:
        kwargs["status"] = data["status"]
    if "amount_approved" in data:
        kwargs["amount_approved"] = data["amount_approved"]
    if "credit_limit" in data:
        kwargs["credit_limit"] = data["credit_limit"]
    if "denial_reason" in data:
        kwargs["denial_reason"] = data["denial_reason"]
    if "notes" in data:
        kwargs["notes"] = data["notes"]
    if data.get("status") in ("approved", "denied"):
        kwargs["decision_date"] = datetime.utcnow().strftime("%Y-%m-%d")

    db.update_application(app_id, **kwargs)
    return jsonify({"status": "updated"})


@app.route("/api/inquiries")
def api_inquiries():
    inqs = db.get_inquiries()
    counts_12 = db.get_inquiry_counts_by_bureau(12)
    counts_24 = db.get_inquiry_counts_by_bureau(24)
    return jsonify({
        "inquiries": [i.to_dict() for i in inqs],
        "counts_12mo": counts_12,
        "counts_24mo": counts_24,
    })


@app.route("/api/strategy")
def api_strategy():
    recs = get_recommendations(db)
    return jsonify([{
        "priority": r.priority,
        "category": r.category,
        "title": r.title,
        "detail": r.detail,
        "impact": r.impact,
    } for r in recs])


@app.route("/api/round-plan")
def api_round_plan():
    products = plan_round(db)
    result = []
    for p in products:
        result.append({
            "lender": p.lender,
            "product_name": p.product_name,
            "product_type": p.product_type,
            "min_score": p.min_score,
            "typical_limit_low": p.typical_limit_low,
            "typical_limit_high": p.typical_limit_high,
            "bureau_pulled": p.bureau_pulled,
            "inquiry_sensitive": p.inquiry_sensitive,
            "notes": p.notes,
            "category": p.category,
            "reference_url": p.reference_url,
        })
    return jsonify(result)


@app.route("/api/products")
def api_products():
    ptype = request.args.get("type")
    products = db.get_products(product_type=ptype)
    result = []
    for p in products:
        result.append({
            "id": p.id,
            "lender": p.lender,
            "product_name": p.product_name,
            "product_type": p.product_type,
            "min_score": p.min_score,
            "typical_limit_low": p.typical_limit_low,
            "typical_limit_high": p.typical_limit_high,
            "bureau_pulled": p.bureau_pulled,
            "inquiry_sensitive": p.inquiry_sensitive,
            "personal_guarantee": p.personal_guarantee,
            "intro_apr": p.intro_apr,
            "intro_period_months": p.intro_period_months,
            "annual_fee": p.annual_fee,
            "category": p.category,
            "notes": p.notes,
            "reference_url": p.reference_url,
            "limit_source_url": p.limit_source_url,
            "docs_level": p.docs_level,
            "startup_grade": p.startup_grade,
            "min_time_months": p.min_time_months,
            "max_line": p.max_line,
            "lender_type": p.lender_type,
            "has_referral": p.has_referral,
            "referral_commission_type": p.referral_commission_type,
            "referral_commission_value": p.referral_commission_value,
            "referral_commission_display": p.referral_commission_display,
            "referral_url": p.referral_url,
            "referral_requires_license": p.referral_requires_license,
        })
    return jsonify(result)


@app.route("/api/parse", methods=["POST"])
def api_parse_pdf():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    f = request.files["file"]
    if not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Must be a PDF file"}), 400

    import tempfile
    from werkzeug.utils import secure_filename
    from funding.pdf_parser import parse_credit_report_full, analyze_credit_health

    safe_filename = secure_filename(f.filename) or "upload.pdf"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp_path = tmp.name
        f.save(tmp_path)
        result = parse_credit_report_full(tmp_path)
        profile = result["profile"]
        inquiries = result["inquiries"]
        profile.pdf_filename = safe_filename
        profile_id = db.save_profile_with_inquiries(profile, inquiries)

        # Credit health analysis
        health = analyze_credit_health(profile)

        # Product eligibility
        from funding.strategy_engine import _get_eligible_products
        all_products = db.get_products()
        all_apps = db.get_all_applications()
        active_inqs = db.get_inquiries(active_only=True)
        eligible = _get_eligible_products(profile, active_inqs, all_apps, all_products)
        eligible_by_type = {}
        for p in eligible:
            eligible_by_type[p.product_type] = eligible_by_type.get(p.product_type, 0) + 1

        # Readiness score
        readiness = get_readiness_score(db)

        # Comparison to previous profile
        previous = None
        all_profiles = db.get_all_profiles()
        if len(all_profiles) > 1:
            prev_profile = all_profiles[1]  # second most recent (first is the one we just saved)
            previous = {
                "score_change": (profile.score or 0) - (prev_profile.score or 0) if profile.score and prev_profile.score else None,
                "utilization_change": round((profile.utilization_pct or 0) - (prev_profile.utilization_pct or 0), 1) if profile.utilization_pct is not None and prev_profile.utilization_pct is not None else None,
                "prev_score": prev_profile.score,
                "prev_utilization": prev_profile.utilization_pct,
                "prev_bureau": prev_profile.bureau,
                "prev_date": prev_profile.parsed_at[:10],
                "days_since": None,
            }
            try:
                from datetime import datetime
                prev_dt = datetime.fromisoformat(prev_profile.parsed_at)
                curr_dt = datetime.fromisoformat(profile.parsed_at)
                previous["days_since"] = (curr_dt - prev_dt).days
            except Exception:
                pass

        # Build profile dict (exclude raw text from response)
        profile_dict = profile.to_dict()
        profile_dict.pop("raw_extracted_text", None)

        return jsonify({
            "profile_id": profile_id,
            "bureau": profile.bureau,
            "profile": profile_dict,
            "inquiries": [{"lender": i.lender, "date": i.date, "bureau": i.bureau,
                          "falls_off": i.falls_off_date} for i in inquiries],
            "extraction": result["extraction"],
            "field_details": result["field_details"],
            "analysis": health,
            "eligibility": {
                "total_eligible": len(eligible),
                "total_products": len(all_products),
                "by_type": eligible_by_type,
                "top_products": [{"lender": p.lender, "name": p.product_name, "type": p.product_type,
                                  "limit_high": p.typical_limit_high} for p in eligible[:5]],
            },
            "readiness": readiness,
            "previous": previous,
        })
    except Exception as e:
        import traceback
        logger.error("Parse failed: %s", traceback.format_exc())
        return jsonify({"error": str(e)}), 500
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@app.route("/api/profile/history")
def api_profile_history():
    profiles = db.get_all_profiles()
    result = []
    for p in profiles:
        d = p.to_dict()
        d.pop("raw_extracted_text", None)
        d["id"] = p.id
        result.append(d)
    return jsonify(result)


# ── Referral Endpoints ────────────────────────────────────────────────

@app.route("/api/referral-clients")
def api_referral_clients():
    clients = db.get_referral_clients()
    result = []
    for c in clients:
        d = c.to_dict()
        d["id"] = c.id
        result.append(d)
    return jsonify(result)


@app.route("/api/referral-clients", methods=["POST"])
def api_create_referral_client():
    data = request.get_json()
    if not data or not data.get("name"):
        return jsonify({"error": "Client name is required"}), 400
    client = ReferralClient(
        name=data["name"],
        email=data.get("email"),
        phone=data.get("phone"),
        notes=data.get("notes"),
    )
    client_id = db.save_referral_client(client)
    return jsonify({"id": client_id, "name": client.name}), 201


@app.route("/api/referrals")
def api_referrals():
    status = request.args.get("status")
    referrals = db.get_referrals(status=status)
    result = []
    for r in referrals:
        d = r.to_dict()
        d["id"] = r.id
        result.append(d)
    return jsonify(result)


@app.route("/api/referrals", methods=["POST"])
def api_create_referral():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body required"}), 400
    required = ["client_id", "product_id", "referral_date"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"{field} is required"}), 400

    # Auto-calculate expected commission from product data
    expected_commission = data.get("expected_commission")
    if expected_commission is None and data.get("funded_amount"):
        products = db.get_referral_products()
        for p in products:
            if p.id == int(data["product_id"]):
                if p.referral_commission_type == "percentage" and p.referral_commission_value:
                    expected_commission = round(float(data["funded_amount"]) * p.referral_commission_value / 100, 2)
                elif p.referral_commission_type in ("flat_fee", "recurring") and p.referral_commission_value:
                    expected_commission = p.referral_commission_value
                break

    ref = Referral(
        client_id=int(data["client_id"]),
        product_id=int(data["product_id"]),
        referral_date=data["referral_date"],
        status=data.get("status", "submitted"),
        funded_amount=data.get("funded_amount"),
        expected_commission=expected_commission,
        actual_commission=data.get("actual_commission"),
        commission_paid_date=data.get("commission_paid_date"),
        notes=data.get("notes"),
    )
    ref_id = db.save_referral(ref)
    return jsonify({"id": ref_id}), 201


@app.route("/api/referrals/<int:ref_id>", methods=["PATCH"])
def api_update_referral(ref_id):
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body required"}), 400

    allowed = {"status", "funded_amount", "expected_commission", "actual_commission",
               "commission_paid_date", "notes"}
    updates = {k: v for k, v in data.items() if k in allowed}

    # Auto-calculate expected commission when funded_amount changes
    if "funded_amount" in updates and "expected_commission" not in updates:
        ref = db.get_referral_by_id(ref_id)
        if ref and hasattr(ref, '_commission_type') and ref._commission_type:
            if ref._commission_type == "percentage" and ref._commission_value:
                updates["expected_commission"] = round(
                    float(updates["funded_amount"]) * ref._commission_value / 100, 2)
            elif ref._commission_type in ("flat_fee", "recurring") and ref._commission_value:
                updates["expected_commission"] = ref._commission_value

    if not updates:
        return jsonify({"error": "No valid fields to update"}), 400
    ok = db.update_referral(ref_id, **updates)
    if ok:
        return jsonify({"ok": True})
    return jsonify({"error": "Update failed"}), 500


@app.route("/api/referrals/summary")
def api_referral_summary():
    summary = db.get_referral_summary()
    return jsonify(summary)


@app.route("/api/referral-products")
def api_referral_products():
    products = db.get_referral_products()
    result = []
    for p in products:
        result.append({
            "id": p.id,
            "lender": p.lender,
            "product_name": p.product_name,
            "product_type": p.product_type,
            "referral_commission_type": p.referral_commission_type,
            "referral_commission_value": p.referral_commission_value,
            "referral_commission_display": p.referral_commission_display,
            "referral_requires_license": p.referral_requires_license,
        })
    return jsonify(result)


# ── Partner Program Endpoints ─────────────────────────────────────────

@app.route("/api/partner-programs")
def api_partner_programs():
    status = request.args.get("status")
    programs = db.get_partner_programs(status=status)
    result = []
    for p in programs:
        d = p.to_dict()
        d["id"] = p.id
        result.append(d)
    return jsonify(result)


@app.route("/api/partner-programs", methods=["POST"])
def api_create_partner_program():
    data = request.get_json()
    if not data or not data.get("lender") or not data.get("program_name"):
        return jsonify({"error": "lender and program_name are required"}), 400
    prog = PartnerProgram(
        lender=data["lender"],
        program_name=data["program_name"],
        program_type=data.get("program_type", "partner"),
        status=data.get("status", "not_started"),
        signup_url=data.get("signup_url"),
        portal_url=data.get("portal_url"),
        referral_link=data.get("referral_link"),
        contact_name=data.get("contact_name"),
        contact_email=data.get("contact_email"),
        commission_display=data.get("commission_display"),
        commission_type=data.get("commission_type"),
        has_api=bool(data.get("has_api", False)),
        applied_date=data.get("applied_date"),
        approved_date=data.get("approved_date"),
        notes=data.get("notes"),
        priority=data.get("priority", 3),
    )
    prog_id = db.save_partner_program(prog)
    return jsonify({"id": prog_id}), 201


@app.route("/api/partner-programs/<int:prog_id>", methods=["PATCH"])
def api_update_partner_program(prog_id):
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body required"}), 400

    allowed = {"status", "portal_url", "referral_link", "contact_name",
               "contact_email", "notes", "applied_date", "approved_date",
               "signup_url", "commission_display", "commission_type",
               "has_api", "priority", "program_type"}
    updates = {k: v for k, v in data.items() if k in allowed}

    # Auto-set applied_date when status changes to "applied"
    if data.get("status") == "applied" and "applied_date" not in updates:
        updates["applied_date"] = datetime.utcnow().strftime("%Y-%m-%d")
    # Auto-set approved_date when status changes to "active"
    if data.get("status") == "active" and "approved_date" not in updates:
        updates["approved_date"] = datetime.utcnow().strftime("%Y-%m-%d")

    if not updates:
        return jsonify({"error": "No valid fields to update"}), 400
    ok = db.update_partner_program(prog_id, **updates)
    if ok:
        return jsonify({"ok": True})
    return jsonify({"error": "Update failed"}), 500


@app.route("/api/partner-programs/summary")
def api_partner_program_summary():
    summary = db.get_partner_program_summary()
    return jsonify(summary)


# ── Main Page ────────────────────────────────────────────────────────

@app.route("/")
def index():
    return Response(DASHBOARD_HTML, mimetype="text/html")


def _add_years(date_str, years):
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    try:
        return dt.replace(year=dt.year + years).strftime("%Y-%m-%d")
    except ValueError:
        return dt.replace(year=dt.year + years, day=28).strftime("%Y-%m-%d")


# ── Embedded HTML ────────────────────────────────────────────────────

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Business Funding Tracker</title>
<style>
:root {
  --bg: #0d1117;
  --surface: #161b22;
  --surface2: #1c2333;
  --border: #30363d;
  --text: #e6edf3;
  --text2: #8b949e;
  --green: #3fb950;
  --yellow: #d29922;
  --red: #f85149;
  --blue: #58a6ff;
  --purple: #bc8cff;
  --orange: #d18616;
}
* { margin:0; padding:0; box-sizing:border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
  background: var(--bg); color: var(--text);
  line-height: 1.5;
}
.container { max-width: 1400px; margin: 0 auto; padding: 20px; }
h1 { font-size: 24px; margin-bottom: 4px; }
h2 { font-size: 18px; margin-bottom: 12px; color: var(--blue); }
.subtitle { color: var(--text2); font-size: 14px; margin-bottom: 24px; }

/* Tabs */
.tabs { display: flex; gap: 2px; margin-bottom: 20px; border-bottom: 1px solid var(--border); }
.tab {
  padding: 10px 20px; cursor: pointer;
  color: var(--text2); border-bottom: 2px solid transparent;
  font-size: 14px; font-weight: 500; transition: all 0.2s;
  background: none; border-top: none; border-left: none; border-right: none;
}
.tab:hover { color: var(--text); }
.tab.active { color: var(--blue); border-bottom-color: var(--blue); }
.tab-content { display: none; }
.tab-content.active { display: block; }

/* Cards */
.grid { display: grid; gap: 16px; margin-bottom: 20px; }
.grid-4 { grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); }
.grid-3 { grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
.grid-2 { grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); }
.card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 16px;
}
.card-title { font-size: 12px; color: var(--text2); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }
.card-value { font-size: 28px; font-weight: 700; }
.card-sub { font-size: 12px; color: var(--text2); margin-top: 2px; }

/* Progress bar */
.progress-bar {
  width: 100%; height: 8px; background: var(--surface2);
  border-radius: 4px; overflow: hidden; margin-top: 8px;
}
.progress-fill {
  height: 100%; border-radius: 4px; transition: width 0.5s;
}

/* Tables */
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th {
  text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border);
  color: var(--text2); font-weight: 600; font-size: 12px; text-transform: uppercase;
}
td { padding: 10px 12px; border-bottom: 1px solid var(--border); }
tr:hover { background: var(--surface2); }

/* Badges */
.badge {
  display: inline-block; padding: 2px 8px; border-radius: 12px;
  font-size: 11px; font-weight: 600; text-transform: uppercase;
}
.badge-green { background: rgba(63,185,80,0.15); color: var(--green); }
.badge-yellow { background: rgba(210,153,34,0.15); color: var(--yellow); }
.badge-red { background: rgba(248,81,73,0.15); color: var(--red); }
.badge-blue { background: rgba(88,166,255,0.15); color: var(--blue); }
.badge-purple { background: rgba(188,140,255,0.15); color: var(--purple); }
.badge-dim { background: rgba(139,148,158,0.15); color: var(--text2); }

/* Strategy cards */
.strategy-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 16px; margin-bottom: 12px;
}
.strategy-card.high { border-left: 3px solid var(--red); }
.strategy-card.medium { border-left: 3px solid var(--yellow); }
.strategy-card.low { border-left: 3px solid var(--green); }
.strategy-title { font-weight: 600; margin-bottom: 6px; }
.strategy-detail { color: var(--text2); font-size: 13px; white-space: pre-line; }
.strategy-impact { font-size: 11px; text-transform: uppercase; font-weight: 700; margin-right: 8px; }

/* Round plan */
.plan-item {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 14px; margin-bottom: 8px;
  display: flex; align-items: center; gap: 14px;
}
.plan-number {
  width: 32px; height: 32px; border-radius: 50%; background: var(--blue);
  color: var(--bg); display: flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 14px; flex-shrink: 0;
}
.plan-detail { flex: 1; }
.plan-lender { font-weight: 600; }
.plan-meta { font-size: 12px; color: var(--text2); }
.plan-limit { font-weight: 600; color: var(--green); }

/* Bureau bars */
.bureau-bar-container { margin-bottom: 12px; }
.bureau-label { display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 4px; }
.bureau-bar { height: 20px; background: var(--surface2); border-radius: 4px; overflow: hidden; }
.bureau-fill { height: 100%; border-radius: 4px; transition: width 0.4s; }

/* Form */
.form-group { margin-bottom: 14px; }
.form-group label { display: block; font-size: 13px; color: var(--text2); margin-bottom: 4px; }
.form-group input, .form-group select {
  width: 100%; padding: 8px 12px; background: var(--surface2);
  border: 1px solid var(--border); border-radius: 6px; color: var(--text);
  font-size: 14px;
}
.form-group select { cursor: pointer; }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.btn {
  padding: 10px 20px; border-radius: 6px; border: none; cursor: pointer;
  font-size: 14px; font-weight: 600; transition: all 0.2s;
}
.btn-primary { background: var(--blue); color: var(--bg); }
.btn-primary:hover { opacity: 0.9; }
.btn-green { background: var(--green); color: var(--bg); }
.btn-green:hover { opacity: 0.9; }

/* Upload */
.upload-zone {
  border: 2px dashed var(--border); border-radius: 8px; padding: 40px;
  text-align: center; cursor: pointer; transition: all 0.2s;
}
.upload-zone:hover { border-color: var(--blue); background: var(--surface); }
.upload-zone.dragover { border-color: var(--green); background: rgba(63,185,80,0.05); }
.upload-icon { font-size: 36px; margin-bottom: 8px; }
.upload-text { color: var(--text2); font-size: 14px; }

/* Toast */
.toast {
  position: fixed; bottom: 20px; right: 20px; padding: 12px 20px;
  border-radius: 8px; font-size: 14px; font-weight: 500; z-index: 1000;
  animation: slideIn 0.3s ease; display: none;
}
.toast.success { background: var(--green); color: var(--bg); }
.toast.error { background: var(--red); color: white; }
@keyframes slideIn { from { transform: translateX(100px); opacity: 0; } to { transform: none; opacity: 1; } }

.empty-state { text-align: center; padding: 40px; color: var(--text2); }

/* Filter chips (Amazon-style) */
.filter-bar { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; align-items: center; }
.filter-chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 5px 12px; border-radius: 20px; font-size: 12px; font-weight: 500;
  cursor: pointer; transition: all 0.15s; border: 1px solid var(--border);
  background: var(--surface); color: var(--text2);
}
.filter-chip:hover { border-color: var(--blue); color: var(--text); }
.filter-chip.active { background: rgba(88,166,255,0.15); border-color: var(--blue); color: var(--blue); }
.filter-chip .chip-x { font-size: 14px; line-height: 1; margin-left: 2px; opacity: 0.6; }
.filter-chip .chip-x:hover { opacity: 1; }
.filter-chip-count { font-size: 10px; background: var(--surface2); border-radius: 8px; padding: 1px 6px; margin-left: 2px; }

/* View tabs */
.view-tabs { display: flex; gap: 4px; margin-bottom: 12px; }
.view-tab {
  padding: 6px 14px; border-radius: 6px; font-size: 12px; font-weight: 500;
  cursor: pointer; border: 1px solid var(--border); background: var(--surface); color: var(--text2);
  transition: all 0.15s;
}
.view-tab:hover { border-color: var(--blue); color: var(--text); }
.view-tab.active { background: var(--blue); border-color: var(--blue); color: var(--bg); }

/* Search input */
.search-box {
  padding: 8px 14px; border-radius: 8px; border: 1px solid var(--border);
  background: var(--surface2); color: var(--text); font-size: 14px; width: 280px;
  transition: border-color 0.2s;
}
.search-box:focus { outline: none; border-color: var(--blue); }
.search-box::placeholder { color: var(--text2); }

/* AG Grid dark overrides */
.ag-theme-alpine-dark {
  --ag-background-color: var(--surface) !important;
  --ag-header-background-color: var(--surface2) !important;
  --ag-odd-row-background-color: rgba(22,27,34,0.5) !important;
  --ag-row-hover-color: rgba(88,166,255,0.08) !important;
  --ag-border-color: var(--border) !important;
  --ag-header-foreground-color: var(--text2) !important;
  --ag-foreground-color: var(--text) !important;
  --ag-secondary-foreground-color: var(--text2) !important;
  --ag-range-selection-border-color: var(--blue) !important;
  --ag-selected-row-background-color: rgba(88,166,255,0.12) !important;
  --ag-input-focus-border-color: var(--blue) !important;
  --ag-checkbox-checked-color: var(--blue) !important;
  --ag-filter-active-color: var(--blue) !important;
  --ag-font-size: 13px !important;
  --ag-row-height: 42px !important;
  --ag-header-height: 40px !important;
  border-radius: 8px; overflow: hidden;
  border: 1px solid var(--border);
}
.ag-theme-alpine-dark .ag-header-cell-label { font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.3px; }
.ag-theme-alpine-dark .ag-header-cell { padding: 0 12px; }
.ag-theme-alpine-dark .ag-cell { padding: 0 12px; display: flex; align-items: center; }
.ag-theme-alpine-dark .ag-filter-toolpanel { background: var(--surface); }
.ag-theme-alpine-dark .ag-popup { background: var(--surface) !important; border: 1px solid var(--border) !important; border-radius: 8px !important; }
.ag-theme-alpine-dark .ag-menu { background: var(--surface) !important; border: 1px solid var(--border) !important; }
.ag-theme-alpine-dark .ag-filter { background: var(--surface) !important; }
.ag-theme-alpine-dark input[class^="ag-"] { background: var(--surface2) !important; color: var(--text) !important; border-color: var(--border) !important; }

/* Stat pills row */
.stats-row { display: flex; gap: 12px; margin-bottom: 14px; align-items: center; }
.stat-pill {
  font-size: 12px; color: var(--text2); background: var(--surface); border: 1px solid var(--border);
  padding: 4px 12px; border-radius: 12px;
}
.stat-pill strong { color: var(--text); }
</style>
<!-- AG Grid Community Edition (same library used by Bloomberg, Goldman Sachs, JPMorgan) -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/ag-grid-community@31.0.3/styles/ag-grid.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/ag-grid-community@31.0.3/styles/ag-theme-alpine.css">
<script src="https://cdn.jsdelivr.net/npm/ag-grid-community@31.0.3/dist/ag-grid-community.min.noStyle.js"></script>
</head>
<body>
<div class="container">
  <h1>Business Funding Tracker</h1>
  <p class="subtitle">Credit optimization & application workflow management</p>

  <div class="tabs">
    <button class="tab active" onclick="showTab('overview',event)">Overview</button>
    <button class="tab" onclick="showTab('strategy',event)">Strategy</button>
    <button class="tab" onclick="showTab('applications',event)">Applications</button>
    <button class="tab" onclick="showTab('inquiries',event)">Inquiries</button>
    <button class="tab" onclick="showTab('round',event)">Round Plan</button>
    <button class="tab" onclick="showTab('products',event)">Products</button>
    <button class="tab" onclick="showTab('upload',event)">Upload Report</button>
    <button class="tab" onclick="showTab('referrals',event)">Referrals</button>
    <button class="tab" onclick="showTab('partners',event)">Partners</button>
  </div>

  <!-- OVERVIEW TAB -->
  <div id="tab-overview" class="tab-content active">
    <div class="grid grid-4" id="summary-cards"></div>
    <div class="grid grid-2">
      <div class="card" id="readiness-card"></div>
      <div class="card" id="profile-card"></div>
    </div>
  </div>

  <!-- STRATEGY TAB -->
  <div id="tab-strategy" class="tab-content">
    <h2>Strategy Recommendations</h2>
    <div id="strategy-list"></div>
  </div>

  <!-- APPLICATIONS TAB -->
  <div id="tab-applications" class="tab-content">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
      <h2 style="margin:0">Applications</h2>
      <button class="btn btn-primary" onclick="showAddForm()">+ New Application</button>
    </div>
    <div id="add-form" style="display:none" class="card" style="margin-bottom:16px;"></div>
    <table id="applications-table">
      <thead>
        <tr><th>#</th><th>Lender</th><th>Product</th><th>Type</th><th>Status</th><th>Amount</th><th>Bureau</th><th>Date</th><th>Actions</th></tr>
      </thead>
      <tbody id="applications-body"></tbody>
    </table>
    <div id="applications-empty" class="empty-state" style="display:none">No applications yet. Click "+ New Application" to get started.</div>
  </div>

  <!-- INQUIRIES TAB -->
  <div id="tab-inquiries" class="tab-content">
    <h2>Hard Inquiry Breakdown</h2>
    <div class="grid grid-2">
      <div class="card">
        <h2>By Bureau (12 Months)</h2>
        <div id="bureau-bars"></div>
      </div>
      <div class="card">
        <h2>Inquiry Timeline</h2>
        <table>
          <thead><tr><th>Date</th><th>Bureau</th><th>Lender</th><th>Falls Off</th></tr></thead>
          <tbody id="inquiries-body"></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- ROUND PLAN TAB -->
  <div id="tab-round" class="tab-content">
    <h2>Next Funding Round — Optimal Application Order</h2>
    <p class="subtitle">Apply in this exact order. Inquiry-sensitive lenders first, then stack by bureau.</p>
    <div id="round-plan"></div>
  </div>

  <!-- PRODUCTS TAB -->
  <div id="tab-products" class="tab-content">
    <!-- Header row: title + search -->
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
      <h2 style="margin:0">Product Catalog</h2>
      <input type="text" class="search-box" id="grid-search" placeholder="Search all products..." oninput="onGridSearch(this.value)">
    </div>

    <!-- Saved view tabs (Airtable-style) -->
    <div class="view-tabs" id="view-tabs">
      <button class="view-tab active" onclick="setView('all',event)">All</button>
      <button class="view-tab" onclick="setView('credit_card',event)">Credit Cards</button>
      <button class="view-tab" onclick="setView('loc',event)">Lines of Credit</button>
      <button class="view-tab" onclick="setView('term_loan',event)">Term Loans</button>
      <button class="view-tab" onclick="setView('sba',event)">SBA Loans</button>
      <button class="view-tab" onclick="setView('balance_transfer',event)">0% APR</button>
      <button class="view-tab" onclick="setView('no_pg',event)">No PG</button>
      <button class="view-tab" onclick="setView('no_pull',event)">No Credit Pull</button>
      <button class="view-tab" onclick="setView('startup',event)">Startup Friendly</button>
      <button class="view-tab" onclick="setView('credit_union',event)">Credit Unions</button>
      <button class="view-tab" onclick="setView('fintech',event)">Fintech</button>
      <button class="view-tab" onclick="setView('referral',event)" style="border-color:rgba(63,185,80,0.3);color:var(--green);">Referral Partners</button>
    </div>

    <!-- Amazon-style faceted filter chips -->
    <div class="filter-bar" id="filter-chips"></div>

    <!-- Stats row -->
    <div class="stats-row" id="stats-row"></div>

    <!-- AG Grid -->
    <div id="product-grid" class="ag-theme-alpine-dark" style="width:100%;height:600px;"></div>
  </div>

  <!-- UPLOAD TAB -->
  <div id="tab-upload" class="tab-content">
    <h2>Upload Credit Report PDF</h2>
    <p class="subtitle">Drop an Experian, TransUnion, Equifax, or Credit Karma PDF to auto-parse and analyze your profile.</p>
    <div class="upload-zone" id="upload-zone" onclick="document.getElementById('file-input').click()">
      <div class="upload-icon">&#128196;</div>
      <div class="upload-text">Click or drag & drop a credit report PDF</div>
      <input type="file" id="file-input" accept=".pdf" style="display:none" onchange="uploadFile(this.files[0])">
    </div>
    <!-- Full analysis appears here after upload -->
    <div id="upload-analysis" style="display:none;margin-top:20px;"></div>
  </div>

  <!-- REFERRALS TAB -->
  <div id="tab-referrals" class="tab-content">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
      <h2 style="margin:0">Referral Revenue Tracker</h2>
      <button class="btn btn-primary" onclick="showReferralForm()">+ New Referral</button>
    </div>

    <!-- Summary Cards -->
    <div class="grid grid-4" id="referral-summary-cards"></div>

    <!-- Add Referral Form (hidden) -->
    <div id="referral-form" style="display:none;margin-bottom:20px;" class="card">
      <h2 style="margin-bottom:12px;">Submit Referral</h2>
      <div class="form-row">
        <div class="form-group">
          <label>Client</label>
          <select id="ref-client-select" onchange="onRefClientChange(this.value)">
            <option value="">Select client...</option>
            <option value="__new">+ New Client</option>
          </select>
        </div>
        <div class="form-group">
          <label>Product (Referral Partners Only)</label>
          <select id="ref-product-select" onchange="onRefProductChange(this.value)">
            <option value="">Select product...</option>
          </select>
        </div>
      </div>
      <div id="new-client-fields" style="display:none;">
        <div class="form-row">
          <div class="form-group"><label>Name</label><input type="text" id="ref-client-name"></div>
          <div class="form-group"><label>Email</label><input type="email" id="ref-client-email"></div>
        </div>
        <div class="form-row">
          <div class="form-group"><label>Phone</label><input type="text" id="ref-client-phone"></div>
          <div class="form-group"><label>Notes</label><input type="text" id="ref-client-notes"></div>
        </div>
      </div>
      <div id="ref-commission-info" style="display:none;margin-bottom:12px;padding:10px;background:var(--surface2);border-radius:6px;font-size:13px;"></div>
      <div class="form-row">
        <div class="form-group"><label>Referral Date</label><input type="date" id="ref-date"></div>
        <div class="form-group"><label>Notes</label><input type="text" id="ref-notes" placeholder="Optional notes"></div>
      </div>
      <div style="display:flex;gap:8px;margin-top:8px;">
        <button class="btn btn-green" onclick="submitReferral()">Submit Referral</button>
        <button class="btn" style="background:var(--surface2);color:var(--text);" onclick="$('referral-form').style.display='none'">Cancel</button>
      </div>
    </div>

    <!-- Referrals AG Grid -->
    <div id="referral-grid" class="ag-theme-alpine-dark" style="width:100%;height:400px;margin-bottom:20px;"></div>

    <!-- Commission Breakdown -->
    <h2 style="margin-bottom:12px;">Commission by Lender</h2>
    <div id="commission-breakdown" class="grid" style="grid-template-columns:repeat(auto-fit, minmax(220px, 1fr));margin-bottom:20px;"></div>
  </div>

  <!-- PARTNERS TAB -->
  <div id="tab-partners" class="tab-content">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
      <h2 style="margin:0">Partner Onboarding Tracker</h2>
      <button class="btn btn-primary" onclick="showPartnerForm()">+ Add Partner</button>
    </div>

    <!-- Summary Cards -->
    <div class="grid grid-4" id="partner-summary-cards"></div>

    <!-- Filter Chips -->
    <div class="filter-bar" id="partner-filter-chips"></div>

    <!-- Partner AG Grid -->
    <div id="partner-grid" class="ag-theme-alpine-dark" style="width:100%;height:500px;margin-bottom:20px;"></div>

    <!-- Quick-Start Checklist -->
    <h2 style="margin-bottom:12px;">Quick-Start Checklist (Priority 1 — Instant Signup)</h2>
    <div id="partner-checklist" class="grid" style="grid-template-columns:repeat(auto-fit, minmax(320px, 1fr));margin-bottom:24px;"></div>

    <!-- Points Redemption Guide -->
    <h2 style="margin-bottom:12px;">Points Redemption Guide</h2>
    <p class="subtitle">Maximize the value of referral points earned from Chase, Amex, and Capital One card referrals.</p>
    <div class="grid grid-3" style="margin-bottom:20px;">
      <!-- Chase UR -->
      <div class="card" style="border-top:3px solid var(--blue);">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
          <div style="font-weight:700;font-size:16px;">Chase Ultimate Rewards</div>
          <span class="badge badge-blue">~$250/referral</span>
        </div>
        <div style="font-size:12px;color:var(--text2);margin-bottom:10px;">20,000 pts per approved referral</div>
        <div style="font-size:13px;line-height:1.8;">
          <div style="border-bottom:1px solid var(--border);padding:4px 0;">
            <span style="color:var(--green);font-weight:600;">Best:</span> Transfer to Hyatt
            <span style="float:right;color:var(--green);font-weight:600;">2+ cpp</span>
          </div>
          <div style="border-bottom:1px solid var(--border);padding:4px 0;">
            Transfer to United/SW/BA
            <span style="float:right;color:var(--blue);">1.5-2 cpp</span>
          </div>
          <div style="border-bottom:1px solid var(--border);padding:4px 0;">
            Pay Yourself Back (Sapphire)
            <span style="float:right;color:var(--text);">1.25-1.5 cpp</span>
          </div>
          <div style="border-bottom:1px solid var(--border);padding:4px 0;">
            Travel Portal
            <span style="float:right;color:var(--text2);">1.25 cpp</span>
          </div>
          <div style="padding:4px 0;">
            <span style="color:var(--red);">Worst:</span> Cash out
            <span style="float:right;color:var(--red);">1 cpp</span>
          </div>
        </div>
        <div style="margin-top:10px;padding:8px;background:var(--surface2);border-radius:6px;font-size:12px;color:var(--text2);">
          10 referrals = 200K UR = ~$3,000 in Hyatt stays
        </div>
      </div>

      <!-- Amex MR -->
      <div class="card" style="border-top:3px solid var(--green);">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
          <div style="font-weight:700;font-size:16px;">Amex Membership Rewards</div>
          <span class="badge badge-green">~$400-450/ref</span>
        </div>
        <div style="font-size:12px;color:var(--text2);margin-bottom:10px;">40,000-45,000 pts per approved referral</div>
        <div style="font-size:13px;line-height:1.8;">
          <div style="border-bottom:1px solid var(--border);padding:4px 0;">
            <span style="color:var(--green);font-weight:600;">Best:</span> Transfer to ANA/Virgin/Aeroplan
            <span style="float:right;color:var(--green);font-weight:600;">2+ cpp</span>
          </div>
          <div style="border-bottom:1px solid var(--border);padding:4px 0;">
            Schwab cashout (w/ Platinum)
            <span style="float:right;color:var(--blue);">1.1 cpp</span>
          </div>
          <div style="border-bottom:1px solid var(--border);padding:4px 0;">
            Transfer to Hilton
            <span style="float:right;color:var(--text);">0.5-1+ cpp</span>
          </div>
          <div style="border-bottom:1px solid var(--border);padding:4px 0;">
            Pay w/ Points (Amazon)
            <span style="float:right;color:var(--yellow);">0.7 cpp</span>
          </div>
          <div style="padding:4px 0;">
            <span style="color:var(--red);">Worst:</span> Statement credit
            <span style="float:right;color:var(--red);">0.6 cpp</span>
          </div>
        </div>
        <div style="margin-top:10px;padding:8px;background:var(--surface2);border-radius:6px;font-size:12px;color:var(--text2);">
          10 referrals = 400K+ MR = ~$5,000+ in premium flights
        </div>
      </div>

      <!-- Capital One -->
      <div class="card" style="border-top:3px solid var(--purple);">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
          <div style="font-weight:700;font-size:16px;">Capital One</div>
          <span class="badge badge-purple">$200 cash/ref</span>
        </div>
        <div style="font-size:12px;color:var(--text2);margin-bottom:10px;">$200 cash bonus per approved referral</div>
        <div style="font-size:13px;line-height:1.8;">
          <div style="border-bottom:1px solid var(--border);padding:4px 0;">
            <span style="color:var(--green);font-weight:600;">Already cash</span> — no optimization needed
          </div>
          <div style="border-bottom:1px solid var(--border);padding:4px 0;">
            Or transfer to Wyndham
            <span style="float:right;color:var(--blue);">1-1.5 cpp</span>
          </div>
          <div style="border-bottom:1px solid var(--border);padding:4px 0;">
            Transfer to Turkish Airlines
            <span style="float:right;color:var(--blue);">1.5+ cpp</span>
          </div>
          <div style="padding:4px 0;">
            Transfer to Air Canada Aeroplan
            <span style="float:right;color:var(--blue);">1.2 cpp</span>
          </div>
        </div>
        <div style="margin-top:10px;padding:8px;background:var(--surface2);border-radius:6px;font-size:12px;color:var(--text2);">
          Simple &amp; instant. $200 per referral, direct deposit.
        </div>
      </div>
    </div>

    <div class="card" style="border-left:3px solid var(--green);margin-bottom:20px;">
      <div style="font-weight:700;margin-bottom:8px;">Key Insight: Referral Points Fund Free Business Travel</div>
      <div style="font-size:13px;color:var(--text2);line-height:1.7;">
        At scale, card referral points fully fund business travel. 10 Chase referrals = 200K UR = ~$3,000 in Hyatt stays or flights.
        10 Amex referrals = 400K+ MR = premium business-class flights worth $5,000+. Capital One pays $200 cash per referral — no points game needed.
        <strong style="color:var(--text);">Focus on Amex for highest per-referral value, Chase for hotel stays, and Capital One for immediate cash.</strong>
      </div>
    </div>

    <!-- Add Partner Form (hidden) -->
    <div id="partner-form" style="display:none;margin-bottom:20px;" class="card">
      <h2 style="margin-bottom:12px;">Add Partner Program</h2>
      <div class="form-row">
        <div class="form-group"><label>Lender</label><input type="text" id="pp-lender" placeholder="e.g., Chase"></div>
        <div class="form-group"><label>Program Name</label><input type="text" id="pp-program" placeholder="e.g., Refer-a-Friend"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>Program Type</label>
          <select id="pp-type">
            <option value="referral">Referral</option><option value="affiliate">Affiliate</option>
            <option value="partner">Partner</option><option value="iso">ISO</option><option value="broker">Broker</option>
          </select>
        </div>
        <div class="form-group"><label>Commission</label><input type="text" id="pp-commission" placeholder="e.g., 15-19% of funded amount"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>Signup URL</label><input type="url" id="pp-signup-url" placeholder="https://..."></div>
        <div class="form-group"><label>Priority</label>
          <select id="pp-priority"><option value="1">1 — High</option><option value="2">2 — Medium</option><option value="3" selected>3 — Low</option></select>
        </div>
      </div>
      <div class="form-group"><label>Notes</label><input type="text" id="pp-notes" placeholder="Optional notes"></div>
      <div style="display:flex;gap:8px;margin-top:8px;">
        <button class="btn btn-green" onclick="submitPartner()">Add Partner</button>
        <button class="btn" style="background:var(--surface2);color:var(--text);" onclick="$('partner-form').style.display='none'">Cancel</button>
      </div>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
const $ = (id) => document.getElementById(id);
const fmt = (n) => n != null ? '$' + Number(n).toLocaleString('en-US', {maximumFractionDigits:0}) : '—';

function showTab(name, ev) {
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  $('tab-' + name).classList.add('active');
  if (ev && ev.target) ev.target.classList.add('active');
  if (name === 'overview') loadOverview();
  if (name === 'strategy') loadStrategy();
  if (name === 'applications') loadApplications();
  if (name === 'inquiries') loadInquiries();
  if (name === 'round') loadRoundPlan();
  if (name === 'products') loadProducts();
  if (name === 'referrals') loadReferrals();
  if (name === 'partners') loadPartners();
}

function toast(msg, type='success') {
  const t = $('toast');
  t.textContent = msg;
  t.className = 'toast ' + type;
  t.style.display = 'block';
  setTimeout(() => t.style.display = 'none', 3000);
}

function statusBadge(status) {
  const map = {approved:'green',denied:'red',pending:'yellow',applied:'blue',planned:'dim',withdrawn:'dim'};
  return `<span class="badge badge-${map[status]||'dim'}">${status}</span>`;
}

function impactColor(impact) {
  return {high:'var(--red)',medium:'var(--yellow)',low:'var(--green)'}[impact] || 'var(--text2)';
}

// ── Overview ──────────────────────────────────────────────────────

async function loadOverview() {
  const [sumRes, profRes] = await Promise.all([
    fetch('/api/summary').then(r=>r.json()),
    fetch('/api/profile').then(r=>r.json()),
  ]);
  const {summary, readiness} = sumRes;

  $('summary-cards').innerHTML = `
    <div class="card">
      <div class="card-title">Total Funding</div>
      <div class="card-value" style="color:var(--green)">${fmt(summary.total_funding_approved)}</div>
      <div class="card-sub">${summary.approved} approved</div>
    </div>
    <div class="card">
      <div class="card-title">Applications</div>
      <div class="card-value">${summary.total_applications}</div>
      <div class="card-sub">${summary.pending} pending</div>
    </div>
    <div class="card">
      <div class="card-title">Approval Rate</div>
      <div class="card-value">${summary.approval_rate.toFixed(0)}%</div>
      <div class="card-sub">${summary.denied} denied</div>
    </div>
    <div class="card">
      <div class="card-title">Credit Score</div>
      <div class="card-value" style="color:var(--blue)">${summary.latest_score || '—'}</div>
      <div class="card-sub">${summary.latest_bureau ? summary.latest_bureau.charAt(0).toUpperCase()+summary.latest_bureau.slice(1) : 'No report'}</div>
    </div>
  `;

  // Readiness
  const score = readiness.score;
  const color = score >= 70 ? 'var(--green)' : score >= 50 ? 'var(--yellow)' : 'var(--red)';
  let factorsHtml = '';
  for (const [k, v] of Object.entries(readiness.factors)) {
    factorsHtml += `<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border);font-size:13px;">
      <span style="color:var(--text2)">${k.replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase())}</span>
      <span>${v}</span>
    </div>`;
  }
  $('readiness-card').innerHTML = `
    <div class="card-title">Readiness Score</div>
    <div style="display:flex;align-items:center;gap:16px;margin:8px 0 16px;">
      <div class="card-value" style="color:${color}">${score}</div>
      <div style="flex:1">
        <div class="progress-bar"><div class="progress-fill" style="width:${score}%;background:${color}"></div></div>
      </div>
      <div style="color:var(--text2)">/100</div>
    </div>
    ${factorsHtml}
  `;

  // Profile
  if (profRes) {
    $('profile-card').innerHTML = `
      <div class="card-title">Credit Profile — ${(profRes.bureau||'').charAt(0).toUpperCase()+(profRes.bureau||'').slice(1)}</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:12px;font-size:14px;">
        <div><span style="color:var(--text2)">Score:</span> <strong>${profRes.score || '—'}</strong></div>
        <div><span style="color:var(--text2)">Utilization:</span> <strong>${profRes.utilization_pct != null ? profRes.utilization_pct.toFixed(1)+'%' : '—'}</strong></div>
        <div><span style="color:var(--text2)">Total Accounts:</span> ${profRes.total_accounts || '—'}</div>
        <div><span style="color:var(--text2)">Open Accounts:</span> ${profRes.open_accounts || '—'}</div>
        <div><span style="color:var(--text2)">Payment History:</span> ${profRes.payment_history_pct != null ? profRes.payment_history_pct.toFixed(1)+'%' : '—'}</div>
        <div><span style="color:var(--text2)">Derogatory Marks:</span> ${profRes.derogatory_marks ?? '—'}</div>
        <div><span style="color:var(--text2)">Avg Age:</span> ${profRes.avg_age_years ? profRes.avg_age_years.toFixed(1)+' yrs' : '—'}</div>
        <div><span style="color:var(--text2)">Oldest:</span> ${profRes.oldest_account_years ? profRes.oldest_account_years.toFixed(1)+' yrs' : '—'}</div>
        <div><span style="color:var(--text2)">Credit Limit:</span> ${fmt(profRes.total_credit_limit)}</div>
        <div><span style="color:var(--text2)">Balance:</span> ${fmt(profRes.total_balance)}</div>
      </div>
    `;
  } else {
    $('profile-card').innerHTML = `
      <div class="card-title">Credit Profile</div>
      <div class="empty-state">No credit report uploaded yet.<br>Go to <strong>Upload Report</strong> tab.</div>
    `;
  }
}

// ── Strategy ──────────────────────────────────────────────────────

async function loadStrategy() {
  const recs = await fetch('/api/strategy').then(r=>r.json());
  if (!recs.length) {
    $('strategy-list').innerHTML = '<div class="empty-state">No recommendations. Upload a credit report first.</div>';
    return;
  }
  $('strategy-list').innerHTML = recs.map(r => `
    <div class="strategy-card ${r.impact||''}">
      <div class="strategy-title">
        <span class="strategy-impact" style="color:${impactColor(r.impact)}">${(r.impact||'info').toUpperCase()}</span>
        ${r.title}
      </div>
      <div class="strategy-detail">${r.detail}</div>
    </div>
  `).join('');
}

// ── Applications ──────────────────────────────────────────────────

async function loadApplications() {
  const apps = await fetch('/api/applications').then(r=>r.json());
  if (!apps.length) {
    $('applications-body').innerHTML = '';
    $('applications-empty').style.display = 'block';
    return;
  }
  $('applications-empty').style.display = 'none';
  $('applications-body').innerHTML = apps.map(a => `<tr>
    <td>${a.id}</td>
    <td><strong>${a.lender}</strong></td>
    <td>${a.product_name || '—'}</td>
    <td>${a.product_type.replace(/_/g,' ')}</td>
    <td>${statusBadge(a.status)}</td>
    <td>${a.amount_approved ? fmt(a.amount_approved) : a.credit_limit ? fmt(a.credit_limit) : a.amount_requested ? fmt(a.amount_requested) : '—'}</td>
    <td>${a.bureau_pulled || '—'}</td>
    <td>${a.applied_date || a.created_at?.slice(0,10) || '—'}</td>
    <td>
      ${a.status !== 'approved' && a.status !== 'denied' ? `
        <button class="btn btn-green" style="padding:4px 10px;font-size:11px;" onclick="updateApp(${a.id},'approved')">Approve</button>
        <button class="btn" style="padding:4px 10px;font-size:11px;background:var(--red);color:white;" onclick="updateApp(${a.id},'denied')">Deny</button>
      ` : ''}
    </td>
  </tr>`).join('');
}

async function updateApp(id, status) {
  let body = {status};
  if (status === 'approved') {
    const amt = prompt('Approved amount ($):');
    if (amt === null) return;  // user cancelled
    if (amt) body.amount_approved = parseFloat(amt.replace(/[,$]/g,''));
  }
  if (status === 'denied') {
    const reason = prompt('Denial reason (optional):');
    if (reason === null) return;  // user cancelled
    if (reason) body.denial_reason = reason;
  }
  await fetch(`/api/applications/${id}`, {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  toast(`Application #${id} ${status}`);
  loadApplications();
  loadOverview();
}

function showAddForm() {
  const form = $('add-form');
  if (form.style.display === 'block') { form.style.display = 'none'; return; }
  form.style.display = 'block';
  form.innerHTML = `
    <h2 style="margin-bottom:16px">New Application</h2>
    <div class="form-row">
      <div class="form-group"><label>Lender</label><input id="f-lender" placeholder="e.g., Chase"></div>
      <div class="form-group"><label>Product Name</label><input id="f-product" placeholder="e.g., Ink Business Preferred"></div>
    </div>
    <div class="form-row">
      <div class="form-group"><label>Type</label>
        <select id="f-type"><option value="credit_card">Credit Card</option><option value="loc">Line of Credit</option><option value="term_loan">Term Loan</option><option value="sba">SBA Loan</option><option value="balance_transfer">Balance Transfer</option></select>
      </div>
      <div class="form-group"><label>Status</label>
        <select id="f-status"><option value="planned">Planned</option><option value="applied">Applied</option><option value="pending">Pending</option><option value="approved">Approved</option><option value="denied">Denied</option></select>
      </div>
    </div>
    <div class="form-row">
      <div class="form-group"><label>Amount ($)</label><input id="f-amount" type="number" placeholder="0"></div>
      <div class="form-group"><label>Bureau Pulled</label>
        <select id="f-bureau"><option value="">—</option><option value="experian">Experian</option><option value="transunion">TransUnion</option><option value="equifax">Equifax</option><option value="multiple">Multiple</option></select>
      </div>
    </div>
    <div class="form-group"><label>Notes</label><input id="f-notes" placeholder="Optional notes"></div>
    <button class="btn btn-primary" onclick="submitApp()">Save Application</button>
    <button class="btn" style="margin-left:8px;background:var(--surface2);color:var(--text);" onclick="$('add-form').style.display='none'">Cancel</button>
  `;
}

async function submitApp() {
  const status = $('f-status').value;
  const amount = parseFloat($('f-amount').value) || null;
  const body = {
    lender: $('f-lender').value,
    product_name: $('f-product').value,
    product_type: $('f-type').value,
    status: status,
    amount_requested: status !== 'approved' ? amount : null,
    amount_approved: status === 'approved' ? amount : null,
    bureau_pulled: $('f-bureau').value || null,
    applied_date: status !== 'planned' ? new Date().toISOString().slice(0,10) : null,
    notes: $('f-notes').value || null,
  };
  await fetch('/api/applications', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  $('add-form').style.display = 'none';
  toast('Application saved');
  loadApplications();
  loadOverview();
}

// ── Inquiries ─────────────────────────────────────────────────────

async function loadInquiries() {
  const data = await fetch('/api/inquiries').then(r=>r.json());
  const bureaus = ['experian','transunion','equifax'];
  const max12 = Math.max(1, ...bureaus.map(b => data.counts_12mo[b]||0));
  const colors = {experian:'var(--blue)',transunion:'var(--green)',equifax:'var(--purple)'};

  $('bureau-bars').innerHTML = bureaus.map(b => {
    const c12 = data.counts_12mo[b]||0;
    const c24 = data.counts_24mo[b]||0;
    const pct = (c12/max12*100).toFixed(0);
    return `<div class="bureau-bar-container">
      <div class="bureau-label"><span>${b.charAt(0).toUpperCase()+b.slice(1)}</span><span>${c12} (12mo) / ${c24} (24mo)</span></div>
      <div class="bureau-bar"><div class="bureau-fill" style="width:${pct}%;background:${colors[b]}"></div></div>
    </div>`;
  }).join('') + `<div style="margin-top:12px;font-size:14px;color:var(--text2)">Total: <strong style="color:var(--text)">${Object.values(data.counts_12mo).reduce((a,b)=>a+b,0)}</strong> (12 mo)</div>`;

  $('inquiries-body').innerHTML = data.inquiries.slice(0,15).map(i => `<tr>
    <td>${i.date}</td>
    <td><span class="badge badge-${i.bureau==='experian'?'blue':i.bureau==='transunion'?'green':'purple'}">${i.bureau}</span></td>
    <td>${i.lender}</td>
    <td style="color:var(--text2)">${i.falls_off_date||'—'}</td>
  </tr>`).join('');
}

// ── Round Plan ────────────────────────────────────────────────────

async function loadRoundPlan() {
  const products = await fetch('/api/round-plan').then(r=>r.json());
  if (!products.length) {
    $('round-plan').innerHTML = '<div class="empty-state">No eligible products for a round. Upload a credit report and check strategy recommendations.</div>';
    return;
  }
  let totalLow = 0, totalHigh = 0;
  $('round-plan').innerHTML = products.map((p, i) => {
    const low = p.typical_limit_low||0;
    const high = p.typical_limit_high||0;
    totalLow += low;
    totalHigh += high;
    return `<div class="plan-item">
      <div class="plan-number">${i+1}</div>
      <div class="plan-detail">
        <div class="plan-lender">${p.lender} — ${p.reference_url ? `<a href="${p.reference_url}" target="_blank" rel="noopener" style="color:var(--blue);text-decoration:none;border-bottom:1px dotted var(--blue);">${p.product_name}</a>` : p.product_name}</div>
        <div class="plan-meta">
          ${p.product_type.replace(/_/g,' ')} &bull; ${p.bureau_pulled||'N/A'}
          ${p.inquiry_sensitive ? ' &bull; <span style="color:var(--red);font-weight:600">INQUIRY SENSITIVE</span>' : ''}
        </div>
        ${p.notes ? `<div class="plan-meta" style="margin-top:4px">${p.notes.slice(0,100)}</div>` : ''}
      </div>
      <div class="plan-limit">${low&&high ? fmt(low)+' – '+fmt(high) : '—'}</div>
    </div>`;
  }).join('') + `<div class="card" style="margin-top:16px;text-align:center;">
    <div class="card-title">Estimated Round Total</div>
    <div class="card-value" style="color:var(--green)">${fmt(totalLow)} – ${fmt(totalHigh)}</div>
  </div>`;
}

// ── Products (AG Grid) ────────────────────────────────────────────

let productGrid = null;
let allProductData = [];
let activeFilters = {};
let currentView = 'all';

// Custom cell renderers
function productNameRenderer(params) {
  const p = params.data;
  if (p.reference_url) {
    return `<a href="${p.reference_url}" target="_blank" rel="noopener" style="color:var(--blue);text-decoration:none;border-bottom:1px dotted var(--blue);">${p.product_name}</a>`;
  }
  return p.product_name;
}

function categoryRenderer(params) {
  const map = {starter:['starter','dim'], mid_tier:['mid tier','blue'], premium:['premium','yellow'], ultra_premium:['ultra','purple']};
  const [label, cls] = map[params.value] || [params.value||'—','dim'];
  return `<span class="badge badge-${cls}">${label}</span>`;
}

function typeRenderer(params) {
  return (params.value||'').replace(/_/g, ' ');
}

function limitRenderer(params) {
  const p = params.data;
  if (!p.typical_limit_low || !p.typical_limit_high) return '<span style="color:var(--text2)">—</span>';
  const text = fmt(p.typical_limit_low) + ' – ' + fmt(p.typical_limit_high);
  if (p.limit_source_url) {
    return `<a href="${p.limit_source_url}" target="_blank" rel="noopener" style="color:var(--green);text-decoration:none;border-bottom:1px dotted var(--green);" title="View source">${text}</a>`;
  }
  return `<span style="color:var(--green)">${text}</span>`;
}

function bureauRenderer(params) {
  const bureau = params.value;
  if (!bureau || bureau === 'none') return '<span style="color:var(--green);font-size:12px;font-weight:600">No Pull</span>';
  if (bureau === 'soft_pull') return '<span style="color:var(--green);font-size:12px;font-weight:600">Soft Pull</span>';
  const colors = {experian:'blue',transunion:'green',equifax:'purple'};
  return bureau.split(',').map(b => {
    const bt = b.trim().toLowerCase();
    const label = bt.charAt(0).toUpperCase()+bt.slice(1);
    return `<span class="badge badge-${colors[bt]||'dim'}" style="font-size:10px;margin:1px 2px;">${label}</span>`;
  }).join('');
}

function inquirySensitiveRenderer(params) {
  return params.value
    ? '<span style="color:var(--red);font-weight:600">Yes</span>'
    : '<span style="color:var(--text2)">No</span>';
}

function pgRenderer(params) {
  return params.value
    ? '<span style="color:var(--text2)">Yes</span>'
    : '<span style="color:var(--green);font-weight:600">No PG</span>';
}

function introAprRenderer(params) {
  const p = params.data;
  if (p.intro_apr === 0 && p.intro_period_months) {
    return `<span style="color:var(--green);font-weight:600">${p.intro_period_months}mo</span>`;
  }
  return '<span style="color:var(--text2)">—</span>';
}

function annualFeeRenderer(params) {
  return params.value ? fmt(params.value) : '<span style="color:var(--green)">$0</span>';
}

function scoreRenderer(params) {
  if (!params.value) return '<span style="color:var(--text2)">—</span>';
  const v = params.value;
  const color = v >= 700 ? 'var(--yellow)' : v >= 640 ? 'var(--text)' : 'var(--green)';
  return `<span style="color:${color};font-weight:500">${v}</span>`;
}

function notesRenderer(params) {
  if (!params.value) return '';
  return `<span title="${params.value.replace(/"/g,'&quot;')}" style="cursor:help;color:var(--text2);font-size:16px">&#9432;</span>`;
}

function docsLevelRenderer(params) {
  const map = {
    very_low: ['Very Low', 'green'],
    low: ['Low', 'blue'],
    moderate: ['Moderate', 'yellow'],
    high: ['High', 'red'],
  };
  const [label, cls] = map[params.value] || [params.value||'—','dim'];
  return `<span class="badge badge-${cls}">${label}</span>`;
}

function startupGradeRenderer(params) {
  if (!params.value) return '<span style="color:var(--text2)">—</span>';
  const g = params.value;
  const colorMap = {'A+':'var(--green)','A':'var(--green)','B+':'#7dd87d','B':'var(--blue)','B-':'var(--blue)','C+':'var(--yellow)','C':'var(--yellow)','D':'var(--red)','F':'var(--red)'};
  const color = colorMap[g] || 'var(--text2)';
  return `<span style="color:${color};font-weight:700;font-size:14px">${g}</span>`;
}

function minTimeRenderer(params) {
  const v = params.value;
  if (v == null) return '<span style="color:var(--text2)">—</span>';
  if (v === 0) return '<span style="color:var(--green);font-weight:600">Day 1</span>';
  if (v <= 3) return `<span style="color:var(--green);font-weight:500">${v}mo</span>`;
  if (v <= 6) return `<span style="color:var(--blue)">${v}mo</span>`;
  if (v <= 12) return `<span style="color:var(--yellow)">${v}mo</span>`;
  return `<span style="color:var(--red)">${v}mo</span>`;
}

function maxLineRenderer(params) {
  if (!params.value) return '<span style="color:var(--text2)">—</span>';
  return `<span style="color:var(--green)">${fmt(params.value)}</span>`;
}

function lenderTypeRenderer(params) {
  const map = {
    bank: ['Bank', 'blue'],
    credit_union: ['Credit Union', 'green'],
    fintech: ['Fintech', 'purple'],
    marketplace: ['Marketplace', 'yellow'],
    vendor: ['Vendor', 'dim'],
    government: ['Gov', 'blue'],
  };
  const [label, cls] = map[params.value] || [params.value||'—','dim'];
  return `<span class="badge badge-${cls}">${label}</span>`;
}

function commissionRenderer(params) {
  if (!params.value) return '<span style="color:var(--text2)">—</span>';
  const type = params.data.referral_commission_type;
  const colorMap = {percentage:'green', flat_fee:'blue', points:'purple', recurring:'yellow'};
  const cls = colorMap[type] || 'dim';
  return `<span class="badge badge-${cls}" style="font-size:10px;">${params.value}</span>`;
}

// Limit range sort comparator (sort by low end)
function limitComparator(a, b, nodeA, nodeB) {
  const aVal = nodeA.data.typical_limit_low || 0;
  const bVal = nodeB.data.typical_limit_low || 0;
  return aVal - bVal;
}

const productColumnDefs = [
  { field: 'lender', headerName: 'Lender', flex: 1.2, filter: true, sortable: true,
    cellStyle: {'font-weight': '600'} },
  { field: 'lender_type', headerName: 'Type', width: 110, filter: true, sortable: true,
    cellRenderer: lenderTypeRenderer },
  { field: 'referral_commission_display', headerName: 'Commission', width: 180, filter: true, sortable: true,
    cellRenderer: commissionRenderer },
  { field: 'product_name', headerName: 'Product', flex: 1.5, filter: true, sortable: true,
    cellRenderer: productNameRenderer },
  { field: 'category', headerName: 'Tier', width: 105, filter: true, sortable: true,
    cellRenderer: categoryRenderer },
  { field: 'product_type', headerName: 'Type', width: 115, filter: true, sortable: true,
    cellRenderer: typeRenderer },
  { field: 'startup_grade', headerName: 'Startup', width: 85, filter: true, sortable: true,
    cellRenderer: startupGradeRenderer },
  { field: 'min_time_months', headerName: 'Min Time', width: 90, filter: 'agNumberColumnFilter', sortable: true,
    cellRenderer: minTimeRenderer },
  { field: 'docs_level', headerName: 'Docs', width: 95, filter: true, sortable: true,
    cellRenderer: docsLevelRenderer },
  { field: 'min_score', headerName: 'Min Score', width: 100, filter: 'agNumberColumnFilter', sortable: true,
    cellRenderer: scoreRenderer },
  { headerName: 'Limit Range', width: 165, sortable: true,
    cellRenderer: limitRenderer, comparator: limitComparator,
    valueGetter: p => p.data.typical_limit_low || 0 },
  { field: 'max_line', headerName: 'Max Line', width: 100, filter: 'agNumberColumnFilter', sortable: true,
    cellRenderer: maxLineRenderer },
  { field: 'bureau_pulled', headerName: 'Bureau', width: 130, filter: true, sortable: true,
    cellRenderer: bureauRenderer },
  { field: 'inquiry_sensitive', headerName: 'Inq Sens', width: 90, filter: true, sortable: true,
    cellRenderer: inquirySensitiveRenderer },
  { field: 'personal_guarantee', headerName: 'PG', width: 70, filter: true, sortable: true,
    cellRenderer: pgRenderer },
  { headerName: '0% APR', width: 85, sortable: true,
    cellRenderer: introAprRenderer,
    valueGetter: p => p.data.intro_apr === 0 ? p.data.intro_period_months || 0 : -1 },
  { field: 'annual_fee', headerName: 'Fee', width: 80, filter: 'agNumberColumnFilter', sortable: true,
    cellRenderer: annualFeeRenderer },
  { field: 'notes', headerName: '', width: 40, sortable: false,
    cellRenderer: notesRenderer },
];

const productGridOptions = {
  columnDefs: productColumnDefs,
  rowData: [],
  defaultColDef: {
    resizable: true,
    suppressMovable: false,
  },
  animateRows: true,
  rowSelection: 'single',
  suppressCellFocus: true,
  overlayNoRowsTemplate: '<div class="empty-state">No products match current filters</div>',
  getRowStyle: params => {
    if (params.data.intro_apr === 0) return { borderLeft: '3px solid var(--green)' };
    if (params.data.inquiry_sensitive) return { borderLeft: '3px solid var(--red)' };
    if (!params.data.personal_guarantee) return { borderLeft: '3px solid var(--purple)' };
    return null;
  },
  onGridReady: () => updateStatsRow(),
  onFilterChanged: () => updateStatsRow(),
  onSortChanged: () => updateStatsRow(),
};

async function loadProducts() {
  const products = await fetch('/api/products').then(r => r.json());
  allProductData = products;

  if (!productGrid) {
    const gridDiv = document.querySelector('#product-grid');
    productGrid = agGrid.createGrid(gridDiv, productGridOptions);
  }
  productGrid.setGridOption('rowData', products);
  applyCurrentView();
  buildFilterChips(products);
  updateStatsRow();
}

// ── View tabs (Airtable-style) ─────────────────────────────────

function setView(view, ev) {
  currentView = view;
  document.querySelectorAll('.view-tab').forEach(t => t.classList.remove('active'));
  if (ev && ev.target) ev.target.classList.add('active');
  applyCurrentView();
  updateStatsRow();
}

function applyCurrentView() {
  if (!productGrid) return;
  let filtered = allProductData;
  if (currentView === 'no_pg') {
    filtered = allProductData.filter(p => !p.personal_guarantee);
  } else if (currentView === 'no_pull') {
    filtered = allProductData.filter(p => !p.bureau_pulled || p.bureau_pulled === 'none' || p.bureau_pulled === 'soft_pull');
  } else if (currentView === 'startup') {
    filtered = allProductData.filter(p => p.startup_grade && ['A+','A','B+','B'].includes(p.startup_grade));
  } else if (currentView === 'credit_union') {
    filtered = allProductData.filter(p => p.lender_type === 'credit_union');
  } else if (currentView === 'fintech') {
    filtered = allProductData.filter(p => p.lender_type === 'fintech');
  } else if (currentView === 'referral') {
    filtered = allProductData.filter(p => p.has_referral);
  } else if (currentView !== 'all') {
    filtered = allProductData.filter(p => p.product_type === currentView);
  }
  // Apply active chip filters on top of view
  filtered = applyChipFilters(filtered);
  productGrid.setGridOption('rowData', filtered);
}

// ── Filter chips (Amazon-style faceted) ────────────────────────

function buildFilterChips(products) {
  const chips = $('filter-chips');
  // Count by category
  const cats = {};
  const bureaus = {};
  const scores = { '700+': 0, '660-699': 0, '640-659': 0, '<640': 0, 'No Min': 0 };

  products.forEach(p => {
    cats[p.category || 'other'] = (cats[p.category || 'other'] || 0) + 1;
    if (p.bureau_pulled) {
      p.bureau_pulled.split(',').forEach(b => {
        const bt = b.trim().toLowerCase();
        if (bt && bt !== 'none' && bt !== 'soft_pull') bureaus[bt] = (bureaus[bt] || 0) + 1;
      });
    }
    if (!p.min_score) scores['No Min']++;
    else if (p.min_score >= 700) scores['700+']++;
    else if (p.min_score >= 660) scores['660-699']++;
    else if (p.min_score >= 640) scores['640-659']++;
    else scores['<640']++;
  });

  let html = '<span style="color:var(--text2);font-size:12px;font-weight:600;margin-right:4px;">FILTER:</span>';

  // Category chips
  const catLabels = {starter:'Starter', mid_tier:'Mid Tier', premium:'Premium', ultra_premium:'Ultra Premium'};
  for (const [cat, count] of Object.entries(cats).sort((a,b) => b[1]-a[1])) {
    const label = catLabels[cat] || cat;
    const isActive = activeFilters.category === cat;
    html += `<button class="filter-chip${isActive?' active':''}" onclick="toggleFilter('category','${cat}')">
      ${label} <span class="filter-chip-count">${count}</span>
      ${isActive ? '<span class="chip-x">&times;</span>' : ''}
    </button>`;
  }

  html += '<span style="width:1px;height:20px;background:var(--border);margin:0 4px;"></span>';

  // Bureau chips
  const bureauLabels = {experian:'Experian', transunion:'TransUnion', equifax:'Equifax'};
  for (const [b, count] of Object.entries(bureaus).sort((a,b) => b[1]-a[1])) {
    const label = bureauLabels[b] || b;
    const isActive = activeFilters.bureau === b;
    html += `<button class="filter-chip${isActive?' active':''}" onclick="toggleFilter('bureau','${b}')">
      ${label} <span class="filter-chip-count">${count}</span>
      ${isActive ? '<span class="chip-x">&times;</span>' : ''}
    </button>`;
  }

  html += '<span style="width:1px;height:20px;background:var(--border);margin:0 4px;"></span>';

  // Docs level chips
  const docsLabels = {very_low:'Very Low Docs', low:'Low Docs', moderate:'Moderate Docs', high:'Heavy Docs'};
  const docsCounts = {};
  products.forEach(p => { if (p.docs_level) docsCounts[p.docs_level] = (docsCounts[p.docs_level]||0)+1; });
  for (const [dl, count] of Object.entries(docsCounts).sort((a,b) => b[1]-a[1])) {
    const isActive = activeFilters.docs === dl;
    html += `<button class="filter-chip${isActive?' active':''}" onclick="toggleFilter('docs','${dl}')">
      ${docsLabels[dl]||dl} <span class="filter-chip-count">${count}</span>
      ${isActive ? '<span class="chip-x">&times;</span>' : ''}
    </button>`;
  }

  // Lender type chips
  html += '<span style="width:1px;height:20px;background:var(--border);margin:0 4px;"></span>';
  const lenderTypeCounts = {};
  products.forEach(p => { if (p.lender_type) lenderTypeCounts[p.lender_type] = (lenderTypeCounts[p.lender_type]||0)+1; });
  const ltLabels = {bank:'Banks',credit_union:'Credit Unions',fintech:'Fintech',marketplace:'Marketplace',vendor:'Vendor',government:'Government'};
  const ltColors = {credit_union:'border-color:rgba(63,185,80,0.4);color:var(--green);',fintech:'border-color:rgba(188,140,255,0.4);color:var(--purple);'};
  for (const [lt, count] of Object.entries(lenderTypeCounts).sort((a,b) => b[1]-a[1])) {
    const isActive = activeFilters.lender_type === lt;
    const style = isActive ? '' : (ltColors[lt]||'');
    html += `<button class="filter-chip${isActive?' active':''}" onclick="toggleFilter('lender_type','${lt}')" style="${style}">
      ${ltLabels[lt]||lt} <span class="filter-chip-count">${count}</span>
      ${isActive ? '<span class="chip-x">&times;</span>' : ''}
    </button>`;
  }

  // Special chips
  html += '<span style="width:1px;height:20px;background:var(--border);margin:0 4px;"></span>';
  const startupFriendly = products.filter(p => p.startup_grade && ['A+','A','B+','B'].includes(p.startup_grade)).length;
  const zeroApr = products.filter(p => p.intro_apr === 0).length;
  const noPg = products.filter(p => !p.personal_guarantee).length;
  if (startupFriendly) {
    const isActive = activeFilters.special === 'startup';
    html += `<button class="filter-chip${isActive?' active':''}" onclick="toggleFilter('special','startup')" style="${isActive?'':'border-color:rgba(63,185,80,0.4);color:var(--green);'}">
      Startup OK <span class="filter-chip-count">${startupFriendly}</span>
      ${isActive ? '<span class="chip-x">&times;</span>' : ''}
    </button>`;
  }
  if (zeroApr) {
    const isActive = activeFilters.special === 'zero_apr';
    html += `<button class="filter-chip${isActive?' active':''}" onclick="toggleFilter('special','zero_apr')" style="${isActive?'':'border-color:rgba(63,185,80,0.4);color:var(--green);'}">
      0% APR <span class="filter-chip-count">${zeroApr}</span>
      ${isActive ? '<span class="chip-x">&times;</span>' : ''}
    </button>`;
  }
  if (noPg) {
    const isActive = activeFilters.special === 'no_pg';
    html += `<button class="filter-chip${isActive?' active':''}" onclick="toggleFilter('special','no_pg')" style="${isActive?'':'border-color:rgba(188,140,255,0.4);color:var(--purple);'}">
      No PG <span class="filter-chip-count">${noPg}</span>
      ${isActive ? '<span class="chip-x">&times;</span>' : ''}
    </button>`;
  }
  const hasRef = products.filter(p => p.has_referral).length;
  if (hasRef) {
    const isActive = activeFilters.special === 'has_referral';
    html += `<button class="filter-chip${isActive?' active':''}" onclick="toggleFilter('special','has_referral')" style="${isActive?'':'border-color:rgba(63,185,80,0.4);color:var(--green);'}">
      Has Referral <span class="filter-chip-count">${hasRef}</span>
      ${isActive ? '<span class="chip-x">&times;</span>' : ''}
    </button>`;
  }

  chips.innerHTML = html;
}

function toggleFilter(type, value) {
  if (activeFilters[type] === value) {
    delete activeFilters[type];
  } else {
    activeFilters[type] = value;
  }
  applyCurrentView();
  buildFilterChips(allProductData);
  updateStatsRow();
}

function applyChipFilters(data) {
  let filtered = data;
  if (activeFilters.category) {
    filtered = filtered.filter(p => (p.category || 'other') === activeFilters.category);
  }
  if (activeFilters.bureau) {
    filtered = filtered.filter(p => p.bureau_pulled && p.bureau_pulled.toLowerCase().includes(activeFilters.bureau));
  }
  if (activeFilters.docs) {
    filtered = filtered.filter(p => p.docs_level === activeFilters.docs);
  }
  if (activeFilters.lender_type) {
    filtered = filtered.filter(p => p.lender_type === activeFilters.lender_type);
  }
  if (activeFilters.special === 'startup') {
    filtered = filtered.filter(p => p.startup_grade && ['A+','A','B+','B'].includes(p.startup_grade));
  }
  if (activeFilters.special === 'zero_apr') {
    filtered = filtered.filter(p => p.intro_apr === 0);
  }
  if (activeFilters.special === 'no_pg') {
    filtered = filtered.filter(p => !p.personal_guarantee);
  }
  if (activeFilters.special === 'has_referral') {
    filtered = filtered.filter(p => p.has_referral);
  }
  return filtered;
}

// ── Global search ──────────────────────────────────────────────

function onGridSearch(value) {
  if (!productGrid) return;
  const term = value.toLowerCase().trim();
  if (!term) {
    applyCurrentView();
  } else {
    let filtered = allProductData.filter(p =>
      (p.lender||'').toLowerCase().includes(term) ||
      (p.product_name||'').toLowerCase().includes(term) ||
      (p.category||'').toLowerCase().includes(term) ||
      (p.product_type||'').toLowerCase().includes(term) ||
      (p.bureau_pulled||'').toLowerCase().includes(term) ||
      (p.lender_type||'').toLowerCase().includes(term) ||
      (p.notes||'').toLowerCase().includes(term) ||
      (p.referral_commission_display||'').toLowerCase().includes(term)
    );
    filtered = applyChipFilters(filtered);
    productGrid.setGridOption('rowData', filtered);
  }
  updateStatsRow();
}

// ── Stats row ──────────────────────────────────────────────────

function updateStatsRow() {
  if (!productGrid) return;
  let count = 0;
  productGrid.forEachNodeAfterFilter(n => count++);
  const total = allProductData.length;
  const showing = count === total ? `<strong>${total}</strong> products` : `<strong>${count}</strong> of ${total} products`;
  const hasFilters = Object.keys(activeFilters).length > 0 || currentView !== 'all' || $('grid-search').value.trim();
  $('stats-row').innerHTML = `
    <span class="stat-pill">${showing}</span>
    ${hasFilters ? '<button class="filter-chip" onclick="clearAllFilters()" style="border-color:var(--red);color:var(--red);font-size:11px;padding:3px 10px;">Clear All Filters</button>' : ''}
  `;
}

function clearAllFilters() {
  activeFilters = {};
  currentView = 'all';
  $('grid-search').value = '';
  document.querySelectorAll('.view-tab').forEach(t => t.classList.remove('active'));
  document.querySelector('.view-tab').classList.add('active');
  productGrid.setGridOption('rowData', allProductData);
  buildFilterChips(allProductData);
  updateStatsRow();
}

// ── Upload + Full Analysis ────────────────────────────────────────

const zone = $('upload-zone');
zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
zone.addEventListener('drop', e => {
  e.preventDefault(); zone.classList.remove('dragover');
  if (e.dataTransfer.files.length) uploadFile(e.dataTransfer.files[0]);
});

async function uploadFile(file) {
  if (!file || !file.name.toLowerCase().endsWith('.pdf')) {
    toast('Please upload a PDF file', 'error');
    return;
  }
  const formData = new FormData();
  formData.append('file', file);
  $('upload-zone').innerHTML = '<div class="upload-icon">&#9203;</div><div class="upload-text">Parsing & analyzing...</div>';

  try {
    const res = await fetch('/api/parse', {method:'POST', body: formData});
    const data = await res.json();
    if (data.error) {
      toast(data.error, 'error');
      resetUploadZone();
      return;
    }
    toast('Credit report parsed successfully');
    resetUploadZone();
    renderFullAnalysis(data);
  } catch(e) {
    toast('Upload failed: ' + e.message, 'error');
    resetUploadZone();
  }
}

function resetUploadZone() {
  $('upload-zone').innerHTML = '<div class="upload-icon">&#128196;</div><div class="upload-text">Click or drag & drop a credit report PDF</div><input type="file" id="file-input" accept=".pdf" style="display:none" onchange="uploadFile(this.files[0])">';
}

function renderFullAnalysis(data) {
  const el = $('upload-analysis');
  el.style.display = 'block';
  const p = data.profile;
  const ext = data.extraction;
  const health = data.analysis;
  const elig = data.eligibility;
  const prev = data.previous;
  const readiness = data.readiness;
  const bureau = (data.bureau||'unknown').charAt(0).toUpperCase() + (data.bureau||'').slice(1);

  let html = '';

  // ── Header: Bureau + Confidence Bar ──────────────────────────
  const confColor = ext.pct >= 70 ? 'var(--green)' : ext.pct >= 40 ? 'var(--yellow)' : 'var(--red)';
  html += `
  <div class="card" style="margin-bottom:16px;border-left:4px solid var(--green);">
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <div>
        <h2 style="margin:0;color:var(--green)">Report Parsed — ${bureau}</h2>
        <div style="color:var(--text2);font-size:13px;margin-top:4px;">Profile #${data.profile_id} &bull; ${p.parsed_at?.slice(0,10) || 'Today'}</div>
      </div>
      <div style="text-align:right;">
        <div style="font-size:12px;color:var(--text2);">Extraction Confidence</div>
        <div style="font-size:24px;font-weight:700;color:${confColor}">${ext.pct}%</div>
        <div style="font-size:11px;color:var(--text2);">${ext.fields_found} of ${ext.fields_total} fields</div>
      </div>
    </div>
    <div class="progress-bar" style="margin-top:12px;">
      <div class="progress-fill" style="width:${ext.pct}%;background:${confColor}"></div>
    </div>
  </div>`;

  // ── Comparison to Previous (if exists) ───────────────────────
  if (prev && prev.score_change !== null) {
    const scoreDir = prev.score_change > 0 ? '+' : '';
    const scoreColor = prev.score_change > 0 ? 'var(--green)' : prev.score_change < 0 ? 'var(--red)' : 'var(--text2)';
    const scoreArrow = prev.score_change > 0 ? '&#9650;' : prev.score_change < 0 ? '&#9660;' : '&#8212;';
    let compHtml = `
    <div class="card" style="margin-bottom:16px;border-left:4px solid var(--blue);">
      <div class="card-title">Compared to Previous Report</div>
      <div style="display:flex;gap:32px;margin-top:8px;align-items:center;">
        <div style="text-align:center;">
          <div style="font-size:11px;color:var(--text2)">Score</div>
          <div style="font-size:28px;font-weight:700;color:${scoreColor}">${scoreArrow} ${scoreDir}${prev.score_change}</div>
          <div style="font-size:11px;color:var(--text2)">${prev.prev_score || '?'} &rarr; ${p.score || '?'}</div>
        </div>`;
    if (prev.utilization_change !== null) {
      const uDir = prev.utilization_change > 0 ? '+' : '';
      const uColor = prev.utilization_change < 0 ? 'var(--green)' : prev.utilization_change > 0 ? 'var(--red)' : 'var(--text2)';
      compHtml += `
        <div style="text-align:center;">
          <div style="font-size:11px;color:var(--text2)">Utilization</div>
          <div style="font-size:28px;font-weight:700;color:${uColor}">${uDir}${prev.utilization_change}%</div>
          <div style="font-size:11px;color:var(--text2)">${prev.prev_utilization?.toFixed(0) || '?'}% &rarr; ${p.utilization_pct?.toFixed(0) || '?'}%</div>
        </div>`;
    }
    compHtml += `
        <div style="flex:1;text-align:right;color:var(--text2);font-size:12px;">
          Previous: ${prev.prev_bureau?.charAt(0).toUpperCase()+prev.prev_bureau?.slice(1) || ''} &bull; ${prev.prev_date || ''}
          ${prev.days_since ? ` &bull; ${prev.days_since} days ago` : ''}
        </div>
      </div>
    </div>`;
    html += compHtml;
  }

  // ── Credit Health Scorecard (6 factor cards) ─────────────────
  html += `<h2 style="margin-bottom:12px;">Credit Health Scorecard</h2>
  <div class="grid" style="grid-template-columns:repeat(auto-fit, minmax(180px, 1fr));margin-bottom:20px;">`;

  for (const factor of health.factors) {
    html += `
    <div class="card" style="border-top:3px solid ${factor.color};">
      <div class="card-title">${factor.name}</div>
      <div style="font-size:24px;font-weight:700;color:${factor.color};margin:4px 0;">${factor.value}</div>
      <span class="badge" style="background:${factor.color}20;color:${factor.color};">${factor.rating}</span>
      ${factor.target ? `<div style="font-size:11px;color:var(--text2);margin-top:4px;">Target: ${factor.target}</div>` : ''}
      ${factor.oldest ? `<div style="font-size:11px;color:var(--text2);margin-top:4px;">Oldest: ${factor.oldest}</div>` : ''}
      ${factor.pct !== undefined ? `<div class="progress-bar" style="margin-top:6px;"><div class="progress-fill" style="width:${Math.min(factor.pct, 100)}%;background:${factor.color}"></div></div>` : ''}
    </div>`;
  }
  html += `</div>`;

  // ── Strengths & Warnings ─────────────────────────────────────
  if (health.strengths.length || health.warnings.length) {
    html += `<div class="grid grid-2" style="margin-bottom:20px;">`;
    if (health.strengths.length) {
      html += `<div class="card" style="border-left:3px solid var(--green);">
        <div class="card-title" style="color:var(--green)">Strengths</div>
        ${health.strengths.map(s => `<div style="font-size:13px;padding:4px 0;color:var(--text);">&#10003; ${s}</div>`).join('')}
      </div>`;
    }
    if (health.warnings.length) {
      html += `<div class="card" style="border-left:3px solid var(--yellow);">
        <div class="card-title" style="color:var(--yellow)">Action Items</div>
        ${health.warnings.map(w => `<div style="font-size:13px;padding:4px 0;color:var(--text);">&#9888; ${w}</div>`).join('')}
      </div>`;
    }
    html += `</div>`;
  }

  // ── Product Eligibility Snapshot ─────────────────────────────
  html += `
  <div class="card" style="margin-bottom:20px;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
      <div>
        <div class="card-title">Product Eligibility</div>
        <div style="font-size:20px;font-weight:700;color:var(--green);">${elig.total_eligible} <span style="font-size:14px;color:var(--text2);font-weight:400;">of ${elig.total_products} products</span></div>
      </div>
      <div style="font-size:40px;font-weight:700;color:var(--green);">${Math.round(elig.total_eligible / (elig.total_products || 1) * 100)}%</div>
    </div>
    <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px;">`;
  const typeLabels = {credit_card:'Credit Cards',loc:'Lines of Credit',term_loan:'Term Loans',sba:'SBA Loans',balance_transfer:'0% APR'};
  for (const [t, count] of Object.entries(elig.by_type || {})) {
    html += `<span class="badge badge-blue">${typeLabels[t]||t}: ${count}</span>`;
  }
  html += `</div>`;
  if (elig.top_products?.length) {
    html += `<div style="font-size:12px;color:var(--text2);margin-bottom:6px;">TOP RECOMMENDATIONS</div>`;
    for (const tp of elig.top_products) {
      html += `<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid var(--border);font-size:13px;">
        <span><strong>${tp.lender}</strong> — ${tp.name}</span>
        <span style="color:var(--green);font-weight:500;">${tp.limit_high ? fmt(tp.limit_high) : '—'}</span>
      </div>`;
    }
  }
  html += `</div>`;

  // ── Readiness Score ──────────────────────────────────────────
  const rScore = readiness.score;
  const rColor = rScore >= 70 ? 'var(--green)' : rScore >= 50 ? 'var(--yellow)' : 'var(--red)';
  html += `
  <div class="card" style="margin-bottom:20px;">
    <div class="card-title">Funding Readiness Score</div>
    <div style="display:flex;align-items:center;gap:16px;margin:8px 0;">
      <div style="font-size:36px;font-weight:700;color:${rColor};">${rScore}</div>
      <div style="flex:1;"><div class="progress-bar"><div class="progress-fill" style="width:${rScore}%;background:${rColor}"></div></div></div>
      <div style="color:var(--text2);">/100</div>
    </div>
  </div>`;

  // ── Extraction Report Card ───────────────────────────────────
  html += `
  <h2 style="margin-bottom:12px;">Extraction Report Card</h2>
  <div class="card" style="margin-bottom:20px;">
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:2px;">`;
  for (const fd of data.field_details) {
    const icon = fd.found
      ? '<span style="color:var(--green);font-weight:700;">&#10003;</span>'
      : '<span style="color:var(--red);opacity:0.6;">&#10007;</span>';
    const val = fd.found
      ? `<span style="font-weight:500;">${fd.value}</span>`
      : '<span style="color:var(--text2);font-size:12px;">not found</span>';
    html += `<div style="display:flex;align-items:center;gap:8px;padding:6px 8px;border-bottom:1px solid var(--border);font-size:13px;">
      ${icon}
      <span style="color:var(--text2);min-width:130px;">${fd.label}</span>
      ${val}
    </div>`;
  }
  html += `</div></div>`;

  // ── Extracted Inquiries Table ─────────────────────────────────
  if (data.inquiries?.length) {
    html += `
    <h2 style="margin-bottom:12px;">Extracted Hard Inquiries (${data.inquiries.length})</h2>
    <div class="card" style="margin-bottom:20px;">
      <table><thead><tr><th>Lender</th><th>Date</th><th>Bureau</th><th>Falls Off</th></tr></thead><tbody>`;
    for (const inq of data.inquiries) {
      const bColor = {experian:'blue',transunion:'green',equifax:'purple'}[inq.bureau] || 'dim';
      html += `<tr>
        <td><strong>${inq.lender}</strong></td>
        <td>${inq.date}</td>
        <td><span class="badge badge-${bColor}">${(inq.bureau||'').charAt(0).toUpperCase()+(inq.bureau||'').slice(1)}</span></td>
        <td style="color:var(--text2);">${inq.falls_off || '—'}</td>
      </tr>`;
    }
    html += `</tbody></table></div>`;
  }

  // ── Upload Another ───────────────────────────────────────────
  html += `<div style="text-align:center;margin-top:16px;">
    <button class="btn btn-primary" onclick="$('upload-analysis').style.display='none';">Upload Another Report</button>
  </div>`;

  el.innerHTML = html;
}

// ── Referrals Tab ─────────────────────────────────────────────────

let referralGrid = null;
let referralProducts = [];
let referralClients = [];

function refStatusRenderer(params) {
  const map = {submitted:'blue', in_review:'yellow', approved:'green', funded:'purple', denied:'red', expired:'dim'};
  return `<span class="badge badge-${map[params.value]||'dim'}">${(params.value||'').replace(/_/g,' ')}</span>`;
}

function refDollarRenderer(params) {
  if (params.value == null) return '<span style="color:var(--text2)">—</span>';
  return `<span style="color:var(--green);font-weight:500;">${fmt(params.value)}</span>`;
}

function refActionsRenderer(params) {
  const opts = ['submitted','in_review','approved','funded','denied','expired'];
  let html = `<select style="background:var(--surface2);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:2px 6px;font-size:11px;" onchange="updateRefStatus(${params.data.id}, this.value)">`;
  for (const o of opts) {
    html += `<option value="${o}" ${o===params.data.status?'selected':''}>${o.replace(/_/g,' ')}</option>`;
  }
  html += `</select>`;
  return html;
}

const referralColumnDefs = [
  { field: 'client_name', headerName: 'Client', flex: 1, filter: true, sortable: true, cellStyle: {'font-weight':'600'} },
  { field: 'lender', headerName: 'Lender', flex: 1, filter: true, sortable: true },
  { field: 'product_name', headerName: 'Product', flex: 1.3, filter: true, sortable: true },
  { field: 'referral_date', headerName: 'Date', width: 110, filter: true, sortable: true },
  { field: 'status', headerName: 'Status', width: 110, filter: true, sortable: true, cellRenderer: refStatusRenderer },
  { field: 'funded_amount', headerName: 'Funded', width: 120, filter: 'agNumberColumnFilter', sortable: true, cellRenderer: refDollarRenderer },
  { field: 'expected_commission', headerName: 'Expected', width: 110, filter: 'agNumberColumnFilter', sortable: true, cellRenderer: refDollarRenderer },
  { field: 'actual_commission', headerName: 'Actual', width: 110, filter: 'agNumberColumnFilter', sortable: true, cellRenderer: refDollarRenderer },
  { field: 'commission_paid_date', headerName: 'Paid', width: 110, filter: true, sortable: true },
  { headerName: '', width: 130, cellRenderer: refActionsRenderer, sortable: false },
];

const referralGridOptions = {
  columnDefs: referralColumnDefs,
  rowData: [],
  defaultColDef: { resizable: true },
  animateRows: true,
  suppressCellFocus: true,
  overlayNoRowsTemplate: '<div class="empty-state">No referrals yet. Click "+ New Referral" to get started.</div>',
};

async function loadReferrals() {
  const [summaryRes, referralsRes, productsRes, clientsRes] = await Promise.all([
    fetch('/api/referrals/summary').then(r => r.json()),
    fetch('/api/referrals').then(r => r.json()),
    fetch('/api/referral-products').then(r => r.json()),
    fetch('/api/referral-clients').then(r => r.json()),
  ]);

  referralProducts = productsRes;
  referralClients = clientsRes;

  // Summary cards
  $('referral-summary-cards').innerHTML = `
    <div class="card">
      <div class="card-title">Total Referrals</div>
      <div class="card-value" style="color:var(--blue)">${summaryRes.total_referrals}</div>
      <div class="card-sub">${summaryRes.funded} funded</div>
    </div>
    <div class="card">
      <div class="card-title">Active Pipeline</div>
      <div class="card-value" style="color:var(--yellow)">${summaryRes.active}</div>
      <div class="card-sub">submitted + in review</div>
    </div>
    <div class="card">
      <div class="card-title">Commission Earned</div>
      <div class="card-value" style="color:var(--green)">${fmt(summaryRes.commission_earned)}</div>
      <div class="card-sub">paid to date</div>
    </div>
    <div class="card">
      <div class="card-title">Commission Pending</div>
      <div class="card-value" style="color:var(--purple)">${fmt(summaryRes.commission_pending)}</div>
      <div class="card-sub">pipeline: ${fmt(summaryRes.pipeline_value)}</div>
    </div>
  `;

  // AG Grid
  if (!referralGrid) {
    const gridDiv = document.querySelector('#referral-grid');
    referralGrid = agGrid.createGrid(gridDiv, referralGridOptions);
  }
  referralGrid.setGridOption('rowData', referralsRes);

  // Commission breakdown by lender
  const byLender = {};
  for (const r of referralsRes) {
    if (!byLender[r.lender]) byLender[r.lender] = { earned: 0, pending: 0, count: 0, display: r.commission_display || '' };
    byLender[r.lender].count++;
    byLender[r.lender].earned += (r.actual_commission || 0);
    byLender[r.lender].pending += (r.expected_commission || 0);
  }
  let breakdownHtml = '';
  for (const [lender, data] of Object.entries(byLender).sort((a,b) => b[1].earned - a[1].earned)) {
    breakdownHtml += `
      <div class="card" style="border-left:3px solid var(--green);">
        <div style="font-weight:600;margin-bottom:4px;">${lender}</div>
        <div style="font-size:12px;color:var(--text2);margin-bottom:8px;">${data.display}</div>
        <div style="display:flex;justify-content:space-between;font-size:13px;">
          <span>Earned: <strong style="color:var(--green)">${fmt(data.earned)}</strong></span>
          <span>Pending: <strong style="color:var(--yellow)">${fmt(data.pending)}</strong></span>
        </div>
        <div style="font-size:11px;color:var(--text2);margin-top:4px;">${data.count} referral${data.count!==1?'s':''}</div>
      </div>`;
  }
  if (!breakdownHtml) {
    breakdownHtml = '<div class="card" style="grid-column:1/-1;"><div class="empty-state">Commission breakdown will appear after you submit referrals.</div></div>';
  }
  $('commission-breakdown').innerHTML = breakdownHtml;

  // Populate dropdowns
  populateRefDropdowns();
}

function populateRefDropdowns() {
  const clientSelect = $('ref-client-select');
  clientSelect.innerHTML = '<option value="">Select client...</option><option value="__new">+ New Client</option>';
  for (const c of referralClients) {
    clientSelect.innerHTML += `<option value="${c.id}">${c.name}${c.email ? ' ('+c.email+')' : ''}</option>`;
  }

  const productSelect = $('ref-product-select');
  productSelect.innerHTML = '<option value="">Select product...</option>';
  for (const p of referralProducts) {
    const license = p.referral_requires_license ? ' [License Req]' : '';
    productSelect.innerHTML += `<option value="${p.id}">${p.lender} — ${p.product_name} (${p.referral_commission_display||'N/A'})${license}</option>`;
  }
}

function showReferralForm() {
  $('referral-form').style.display = 'block';
  $('ref-date').value = new Date().toISOString().slice(0,10);
  populateRefDropdowns();
}

function onRefClientChange(val) {
  $('new-client-fields').style.display = val === '__new' ? 'block' : 'none';
}

function onRefProductChange(val) {
  const info = $('ref-commission-info');
  if (!val) { info.style.display = 'none'; return; }
  const p = referralProducts.find(x => x.id == val);
  if (p) {
    info.style.display = 'block';
    info.innerHTML = `<strong>${p.lender}</strong> — ${p.product_name}<br>
      <span style="color:var(--green);font-weight:600;">${p.referral_commission_display || 'Commission info not available'}</span>
      ${p.referral_requires_license ? '<br><span class="badge badge-yellow" style="margin-top:4px;">Requires ISO/Broker License</span>' : ''}`;
  }
}

async function submitReferral() {
  let clientId = $('ref-client-select').value;
  const productId = $('ref-product-select').value;
  const date = $('ref-date').value;

  if (!productId) { toast('Please select a product', 'error'); return; }
  if (!date) { toast('Please select a date', 'error'); return; }

  // Create new client if needed
  if (clientId === '__new') {
    const name = $('ref-client-name').value.trim();
    if (!name) { toast('Please enter client name', 'error'); return; }
    const res = await fetch('/api/referral-clients', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        name: name,
        email: $('ref-client-email').value.trim() || null,
        phone: $('ref-client-phone').value.trim() || null,
        notes: $('ref-client-notes').value.trim() || null,
      })
    });
    const data = await res.json();
    if (data.error) { toast(data.error, 'error'); return; }
    clientId = data.id;
    toast(`Client "${name}" created`);
  }

  if (!clientId) { toast('Please select a client', 'error'); return; }

  const res = await fetch('/api/referrals', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      client_id: parseInt(clientId),
      product_id: parseInt(productId),
      referral_date: date,
      notes: $('ref-notes').value.trim() || null,
    })
  });
  const data = await res.json();
  if (data.error) { toast(data.error, 'error'); return; }

  toast('Referral submitted successfully');
  $('referral-form').style.display = 'none';
  // Clear form
  $('ref-client-select').value = '';
  $('ref-product-select').value = '';
  $('ref-notes').value = '';
  $('new-client-fields').style.display = 'none';
  $('ref-commission-info').style.display = 'none';
  loadReferrals();
}

async function updateRefStatus(refId, newStatus) {
  const res = await fetch(`/api/referrals/${refId}`, {
    method: 'PATCH',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ status: newStatus })
  });
  const data = await res.json();
  if (data.error) { toast(data.error, 'error'); return; }
  toast(`Referral #${refId} updated to ${newStatus.replace(/_/g,' ')}`);
  loadReferrals();
}

// ── Partners Tab ──────────────────────────────────────────────────

let partnerGrid = null;
let allPartnerData = [];
let partnerFilters = {};

function partnerStatusRenderer(params) {
  const map = {not_started:'dim', applied:'blue', onboarding:'yellow', active:'green', paused:'purple', denied:'red'};
  return `<span class="badge badge-${map[params.value]||'dim'}">${(params.value||'').replace(/_/g,' ')}</span>`;
}

function partnerTypeRenderer(params) {
  const map = {iso:['ISO','red'], affiliate:['Affiliate','green'], referral:['Referral','purple'], partner:['Partner','blue'], broker:['Broker','yellow']};
  const [label, cls] = map[params.value] || [params.value||'—','dim'];
  return `<span class="badge badge-${cls}">${label}</span>`;
}

function partnerPriorityRenderer(params) {
  const v = params.value;
  if (v === 1) return '<span style="color:var(--red);font-weight:700;">1</span>';
  if (v === 2) return '<span style="color:var(--yellow);font-weight:700;">2</span>';
  return '<span style="color:var(--text2);">3</span>';
}

function partnerApiRenderer(params) {
  return params.value
    ? '<span style="color:var(--green);font-weight:600;">Yes</span>'
    : '<span style="color:var(--text2);">—</span>';
}

function partnerPortalRenderer(params) {
  if (!params.value) return '<span style="color:var(--text2);">—</span>';
  return `<a href="${params.value}" target="_blank" rel="noopener" style="color:var(--blue);text-decoration:none;border-bottom:1px dotted var(--blue);font-size:12px;">Open Portal</a>`;
}

function partnerSignupRenderer(params) {
  if (!params.value) return '<span style="color:var(--text2);">—</span>';
  return `<a href="${params.value}" target="_blank" rel="noopener" style="color:var(--blue);text-decoration:none;border-bottom:1px dotted var(--blue);font-size:12px;">Sign Up</a>`;
}

function partnerActionsRenderer(params) {
  const opts = ['not_started','applied','onboarding','active','paused','denied'];
  let html = `<select style="background:var(--surface2);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:2px 6px;font-size:11px;" onchange="updatePartnerStatus(${params.data.id}, this.value)">`;
  for (const o of opts) {
    html += `<option value="${o}" ${o===params.data.status?'selected':''}>${o.replace(/_/g,' ')}</option>`;
  }
  html += `</select>`;
  html += ` <button class="btn" style="padding:2px 8px;font-size:11px;background:var(--surface2);color:var(--text);margin-left:4px;" onclick="editPartner(${params.data.id})">Edit</button>`;
  return html;
}

const partnerColumnDefs = [
  { field: 'priority', headerName: 'P', width: 50, sortable: true, cellRenderer: partnerPriorityRenderer },
  { field: 'lender', headerName: 'Lender', flex: 1.2, filter: true, sortable: true, cellStyle: {'font-weight':'600'} },
  { field: 'program_name', headerName: 'Program', flex: 1.3, filter: true, sortable: true },
  { field: 'program_type', headerName: 'Type', width: 100, filter: true, sortable: true, cellRenderer: partnerTypeRenderer },
  { field: 'status', headerName: 'Status', width: 115, filter: true, sortable: true, cellRenderer: partnerStatusRenderer },
  { field: 'commission_display', headerName: 'Commission', flex: 1.2, filter: true, sortable: true },
  { field: 'has_api', headerName: 'API', width: 65, filter: true, sortable: true, cellRenderer: partnerApiRenderer },
  { field: 'applied_date', headerName: 'Applied', width: 100, filter: true, sortable: true },
  { field: 'approved_date', headerName: 'Approved', width: 100, filter: true, sortable: true },
  { field: 'portal_url', headerName: 'Portal', width: 90, sortable: false, cellRenderer: partnerPortalRenderer },
  { field: 'signup_url', headerName: 'Signup', width: 80, sortable: false, cellRenderer: partnerSignupRenderer },
  { headerName: 'Actions', width: 180, cellRenderer: partnerActionsRenderer, sortable: false },
];

const partnerGridOptions = {
  columnDefs: partnerColumnDefs,
  rowData: [],
  defaultColDef: { resizable: true },
  animateRows: true,
  suppressCellFocus: true,
  overlayNoRowsTemplate: '<div class="empty-state">No partner programs found</div>',
  getRowStyle: params => {
    if (params.data.status === 'active') return { borderLeft: '3px solid var(--green)' };
    if (params.data.priority === 1 && params.data.status === 'not_started') return { borderLeft: '3px solid var(--red)' };
    return null;
  },
};

async function loadPartners() {
  const [summaryRes, programsRes] = await Promise.all([
    fetch('/api/partner-programs/summary').then(r => r.json()),
    fetch('/api/partner-programs').then(r => r.json()),
  ]);

  allPartnerData = programsRes;

  // Summary cards
  $('partner-summary-cards').innerHTML = `
    <div class="card">
      <div class="card-title">Active Partners</div>
      <div class="card-value" style="color:var(--green)">${summaryRes.active}</div>
      <div class="card-sub">signed up & earning</div>
    </div>
    <div class="card">
      <div class="card-title">In Progress</div>
      <div class="card-value" style="color:var(--yellow)">${summaryRes.in_progress}</div>
      <div class="card-sub">applied + onboarding</div>
    </div>
    <div class="card">
      <div class="card-title">Not Started</div>
      <div class="card-value" style="color:var(--text2)">${summaryRes.not_started}</div>
      <div class="card-sub">ready to sign up</div>
    </div>
    <div class="card">
      <div class="card-title">API-Ready</div>
      <div class="card-value" style="color:var(--blue)">${summaryRes.api_ready}</div>
      <div class="card-sub">webhook/API integration</div>
    </div>
  `;

  // Filter chips
  buildPartnerFilterChips(programsRes);

  // AG Grid
  const filteredData = applyPartnerFilters(programsRes);
  if (!partnerGrid) {
    const gridDiv = document.querySelector('#partner-grid');
    partnerGrid = agGrid.createGrid(gridDiv, partnerGridOptions);
  }
  partnerGrid.setGridOption('rowData', filteredData);

  // Quick-start checklist (priority 1 programs)
  const p1 = programsRes.filter(p => p.priority === 1).sort((a,b) => {
    const order = {active:0, onboarding:1, applied:2, not_started:3, paused:4, denied:5};
    return (order[a.status]||9) - (order[b.status]||9);
  });
  let checklistHtml = '';
  for (const [i, prog] of p1.entries()) {
    const statusIcon = prog.status === 'active' ? '<span style="color:var(--green);font-size:18px;">&#10003;</span>'
      : prog.status === 'applied' || prog.status === 'onboarding' ? '<span style="color:var(--yellow);font-size:18px;">&#9679;</span>'
      : '<span style="color:var(--text2);font-size:18px;">&#9675;</span>';
    const signupBtn = prog.signup_url && prog.status === 'not_started'
      ? `<a href="${prog.signup_url}" target="_blank" rel="noopener" class="btn btn-primary" style="padding:4px 12px;font-size:11px;text-decoration:none;">Sign Up</a>`
      : '';
    const markApplied = prog.status === 'not_started'
      ? `<button class="btn btn-green" style="padding:4px 12px;font-size:11px;" onclick="updatePartnerStatus(${prog.id},'applied')">Mark Applied</button>`
      : '';
    checklistHtml += `
      <div class="card" style="display:flex;align-items:center;gap:12px;${prog.status==='active'?'border-left:3px solid var(--green);opacity:0.7;':''}">
        <div style="font-size:18px;font-weight:700;color:var(--text2);width:24px;text-align:center;">${statusIcon}</div>
        <div style="flex:1;">
          <div style="font-weight:600;">${prog.lender}</div>
          <div style="font-size:12px;color:var(--text2);">${prog.program_name} &bull; ${prog.commission_display || 'N/A'}</div>
        </div>
        <div style="display:flex;gap:6px;">${signupBtn}${markApplied}</div>
      </div>`;
  }
  if (!checklistHtml) checklistHtml = '<div class="card" style="grid-column:1/-1;"><div class="empty-state">No priority 1 programs found.</div></div>';
  $('partner-checklist').innerHTML = checklistHtml;
}

function buildPartnerFilterChips(programs) {
  const chips = $('partner-filter-chips');
  let html = '<span style="color:var(--text2);font-size:12px;font-weight:600;margin-right:4px;">FILTER:</span>';

  // Status chips
  const statusCounts = {};
  programs.forEach(p => { statusCounts[p.status] = (statusCounts[p.status]||0)+1; });
  const statusLabels = {not_started:'Not Started', applied:'Applied', onboarding:'Onboarding', active:'Active', paused:'Paused', denied:'Denied'};
  for (const [s, count] of Object.entries(statusCounts).sort((a,b) => b[1]-a[1])) {
    const isActive = partnerFilters.status === s;
    html += `<button class="filter-chip${isActive?' active':''}" onclick="togglePartnerFilter('status','${s}')">
      ${statusLabels[s]||s} <span class="filter-chip-count">${count}</span>
      ${isActive ? '<span class="chip-x">&times;</span>' : ''}
    </button>`;
  }

  html += '<span style="width:1px;height:20px;background:var(--border);margin:0 4px;"></span>';

  // Type chips
  const typeCounts = {};
  programs.forEach(p => { typeCounts[p.program_type] = (typeCounts[p.program_type]||0)+1; });
  const typeLabels = {iso:'ISO', affiliate:'Affiliate', referral:'Referral', partner:'Partner', broker:'Broker'};
  for (const [t, count] of Object.entries(typeCounts).sort((a,b) => b[1]-a[1])) {
    const isActive = partnerFilters.type === t;
    html += `<button class="filter-chip${isActive?' active':''}" onclick="togglePartnerFilter('type','${t}')">
      ${typeLabels[t]||t} <span class="filter-chip-count">${count}</span>
      ${isActive ? '<span class="chip-x">&times;</span>' : ''}
    </button>`;
  }

  html += '<span style="width:1px;height:20px;background:var(--border);margin:0 4px;"></span>';

  // Special chips: Has API
  const apiCount = programs.filter(p => p.has_api).length;
  if (apiCount) {
    const isActive = partnerFilters.special === 'has_api';
    html += `<button class="filter-chip${isActive?' active':''}" onclick="togglePartnerFilter('special','has_api')" style="${isActive?'':'border-color:rgba(88,166,255,0.4);color:var(--blue);'}">
      Has API <span class="filter-chip-count">${apiCount}</span>
      ${isActive ? '<span class="chip-x">&times;</span>' : ''}
    </button>`;
  }

  // Referral Points Only
  const pointsCount = programs.filter(p => p.commission_type === 'points').length;
  if (pointsCount) {
    const isActive = partnerFilters.special === 'points_only';
    html += `<button class="filter-chip${isActive?' active':''}" onclick="togglePartnerFilter('special','points_only')" style="${isActive?'':'border-color:rgba(188,140,255,0.4);color:var(--purple);'}">
      Points Only <span class="filter-chip-count">${pointsCount}</span>
      ${isActive ? '<span class="chip-x">&times;</span>' : ''}
    </button>`;
  }

  // Priority 1
  const p1Count = programs.filter(p => p.priority === 1).length;
  if (p1Count) {
    const isActive = partnerFilters.special === 'priority_1';
    html += `<button class="filter-chip${isActive?' active':''}" onclick="togglePartnerFilter('special','priority_1')" style="${isActive?'':'border-color:rgba(248,81,73,0.4);color:var(--red);'}">
      Priority 1 <span class="filter-chip-count">${p1Count}</span>
      ${isActive ? '<span class="chip-x">&times;</span>' : ''}
    </button>`;
  }

  chips.innerHTML = html;
}

function togglePartnerFilter(type, value) {
  if (partnerFilters[type] === value) {
    delete partnerFilters[type];
  } else {
    partnerFilters[type] = value;
  }
  const filtered = applyPartnerFilters(allPartnerData);
  if (partnerGrid) partnerGrid.setGridOption('rowData', filtered);
  buildPartnerFilterChips(allPartnerData);
}

function applyPartnerFilters(data) {
  let filtered = data;
  if (partnerFilters.status) {
    filtered = filtered.filter(p => p.status === partnerFilters.status);
  }
  if (partnerFilters.type) {
    filtered = filtered.filter(p => p.program_type === partnerFilters.type);
  }
  if (partnerFilters.special === 'has_api') {
    filtered = filtered.filter(p => p.has_api);
  }
  if (partnerFilters.special === 'points_only') {
    filtered = filtered.filter(p => p.commission_type === 'points');
  }
  if (partnerFilters.special === 'priority_1') {
    filtered = filtered.filter(p => p.priority === 1);
  }
  return filtered;
}

async function updatePartnerStatus(progId, newStatus) {
  const res = await fetch(`/api/partner-programs/${progId}`, {
    method: 'PATCH',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ status: newStatus })
  });
  const data = await res.json();
  if (data.error) { toast(data.error, 'error'); return; }
  toast(`Partner #${progId} updated to ${newStatus.replace(/_/g,' ')}`);
  loadPartners();
}

function editPartner(progId) {
  const prog = allPartnerData.find(p => p.id === progId);
  if (!prog) return;
  const portal = prompt('Portal URL:', prog.portal_url || '');
  if (portal === null) return;
  const refLink = prompt('Referral Link:', prog.referral_link || '');
  if (refLink === null) return;
  const contact = prompt('Contact Name:', prog.contact_name || '');
  if (contact === null) return;
  const email = prompt('Contact Email:', prog.contact_email || '');
  if (email === null) return;
  const notes = prompt('Notes:', prog.notes || '');
  if (notes === null) return;

  const body = {};
  if (portal !== (prog.portal_url || '')) body.portal_url = portal || null;
  if (refLink !== (prog.referral_link || '')) body.referral_link = refLink || null;
  if (contact !== (prog.contact_name || '')) body.contact_name = contact || null;
  if (email !== (prog.contact_email || '')) body.contact_email = email || null;
  if (notes !== (prog.notes || '')) body.notes = notes || null;

  if (Object.keys(body).length === 0) { toast('No changes made'); return; }

  fetch(`/api/partner-programs/${progId}`, {
    method: 'PATCH',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  }).then(r => r.json()).then(data => {
    if (data.error) { toast(data.error, 'error'); return; }
    toast('Partner updated');
    loadPartners();
  });
}

function showPartnerForm() {
  $('partner-form').style.display = 'block';
}

async function submitPartner() {
  const lender = $('pp-lender').value.trim();
  const program = $('pp-program').value.trim();
  if (!lender || !program) { toast('Lender and program name required', 'error'); return; }

  const res = await fetch('/api/partner-programs', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      lender: lender,
      program_name: program,
      program_type: $('pp-type').value,
      commission_display: $('pp-commission').value.trim() || null,
      signup_url: $('pp-signup-url').value.trim() || null,
      priority: parseInt($('pp-priority').value),
      notes: $('pp-notes').value.trim() || null,
    })
  });
  const data = await res.json();
  if (data.error) { toast(data.error, 'error'); return; }
  toast('Partner program added');
  $('partner-form').style.display = 'none';
  $('pp-lender').value = '';
  $('pp-program').value = '';
  $('pp-commission').value = '';
  $('pp-signup-url').value = '';
  $('pp-notes').value = '';
  loadPartners();
}

// ── Init ──────────────────────────────────────────────────────────
loadOverview();
</script>
</body>
</html>"""


# ── Entry Point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Business Funding Tracker Dashboard")
    parser.add_argument("--port", type=int, default=5055)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--debug", action="store_true", default=False,
                        help="Enable Flask debug mode (NEVER use with --host 0.0.0.0)")
    args = parser.parse_args()

    print("\n  Business Funding Tracker Dashboard")
    print(f"  http://{args.host}:{args.port}\n")
    app.run(host=args.host, port=args.port, debug=args.debug)
