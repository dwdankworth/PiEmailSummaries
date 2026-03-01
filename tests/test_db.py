"""Tests for common/db.py — data integrity and lifecycle."""
from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

from common.db import (
    execute_with_retry,
    fetch_pending_emails,
    fetch_undelivered_processed,
    init_schema,
    insert_email,
    mark_delivered,
    save_summary,
)


def _insert_helper(db, gmail_id="msg_001", sender="alice@example.com", is_vip=False):
    """Shortcut to insert an email and return its row id."""
    return insert_email(
        db,
        gmail_id=gmail_id,
        thread_id="thread_001",
        sender=sender,
        recipients="me@gmail.com",
        subject="Test subject",
        date="2025-01-15T10:00:00Z",
        body_text="Hello world",
        headers={"from": sender, "to": "me@gmail.com"},
        is_vip=is_vip,
    )


class TestInitSchema:
    def test_init_schema_creates_tables(self, db):
        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "emails" in tables
        assert "summaries" in tables
        assert "system_log" in tables


class TestInsertEmail:
    def test_insert_email_returns_id(self, db):
        row_id = _insert_helper(db)
        assert isinstance(row_id, int)
        assert row_id > 0

    def test_insert_email_duplicate_returns_none(self, db):
        _insert_helper(db, gmail_id="dup_001")
        result = _insert_helper(db, gmail_id="dup_001")
        assert result is None


class TestFetchPendingEmails:
    def test_fetch_pending_emails_vip_first(self, db):
        _insert_helper(db, gmail_id="normal_1", sender="normal@test.com", is_vip=False)
        _insert_helper(db, gmail_id="vip_1", sender="boss@test.com", is_vip=True)
        rows = fetch_pending_emails(db, limit=10)
        assert len(rows) == 2
        assert rows[0]["is_vip"] == 1
        assert rows[1]["is_vip"] == 0


class TestSaveSummary:
    def test_save_summary_marks_processed(self, db):
        email_id = _insert_helper(db)
        save_summary(
            db,
            email_id=email_id,
            summary_text="Test summary",
            priority=3,
            categories=["test"],
            priority_reason="testing",
            model_name="test-model",
            processing_seconds=1.5,
        )
        status = db.execute(
            "SELECT status FROM emails WHERE id = ?", (email_id,)
        ).fetchone()["status"]
        assert status == "processed"


class TestMarkDelivered:
    def test_mark_delivered_updates_both_tables(self, db):
        email_id = _insert_helper(db)
        save_summary(
            db,
            email_id=email_id,
            summary_text="Summary",
            priority=3,
            categories=[],
            priority_reason="reason",
            model_name="test-model",
            processing_seconds=1.0,
        )
        summary_row = db.execute(
            "SELECT id FROM summaries WHERE email_id = ?", (email_id,)
        ).fetchone()
        mark_delivered(db, [summary_row["id"]])

        summary = db.execute(
            "SELECT delivered FROM summaries WHERE id = ?", (summary_row["id"],)
        ).fetchone()
        email = db.execute(
            "SELECT status FROM emails WHERE id = ?", (email_id,)
        ).fetchone()
        assert summary["delivered"] == 1
        assert email["status"] == "delivered"


class TestFullLifecycle:
    def test_full_lifecycle_pending_to_delivered(self, db):
        email_id = _insert_helper(db)
        # Pending
        pending = fetch_pending_emails(db, limit=10)
        assert len(pending) == 1

        # Process
        save_summary(
            db,
            email_id=email_id,
            summary_text="Full lifecycle summary",
            priority=4,
            categories=["lifecycle"],
            priority_reason="test",
            model_name="model",
            processing_seconds=2.0,
        )
        assert fetch_pending_emails(db, limit=10) == []

        # Deliver
        undelivered = fetch_undelivered_processed(db)
        assert len(undelivered) == 1
        mark_delivered(db, [undelivered[0]["summary_id"]])

        assert fetch_undelivered_processed(db) == []
        final_status = db.execute(
            "SELECT status FROM emails WHERE id = ?", (email_id,)
        ).fetchone()["status"]
        assert final_status == "delivered"


class TestExecuteWithRetry:
    def test_execute_with_retry_on_locked(self):
        call_count = 0

        def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise sqlite3.OperationalError("database is locked")
            return "success"

        result = execute_with_retry(flaky_func)
        assert result == "success"
        assert call_count == 3
