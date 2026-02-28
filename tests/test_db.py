from __future__ import annotations

import json

from common.db import (
    fetch_pending_emails,
    fetch_undelivered_processed,
    insert_email,
    mark_delivered,
    record_system_event,
    save_summary,
    search_summaries,
    status_snapshot,
)


def _insert_sample_email(conn, gmail_id="msg-1", subject="Test Subject", sender="alice@example.com", is_vip=False):
    return insert_email(
        connection=conn,
        gmail_id=gmail_id,
        thread_id="thread-1",
        sender=sender,
        recipients="bob@example.com",
        subject=subject,
        date="2025-01-15T10:00:00Z",
        body_text="Hello, this is the body.",
        headers={"to": "bob@example.com", "from": sender},
        is_vip=is_vip,
    )


class TestInsertEmail:
    def test_insert_returns_row_id(self, db_connection):
        row_id = _insert_sample_email(db_connection)
        assert row_id is not None
        assert row_id > 0

    def test_duplicate_gmail_id_returns_none(self, db_connection):
        _insert_sample_email(db_connection, gmail_id="dup-1")
        result = _insert_sample_email(db_connection, gmail_id="dup-1")
        assert result is None

    def test_email_stored_with_correct_status(self, db_connection):
        _insert_sample_email(db_connection)
        row = db_connection.execute("SELECT status FROM emails WHERE gmail_id='msg-1'").fetchone()
        assert row["status"] == "pending"

    def test_vip_flag_stored(self, db_connection):
        _insert_sample_email(db_connection, gmail_id="vip-1", is_vip=True)
        row = db_connection.execute("SELECT is_vip FROM emails WHERE gmail_id='vip-1'").fetchone()
        assert row["is_vip"] == 1


class TestFetchPendingEmails:
    def test_returns_pending_only(self, db_connection):
        _insert_sample_email(db_connection, gmail_id="p1")
        _insert_sample_email(db_connection, gmail_id="p2")
        rows = fetch_pending_emails(db_connection, limit=10)
        assert len(rows) == 2

    def test_respects_limit(self, db_connection):
        for i in range(5):
            _insert_sample_email(db_connection, gmail_id=f"lim-{i}")
        rows = fetch_pending_emails(db_connection, limit=3)
        assert len(rows) == 3

    def test_vip_ordered_first(self, db_connection):
        _insert_sample_email(db_connection, gmail_id="normal", is_vip=False)
        _insert_sample_email(db_connection, gmail_id="vip", is_vip=True)
        rows = fetch_pending_emails(db_connection, limit=10)
        assert rows[0]["gmail_id"] == "vip"


class TestSaveSummary:
    def test_saves_and_transitions_status(self, db_connection):
        email_id = _insert_sample_email(db_connection)
        save_summary(
            connection=db_connection,
            email_id=email_id,
            summary_text="A brief summary.",
            priority=3,
            categories=["work"],
            priority_reason="Contains deadline",
            model_name="test-model",
            processing_seconds=1.5,
        )
        email_row = db_connection.execute("SELECT status FROM emails WHERE id=?", (email_id,)).fetchone()
        assert email_row["status"] == "processed"

        summary_row = db_connection.execute("SELECT * FROM summaries WHERE email_id=?", (email_id,)).fetchone()
        assert summary_row["priority"] == 3
        assert summary_row["delivered"] == 0
        assert summary_row["model_name"] == "test-model"

    def test_upsert_updates_existing(self, db_connection):
        email_id = _insert_sample_email(db_connection)
        save_summary(db_connection, email_id, "First", 2, [], "r1", "m1", 1.0)
        save_summary(db_connection, email_id, "Updated", 4, ["new"], "r2", "m2", 2.0)
        row = db_connection.execute("SELECT summary_text, priority FROM summaries WHERE email_id=?", (email_id,)).fetchone()
        assert row["summary_text"] == "Updated"
        assert row["priority"] == 4


class TestDeliveryFlow:
    def test_fetch_undelivered_and_mark_delivered(self, db_connection):
        email_id = _insert_sample_email(db_connection)
        save_summary(db_connection, email_id, "Summary", 3, ["test"], "reason", "model", 1.0)

        undelivered = fetch_undelivered_processed(db_connection)
        assert len(undelivered) == 1
        summary_id = undelivered[0]["summary_id"]

        mark_delivered(db_connection, [summary_id])
        after = fetch_undelivered_processed(db_connection)
        assert len(after) == 0

        email_row = db_connection.execute("SELECT status FROM emails WHERE id=?", (email_id,)).fetchone()
        assert email_row["status"] == "delivered"

    def test_mark_delivered_empty_list(self, db_connection):
        mark_delivered(db_connection, [])  # should not raise


class TestSearchSummaries:
    def test_search_by_subject(self, db_connection):
        email_id = _insert_sample_email(db_connection, subject="Meeting tomorrow")
        save_summary(db_connection, email_id, "Team meeting.", 2, [], "routine", "m", 1.0)
        results = search_summaries(db_connection, "Meeting")
        assert len(results) == 1
        assert "Meeting" in results[0]["subject"]

    def test_search_by_summary_text(self, db_connection):
        email_id = _insert_sample_email(db_connection)
        save_summary(db_connection, email_id, "Budget review needed.", 3, [], "finance", "m", 1.0)
        results = search_summaries(db_connection, "Budget")
        assert len(results) == 1

    def test_search_no_match(self, db_connection):
        email_id = _insert_sample_email(db_connection)
        save_summary(db_connection, email_id, "Hello", 1, [], "greeting", "m", 1.0)
        results = search_summaries(db_connection, "xyznonexistent")
        assert len(results) == 0


class TestStatusSnapshot:
    def test_initial_snapshot(self, db_connection):
        snap = status_snapshot(db_connection)
        assert snap["pending_queue_size"] == 0
        assert snap["undelivered_processed_count"] == 0
        assert snap["last_fetch_time"] is None

    def test_reflects_pending(self, db_connection):
        _insert_sample_email(db_connection, gmail_id="s1")
        _insert_sample_email(db_connection, gmail_id="s2")
        snap = status_snapshot(db_connection)
        assert snap["pending_queue_size"] == 2


class TestRecordSystemEvent:
    def test_event_stored(self, db_connection):
        record_system_event(db_connection, "test_service", "test_event", {"key": "value"})
        row = db_connection.execute("SELECT * FROM system_log WHERE service='test_service'").fetchone()
        assert row["event_type"] == "test_event"
        details = json.loads(row["details"])
        assert details["key"] == "value"
