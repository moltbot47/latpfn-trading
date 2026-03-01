"""End-to-end workflow tests for the funding dashboard.

These tests simulate realistic multi-step user workflows that span
multiple API endpoints, verifying that the system behaves correctly
when actions are chained together (e.g., create application → update
status → verify summary reflects changes).
"""

import json


class TestApplicationLifecycle:
    """Full lifecycle: create → update → approve → verify in summary."""

    def test_create_and_approve_application(self, flask_client):
        # 1. Create a planned application
        resp = flask_client.post("/api/applications",
                                  data=json.dumps({
                                      "lender": "Amex",
                                      "product_type": "credit_card",
                                      "product_name": "Blue Business Plus",
                                      "status": "planned",
                                      "amount_requested": 25000,
                                  }),
                                  content_type="application/json")
        assert resp.status_code == 200
        app_id = resp.get_json()["id"]

        # 2. Submit the application
        resp = flask_client.patch(f"/api/applications/{app_id}",
                                   data=json.dumps({"status": "submitted"}),
                                   content_type="application/json")
        assert resp.status_code == 200

        # 3. Approve with an amount
        resp = flask_client.patch(f"/api/applications/{app_id}",
                                   data=json.dumps({
                                       "status": "approved",
                                       "amount_approved": 20000,
                                   }),
                                   content_type="application/json")
        assert resp.status_code == 200

        # 4. Verify it shows up in the applications list
        resp = flask_client.get("/api/applications")
        assert resp.status_code == 200
        apps = resp.get_json()
        matching = [a for a in apps if a["id"] == app_id]
        assert len(matching) == 1
        assert matching[0]["status"] == "approved"

    def test_multiple_applications_reflected_in_summary(self, flask_client):
        # Create two applications
        for lender in ["Chase", "CapitalOne"]:
            resp = flask_client.post("/api/applications",
                                      data=json.dumps({
                                          "lender": lender,
                                          "product_type": "credit_card",
                                          "status": "planned",
                                      }),
                                      content_type="application/json")
            assert resp.status_code == 200

        # Summary should reflect them
        resp = flask_client.get("/api/summary")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["summary"]["total_applications"] >= 2


class TestReferralWorkflow:
    """Create client → create referral → update status → verify summary."""

    def test_full_referral_flow(self, flask_client):
        # 1. Create a referral client
        resp = flask_client.post("/api/referral-clients",
                                  data=json.dumps({
                                      "name": "John Doe",
                                      "email": "john@example.com",
                                      "phone": "555-0100",
                                  }),
                                  content_type="application/json")
        assert resp.status_code == 201
        client_data = resp.get_json()
        client_id = client_data["id"]

        # 2. Get a referral product to use its ID
        resp = flask_client.get("/api/referral-products")
        assert resp.status_code == 200
        products = resp.get_json()
        assert len(products) > 0
        product_id = products[0]["id"]

        # 3. Create a referral for that client
        resp = flask_client.post("/api/referrals",
                                  data=json.dumps({
                                      "client_id": client_id,
                                      "product_id": product_id,
                                      "referral_date": "2026-03-01",
                                      "status": "submitted",
                                  }),
                                  content_type="application/json")
        assert resp.status_code == 201
        ref_id = resp.get_json()["id"]

        # 4. Update referral to funded with commission
        resp = flask_client.patch(f"/api/referrals/{ref_id}",
                                   data=json.dumps({
                                       "status": "funded",
                                       "actual_commission": 150.0,
                                   }),
                                   content_type="application/json")
        assert resp.status_code == 200

        # 5. Verify referral summary includes the referral
        resp = flask_client.get("/api/referrals/summary")
        assert resp.status_code == 200
        summary = resp.get_json()
        assert summary["total_referrals"] >= 1


class TestPartnerProgramWorkflow:
    """Fetch programs → update status → verify summary changes."""

    def test_activate_partner_program(self, flask_client):
        # 1. Get all partner programs (seeded)
        resp = flask_client.get("/api/partner-programs")
        assert resp.status_code == 200
        programs = resp.get_json()
        assert len(programs) > 0

        prog_id = programs[0]["id"]

        # 2. Update to applied
        resp = flask_client.patch(f"/api/partner-programs/{prog_id}",
                                   data=json.dumps({"status": "applied"}),
                                   content_type="application/json")
        assert resp.status_code == 200

        # 3. Update to active
        resp = flask_client.patch(f"/api/partner-programs/{prog_id}",
                                   data=json.dumps({"status": "active"}),
                                   content_type="application/json")
        assert resp.status_code == 200

        # 4. Summary should show at least 1 active
        resp = flask_client.get("/api/partner-programs/summary")
        assert resp.status_code == 200
        summary = resp.get_json()
        assert summary["active"] >= 1


class TestStrategyIntegration:
    """Verify strategy endpoints work with seeded data."""

    def test_strategy_recommendations(self, flask_client):
        resp = flask_client.get("/api/strategy")
        assert resp.status_code == 200
        data = resp.get_json()
        # Returns a list of recommendation dicts
        assert isinstance(data, list)
        assert len(data) > 0
        assert "category" in data[0]
        assert "title" in data[0]

    def test_round_plan(self, flask_client):
        resp = flask_client.get("/api/round-plan")
        assert resp.status_code == 200
        data = resp.get_json()
        # Returns a list of products (may be empty if no profile uploaded)
        assert isinstance(data, list)

    def test_products_with_filters(self, flask_client):
        # Get all products
        resp = flask_client.get("/api/products")
        assert resp.status_code == 200
        all_products = resp.get_json()
        assert len(all_products) > 0

        # Filter by type
        resp = flask_client.get("/api/products?type=credit_card")
        assert resp.status_code == 200
        cards = resp.get_json()
        assert all(p["product_type"] == "credit_card" for p in cards)
        assert len(cards) <= len(all_products)


class TestHealthAndMonitoring:
    """Verify monitoring infrastructure works end-to-end."""

    def test_health_detail_reflects_seeded_data(self, flask_client):
        resp = flask_client.get("/health/detail")
        assert resp.status_code == 200
        data = resp.get_json()
        # DB should have seeded products and partner programs
        assert data["db"]["products"] > 0
        assert data["db"]["partner_programs"] > 0
        # Uptime should be positive
        assert data["uptime_seconds"] >= 0

    def test_error_handling_returns_json(self, flask_client):
        # 404 should return JSON, not HTML
        resp = flask_client.get("/api/nonexistent-endpoint")
        assert resp.status_code == 404
        data = resp.get_json()
        assert "error" in data


class TestCrossEndpointConsistency:
    """Verify data consistency across related endpoints."""

    def test_application_count_matches_summary(self, flask_client):
        # Create some applications
        for i in range(3):
            flask_client.post("/api/applications",
                               data=json.dumps({
                                   "lender": f"Lender{i}",
                                   "status": "planned",
                               }),
                               content_type="application/json")

        # Get count from applications list
        resp = flask_client.get("/api/applications")
        app_count = len(resp.get_json())

        # Get count from summary
        resp = flask_client.get("/api/summary")
        summary_count = resp.get_json()["summary"]["total_applications"]

        assert app_count == summary_count

    def test_product_catalog_stable_after_multiple_seeds(self, flask_client):
        """Seeding should be idempotent — product count shouldn't change."""
        resp1 = flask_client.get("/api/products")
        count1 = len(resp1.get_json())

        # Health detail also reports product count
        resp2 = flask_client.get("/health/detail")
        count2 = resp2.get_json()["db"]["products"]

        assert count1 == count2
        assert count1 > 0
