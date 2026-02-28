from __future__ import annotations

import json

from common.logging_utils import JsonFormatter, get_logger


class TestJsonFormatter:
    def test_basic_format(self):
        import logging

        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello world", args=(), exc_info=None,
        )
        record.service = "test_svc"
        output = formatter.format(record)
        data = json.loads(output)
        assert data["level"] == "INFO"
        assert data["message"] == "hello world"
        assert data["service"] == "test_svc"
        assert "timestamp" in data

    def test_extra_json_included(self):
        import logging

        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.WARNING, pathname="", lineno=0,
            msg="with details", args=(), exc_info=None,
        )
        record.service = "svc"
        record.extra_json = {"count": 42}
        output = formatter.format(record)
        data = json.loads(output)
        assert data["details"]["count"] == 42


class TestGetLogger:
    def test_returns_logger_with_handler(self):
        logger = get_logger("unit_test_svc")
        assert len(logger.handlers) >= 1

    def test_idempotent(self):
        logger1 = get_logger("idempotent_test")
        logger2 = get_logger("idempotent_test")
        assert logger1 is logger2
        assert len(logger1.handlers) == 1
