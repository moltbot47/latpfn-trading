"""Tests for monitoring/logger.py — JSON formatter and setup_logging."""

import json
import logging

from monitoring.logger import JSONFormatter


class TestJSONFormatter:
    def test_basic_format(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test.logger", level=logging.INFO, pathname="", lineno=0,
            msg="Hello %s", args=("world",), exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)

        assert data["level"] == "INFO"
        assert data["logger"] == "test.logger"
        assert data["message"] == "Hello world"
        assert "timestamp" in data
        assert "exception" not in data

    def test_exception_included(self):
        formatter = JSONFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test", level=logging.ERROR, pathname="", lineno=0,
            msg="Failed", args=(), exc_info=exc_info,
        )
        output = formatter.format(record)
        data = json.loads(output)

        assert data["level"] == "ERROR"
        assert "exception" in data
        assert "ValueError: test error" in data["exception"]

    def test_output_is_single_line(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.WARNING, pathname="", lineno=0,
            msg="multi\nline\nmessage", args=(), exc_info=None,
        )
        output = formatter.format(record)
        # JSON itself should be one line (no embedded newlines outside strings)
        assert "\n" not in output
        data = json.loads(output)
        assert "multi\nline\nmessage" == data["message"]
