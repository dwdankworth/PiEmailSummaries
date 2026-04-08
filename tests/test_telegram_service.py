"""Tests for telegram_bot/service.py — user-facing status and search commands."""
from __future__ import annotations

from common.db import (
    connect,
    initialize_database,
    insert_email,
    record_system_event,
    save_summary,
)
from telegram_bot.service import get_status, search_digest_items


def _prepare_processed_email(database_path, *, gmail_id: str, subject: str, summary_text: str):
    connection = connect(str(database_path))
    email_id = insert_email(
        connection=connection,
        gmail_id=gmail_id,
        thread_id=f"thread-{gmail_id}",
        sender="manager@example.com",
        recipients="me@gmail.com",
        subject=subject,
        date="2025-04-08T08:30:00Z",
        body_text="Please review the latest incident summary.",
        headers={"from": "manager@example.com", "to": "me@gmail.com"},
        is_vip=True,
    )
    save_summary(
        connection=connection,
        email_id=email_id,
        summary_text=summary_text,
        priority=4,
        categories=["operations"],
        priority_reason="Customer impact is still visible in support tickets.",
        model_name="triage-model-v2",
        processing_seconds=2.4,
    )
    connection.close()


class TestTelegramService:
    # Mutation detected: change the search query to require subject AND summary
    # matches, which would hide valid digest hits from the `/search` command.
    def test_search_digest_items_returns_priority_tagged_matches(self, tmp_path):
        database_path = tmp_path / "telegram-search.db"
        initialize_database(str(database_path))
        _prepare_processed_email(
            database_path,
            gmail_id="incident-2025-04-08",
            subject="Weekly operations review",
            summary_text="The deadline for the database patch was moved to Thursday.",
        )

        results = search_digest_items("database patch", database_path=str(database_path))

        assert results == [
            "[P4] Weekly operations review — The deadline for the database patch was moved to Thursday."
        ]

    # Mutation detected: swap the pending and processed count queries so `/status`
    # reports the wrong operational state to the Telegram user.
    def test_get_status_reports_queue_sizes_last_runs_and_latest_model(
        self, sample_config, tmp_path
    ):
        database_path = tmp_path / "telegram-status.db"
        initialize_database(str(database_path))

        connection = connect(str(database_path))
        insert_email(
            connection=connection,
            gmail_id="pending-2025-04-08",
            thread_id="thread-pending",
            sender="alerts@example.com",
            recipients="me@gmail.com",
            subject="Pending approval required",
            date="2025-04-08T09:00:00Z",
            body_text="A security exception is awaiting review.",
            headers={"from": "alerts@example.com", "to": "me@gmail.com"},
            is_vip=False,
        )
        record_system_event(
            connection,
            "fetcher",
            "fetch_cycle_completed",
            {"fetched": 1, "inserted": 1, "duplicates": 0, "skipped": 0},
        )
        record_system_event(
            connection,
            "summarizer",
            "summarizer_cycle_completed",
            {
                "processed": 1,
                "failed": 0,
                "digest_sent_count": 0,
                "duration_seconds": 1.2,
                "model": "triage-model-v2",
            },
        )
        connection.close()

        _prepare_processed_email(
            database_path,
            gmail_id="processed-2025-04-08",
            subject="Customer outage follow-up",
            summary_text="Support volume remains elevated after the outage was resolved.",
        )

        status = get_status(config=sample_config, database_path=str(database_path))

        assert status["pending_queue_size"] == 1
        assert status["undelivered_processed_count"] == 1
        assert status["last_fetch_time"] is not None
        assert status["last_summarizer_run"] is not None
        assert status["ollama_model_loaded"] == "triage-model-v2"
