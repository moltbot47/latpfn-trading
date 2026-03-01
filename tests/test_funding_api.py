"""Tests for funding dashboard Flask API endpoints."""

import json


# ── Products ─────────────────────────────────────────────────────────


class TestProductsAPI:
    def test_get_products(self, flask_client):
        resp = flask_client.get("/api/products")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert len(data) > 0  # seeded catalog
        assert "lender" in data[0]

    def test_get_products_filter_type(self, flask_client):
        resp = flask_client.get("/api/products?type=credit_card")
        assert resp.status_code == 200
        data = resp.get_json()
        assert all(p["product_type"] == "credit_card" for p in data)


# ── Applications ─────────────────────────────────────────────────────


class TestApplicationsAPI:
    def test_post_application_valid(self, flask_client):
        resp = flask_client.post("/api/applications",
                                  data=json.dumps({
                                      "lender": "Chase",
                                      "product_type": "credit_card",
                                      "product_name": "Ink Preferred",
                                      "status": "planned",
                                  }),
                                  content_type="application/json")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "id" in data
        assert data["status"] == "created"

    def test_post_application_missing_lender(self, flask_client):
        resp = flask_client.post("/api/applications",
                                  data=json.dumps({"product_type": "credit_card"}),
                                  content_type="application/json")
        assert resp.status_code == 400
        assert "lender" in resp.get_json()["error"].lower()

    def test_post_application_invalid_status(self, flask_client):
        resp = flask_client.post("/api/applications",
                                  data=json.dumps({
                                      "lender": "Chase",
                                      "status": "bogus_status",
                                  }),
                                  content_type="application/json")
        assert resp.status_code == 400
        assert "Invalid status" in resp.get_json()["error"]

    def test_patch_application(self, flask_client):
        # Create first
        resp = flask_client.post("/api/applications",
                                  data=json.dumps({"lender": "Chase", "status": "planned"}),
                                  content_type="application/json")
        app_id = resp.get_json()["id"]

        # Patch
        resp = flask_client.patch(f"/api/applications/{app_id}",
                                   data=json.dumps({"status": "approved", "amount_approved": 15000}),
                                   content_type="application/json")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "updated"

    def test_patch_application_no_json(self, flask_client):
        resp = flask_client.patch("/api/applications/1",
                                   data="not json",
                                   content_type="text/plain")
        assert resp.status_code == 400

    def test_post_application_no_content_type(self, flask_client):
        resp = flask_client.post("/api/applications", data="not json")
        assert resp.status_code == 400


# ── Partner Programs ─────────────────────────────────────────────────


class TestPartnerProgramsAPI:
    def test_get_partner_programs(self, flask_client):
        resp = flask_client.get("/api/partner-programs")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert len(data) > 0  # seeded programs

    def test_get_partner_programs_filter(self, flask_client):
        resp = flask_client.get("/api/partner-programs?status=not_started")
        assert resp.status_code == 200
        data = resp.get_json()
        assert all(p["status"] == "not_started" for p in data)

    def test_patch_partner_program(self, flask_client):
        # Get first program
        resp = flask_client.get("/api/partner-programs")
        prog_id = resp.get_json()[0]["id"]

        resp = flask_client.patch(f"/api/partner-programs/{prog_id}",
                                   data=json.dumps({"status": "applied"}),
                                   content_type="application/json")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_get_partner_summary(self, flask_client):
        resp = flask_client.get("/api/partner-programs/summary")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total" in data
        assert "active" in data
        assert "api_ready" in data
        assert data["total"] > 0


# ── Referrals ────────────────────────────────────────────────────────


class TestReferralsAPI:
    def test_get_referrals(self, flask_client):
        resp = flask_client.get("/api/referrals")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)

    def test_get_referral_summary(self, flask_client):
        resp = flask_client.get("/api/referrals/summary")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total_referrals" in data
        assert "commission_earned" in data


# ── Summary & Index ──────────────────────────────────────────────────


class TestSummaryAndIndex:
    def test_get_funding_summary(self, flask_client):
        resp = flask_client.get("/api/summary")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "summary" in data
        assert "readiness" in data
        assert "total_applications" in data["summary"]

    def test_index_page(self, flask_client):
        resp = flask_client.get("/")
        assert resp.status_code == 200
        assert b"<!DOCTYPE html>" in resp.data or b"<html" in resp.data


# ── Health & Monitoring ──────────────────────────────────────────────


class TestHealthEndpoints:
    def test_health(self, flask_client):
        resp = flask_client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "uptime_seconds" in data
        assert isinstance(data["uptime_seconds"], int)
        assert "version" in data

    def test_health_detail(self, flask_client):
        resp = flask_client.get("/health/detail")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["db"]["ok"] is True
        assert data["db"]["products"] > 0
        assert data["db"]["partner_programs"] > 0
        assert "memory_mb" in data
        assert "python_version" in data
        assert "timestamp" in data

    def test_404_returns_json(self, flask_client):
        resp = flask_client.get("/nonexistent-route")
        assert resp.status_code == 404
        data = resp.get_json()
        assert data["error"] == "Not found"

    def test_request_logging_skips_health(self, flask_client, caplog):
        """Health endpoints should not produce request log lines."""
        import logging
        with caplog.at_level(logging.INFO):
            flask_client.get("/health")
        # No log entry for /health path
        assert not any("/health" in r.message for r in caplog.records)

    def test_metrics_endpoint(self, flask_client):
        # Make a few requests first
        flask_client.get("/api/products")
        flask_client.get("/api/summary")

        resp = flask_client.get("/metrics")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["requests_total"] >= 2
        assert "GET" in data["requests_by_method"]
        assert data["latency_avg_ms"] >= 0
        assert data["latency_max_ms"] >= 0
        assert "uptime_seconds" in data

    def test_security_headers(self, flask_client):
        resp = flask_client.get("/api/products")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert resp.headers.get("X-Request-ID") is not None
        assert len(resp.headers.get("X-Request-ID")) == 12

    def test_request_id_unique(self, flask_client):
        r1 = flask_client.get("/api/products")
        r2 = flask_client.get("/api/products")
        assert r1.headers["X-Request-ID"] != r2.headers["X-Request-ID"]

    def test_rate_limit_returns_429(self, flask_client, monkeypatch):
        """Exceeding rate limit should return 429."""
        import scripts.funding_dashboard as dash
        # Temporarily set a very low limit
        monkeypatch.setattr(dash, "RATE_LIMIT_REQUESTS", 2)
        dash._rate_limit_store.clear()

        flask_client.get("/api/products")
        flask_client.get("/api/products")
        resp = flask_client.get("/api/products")  # 3rd request exceeds limit of 2
        assert resp.status_code == 429
        assert "Rate limit" in resp.get_json()["error"]

        # Clean up
        dash._rate_limit_store.clear()

    def test_health_bypasses_rate_limit(self, flask_client, monkeypatch):
        """Health endpoints should not be rate limited."""
        import scripts.funding_dashboard as dash
        monkeypatch.setattr(dash, "RATE_LIMIT_REQUESTS", 1)
        dash._rate_limit_store.clear()

        # First request fills the limit
        flask_client.get("/api/products")
        # Health should still work
        resp = flask_client.get("/health")
        assert resp.status_code == 200

        dash._rate_limit_store.clear()

    def test_api_docs(self, flask_client):
        resp = flask_client.get("/api/docs")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total"] > 20  # should have 25+ endpoints
        assert "version" in data
        paths = [e["path"] for e in data["endpoints"]]
        assert "/health" in paths
        assert "/api/summary" in paths
        assert "/metrics" in paths
