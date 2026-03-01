"""Tests for the health monitor script."""

import json
from unittest.mock import patch, MagicMock
import urllib.error

from scripts.health_monitor import check_service, SERVICES


class TestCheckService:
    def test_service_up(self):
        """A reachable service returns status 'up' with response time."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"status": "ok"}).encode()

        with patch("scripts.health_monitor.urllib.request.urlopen", return_value=mock_response):
            result = check_service({"name": "Test", "url": "http://localhost:9999/health"})

        assert result["status"] == "up"
        assert result["response_ms"] is not None
        assert result["response_ms"] >= 0
        assert result["error"] is None

    def test_service_down_connection_refused(self):
        """An unreachable service returns status 'down' with error."""
        with patch("scripts.health_monitor.urllib.request.urlopen",
                   side_effect=urllib.error.URLError("Connection refused")):
            result = check_service({"name": "Test", "url": "http://localhost:9999/health"})

        assert result["status"] == "down"
        assert result["response_ms"] is None
        assert "Connection refused" in result["error"]

    def test_service_with_detail_url(self):
        """When detail_url is present, it fetches additional details."""
        basic = MagicMock()
        basic.read.return_value = json.dumps({"status": "ok"}).encode()

        detail = MagicMock()
        detail.read.return_value = json.dumps({
            "status": "ok",
            "db": {"ok": True},
            "uptime_seconds": 3600,
        }).encode()

        responses = [basic, detail]
        with patch("scripts.health_monitor.urllib.request.urlopen", side_effect=responses):
            result = check_service({
                "name": "Test",
                "url": "http://localhost:9999/health",
                "detail_url": "http://localhost:9999/health/detail",
            })

        assert result["status"] == "up"
        assert result["details"]["uptime_seconds"] == 3600

    def test_service_detail_failure_still_up(self):
        """If detail URL fails but main health is OK, service is still 'up'."""
        basic = MagicMock()
        basic.read.return_value = json.dumps({"status": "ok"}).encode()

        with patch("scripts.health_monitor.urllib.request.urlopen",
                   side_effect=[basic, urllib.error.URLError("timeout")]):
            result = check_service({
                "name": "Test",
                "url": "http://localhost:9999/health",
                "detail_url": "http://localhost:9999/health/detail",
            })

        assert result["status"] == "up"


class TestServicesConfig:
    def test_services_list_not_empty(self):
        assert len(SERVICES) > 0

    def test_each_service_has_required_fields(self):
        for svc in SERVICES:
            assert "name" in svc
            assert "url" in svc
