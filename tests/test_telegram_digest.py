"""Tests for common/telegram_digest.py — digest building, chunking, and delivery."""
from __future__ import annotations

import json

import httpx
import pytest

from common.db import connect, initialize_database, insert_email, save_summary
from common.telegram_digest import (
    _build_digest_text,
    _split_digest_text,
    send_digest_and_mark_delivered,
)


def _make_row(priority, subject="Test subject", sender="test@example.com"):
    return {
        "priority": priority,
        "subject": subject,
        "sender": sender,
        "summary_text": f"Summary for priority {priority}",
        "model_name": "test-model",
        "processing_seconds": 1.0,
    }


class TestBuildDigestText:
    def test_build_digest_text_groups_by_priority(self):
        rows = [_make_row(5), _make_row(3), _make_row(1)]
        text = _build_digest_text(rows, "test-model")
        assert "High priority" in text
        assert "Medium priority" in text
        assert "Low priority" in text
        assert "Total emails: 3" in text


class TestSplitDigestText:
    def test_split_digest_text_long_message(self):
        # Build a message that exceeds the 4000-char limit
        rows = [_make_row(4, subject=f"Email #{i}", sender=f"user{i}@test.com") for i in range(80)]
        text = _build_digest_text(rows, "test-model")
        chunks = _split_digest_text(text)
        assert len(chunks) > 1
        assert all(len(chunk) <= 4000 for chunk in chunks)
        assert "part 1 of" in chunks[0]


class _FakeTelegramResponse:
    def __init__(self, ok: bool):
        self._ok = ok

    def json(self):
        return {"ok": self._ok}


def _seed_processed_summary(database_path, *, gmail_id: str, subject: str, summary_text: str):
    connection = connect(str(database_path))
    email_id = insert_email(
        connection=connection,
        gmail_id=gmail_id,
        thread_id=f"thread-{gmail_id}",
        sender="alerts@example.com",
        recipients="me@gmail.com",
        subject=subject,
        date="2025-04-07T09:00:00Z",
        body_text="Background details for the alert.",
        headers={"from": "alerts@example.com", "to": "me@gmail.com"},
        is_vip=False,
    )
    save_summary(
        connection=connection,
        email_id=email_id,
        summary_text=summary_text,
        priority=4,
        categories=["ops"],
        priority_reason="The issue affects customer-facing services.",
        model_name="test-model",
        processing_seconds=1.2,
    )
    connection.close()


class TestSendDigestAndMarkDelivered:
    # Mutation detected: move mark_delivered before the Telegram API loop so
    # summaries are marked delivered even when the outbound send fails.
    def test_send_digest_marks_rows_delivered_after_successful_send(
        self, monkeypatch, sample_config, tmp_path
    ):
        database_path = tmp_path / "digest-success.db"
        initialize_database(str(database_path))
        _seed_processed_summary(
            database_path,
            gmail_id="incident-2025-04-07",
            subject="Production database failover complete",
            summary_text="Replication recovered and customer traffic is stable again.",
        )

        payloads: list[dict] = []

        monkeypatch.setattr(
            "common.telegram_digest._send_telegram_with_retry",
            lambda url, json_payload: payloads.append(json_payload)
            or _FakeTelegramResponse(ok=True),
        )

        connection = connect(str(database_path))
        sent_count = send_digest_and_mark_delivered(connection, sample_config, "summarizer")
        summary = connection.execute(
            "SELECT delivered FROM summaries ORDER BY id DESC LIMIT 1"
        ).fetchone()
        email = connection.execute(
            "SELECT status FROM emails ORDER BY id DESC LIMIT 1"
        ).fetchone()
        event = connection.execute(
            """
            SELECT event_type, details
            FROM system_log
            WHERE service = 'summarizer'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        connection.close()

        assert sent_count == 1
        assert len(payloads) == 1
        assert payloads[0]["chat_id"] == sample_config.telegram_chat_id
        assert payloads[0]["parse_mode"] == "HTML"
        assert "Production database failover complete" in payloads[0]["text"]
        assert summary["delivered"] == 1
        assert email["status"] == "delivered"
        assert event["event_type"] == "digest_sent"
        assert json.loads(event["details"]) == {
            "count": 1,
            "chat_id": sample_config.telegram_chat_id,
        }

    # Mutation detected: remove the digest_failed event or call mark_delivered
    # from the exception path so failed sends disappear from operational history.
    def test_send_digest_records_failure_and_leaves_rows_undelivered(
        self, monkeypatch, sample_config, tmp_path
    ):
        database_path = tmp_path / "digest-failure.db"
        initialize_database(str(database_path))
        _seed_processed_summary(
            database_path,
            gmail_id="incident-2025-04-08",
            subject="API latency spike detected",
            summary_text="Latency crossed the SLO for eleven minutes in eu-west.",
        )

        monkeypatch.setattr(
            "common.telegram_digest._send_telegram_with_retry",
            lambda url, json_payload: (_ for _ in ()).throw(httpx.TimeoutException("telegram timed out")),
        )

        connection = connect(str(database_path))
        try:
            with pytest.raises(httpx.TimeoutException, match="telegram timed out"):
                send_digest_and_mark_delivered(connection, sample_config, "telegram-bot")

            summary = connection.execute(
                "SELECT delivered FROM summaries ORDER BY id DESC LIMIT 1"
            ).fetchone()
            email = connection.execute(
                "SELECT status FROM emails ORDER BY id DESC LIMIT 1"
            ).fetchone()
            event = connection.execute(
                """
                SELECT event_type, details
                FROM system_log
                WHERE service = 'telegram-bot'
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        finally:
            connection.close()

        assert summary["delivered"] == 0
        assert email["status"] == "processed"
        assert event["event_type"] == "digest_failed"
        assert json.loads(event["details"]) == {
            "error": "telegram timed out",
            "count": 1,
        }
