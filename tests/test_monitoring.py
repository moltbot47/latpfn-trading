"""Tests for monitoring/logger.py — JSON formatter, setup_logging, error aggregator."""

import json
import logging
import time

from monitoring.logger import JSONFormatter, ErrorAggregator


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


class TestErrorAggregator:
    def test_record_and_flush(self):
        agg = ErrorAggregator(window_seconds=300)
        agg.record("DB timeout")
        agg.record("DB timeout")
        agg.record("API failure")

        assert agg.error_count == 3
        summary = agg.flush()

        assert len(summary) == 2
        db_err = next(s for s in summary if s["message"] == "DB timeout")
        assert db_err["count"] == 2

        # Flush clears the buffer
        assert agg.error_count == 0
        assert agg.flush() == []

    def test_old_errors_excluded(self):
        agg = ErrorAggregator(window_seconds=60)
        old_ts = time.time() - 120  # 2 minutes ago
        agg.record("old error", timestamp=old_ts)
        agg.record("recent error")

        summary = agg.flush()
        messages = [s["message"] for s in summary]
        assert "recent error" in messages
        assert "old error" not in messages

    def test_empty_aggregator(self):
        agg = ErrorAggregator()
        assert agg.error_count == 0
        assert agg.flush() == []

    def test_first_and_last_seen(self):
        agg = ErrorAggregator(window_seconds=300)
        t1 = time.time() - 10
        t2 = time.time()
        agg.record("error", timestamp=t1)
        agg.record("error", timestamp=t2)

        summary = agg.flush()
        assert len(summary) == 1
        assert summary[0]["first_seen"] == t1
        assert summary[0]["last_seen"] == t2
