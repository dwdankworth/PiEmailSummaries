"""Shared fixtures for EmailSummaries tests."""
from __future__ import annotations

import json
import sqlite3

import pytest

from common.config import AppConfig
from common.db import init_schema


@pytest.fixture()
def db():
    """In-memory SQLite connection with schema initialized."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    init_schema(conn)
    yield conn
    conn.close()


@pytest.fixture()
def sample_config():
    """Minimal AppConfig for testing (no real tokens)."""
    return AppConfig(
        vip_senders=["boss@company.com", "*@important-client.com"],
        priority_keywords=["urgent", "deadline", "action required"],
        skip_labels=["CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_UPDATES"],
        telegram_bot_token="test-token",
        telegram_chat_id="12345",
        gmail_user_email="me@gmail.com",
        ollama_model="test-model",
    )


@pytest.fixture()
def sample_email_row():
    """Dict matching the shape of an emails table row."""
    return {
        "id": 1,
        "gmail_id": "msg_001",
        "thread_id": "thread_001",
        "sender": "alice@example.com",
        "recipients": "me@gmail.com",
        "subject": "Weekly report",
        "date": "2025-01-15T10:00:00Z",
        "body_text": "Here is the weekly report with key metrics.",
        "headers_json": json.dumps({"from": "alice@example.com", "to": "me@gmail.com"}),
        "is_vip": 0,
        "status": "pending",
    }
