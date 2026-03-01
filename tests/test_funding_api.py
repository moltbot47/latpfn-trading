"""Tests for funding dashboard Flask API endpoints."""

import json
import pytest


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
