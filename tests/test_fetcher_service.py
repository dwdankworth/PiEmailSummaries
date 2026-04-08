"""Tests for fetcher/service.py — VIP matching, skip logic, and fetch cycles."""
from __future__ import annotations

import json

import pytest

from common.db import connect, initialize_database, insert_email
from fetcher.service import _sender_is_vip, _should_skip, run_fetch_cycle


def _message(
    gmail_id: str,
    *,
    sender_email: str = "alerts@updates.example.com",
    sender: str | None = None,
    recipients: str = "me@gmail.com",
    subject: str = "Project update",
    body_text: str = "Latest project update attached.",
    headers: dict[str, str] | None = None,
    label_ids: list[str] | None = None,
):
    return {
        "gmail_id": gmail_id,
        "thread_id": f"thread-{gmail_id}",
        "sender_email": sender_email,
        "sender": sender or sender_email,
        "recipients": recipients,
        "subject": subject,
        "date": "2025-01-15T10:00:00Z",
        "body_text": body_text,
        "headers": headers or {"from": sender_email, "to": recipients},
        "label_ids": label_ids or ["INBOX"],
    }


class TestSenderIsVip:
    def test_sender_is_vip_wildcard(self):
        patterns = ["boss@company.com", "*@important-client.com"]
        assert _sender_is_vip("boss@company.com", patterns) is True
        assert _sender_is_vip("anyone@important-client.com", patterns) is True
        assert _sender_is_vip("stranger@other.com", patterns) is False
        # Case insensitive
        assert _sender_is_vip("BOSS@COMPANY.COM", patterns) is True


class TestShouldSkip:
    def test_should_skip_promo_label(self, sample_config):
        message = {
            "label_ids": ["CATEGORY_PROMOTIONS", "INBOX"],
            "headers": {},
        }
        assert _should_skip(message, sample_config) is True

    def test_should_skip_list_unsubscribe(self, sample_config):
        message = {
            "label_ids": ["INBOX"],
            "headers": {"list-unsubscribe": "<mailto:unsub@example.com>"},
        }
        assert _should_skip(message, sample_config) is True

        # No unsubscribe header, no skip labels → should NOT skip
        clean_message = {
            "label_ids": ["INBOX"],
            "headers": {},
        }
        assert _should_skip(clean_message, sample_config) is False


class TestRunFetchCycle:
    # Mutation detected: delete the duplicate-count branch so duplicate inserts are
    # counted as new emails instead of duplicates.
    def test_run_fetch_cycle_tracks_inserted_skipped_and_duplicate_messages(
        self, monkeypatch, sample_config, tmp_path
    ):
        database_path = tmp_path / "fetch-cycle.db"
        initialize_database(str(database_path))

        connection = connect(str(database_path))
        insert_email(
            connection=connection,
            gmail_id="dup-2025-04-01",
            thread_id="thread-dup",
            sender="alerts@updates.example.com",
            recipients="me@gmail.com",
            subject="Existing project update",
            date="2025-04-01T08:00:00Z",
            body_text="Original copy already imported.",
            headers={"from": "alerts@updates.example.com", "to": "me@gmail.com"},
            is_vip=False,
        )
        connection.close()

        monkeypatch.setattr("fetcher.service.load_config", lambda _: sample_config)
        monkeypatch.setattr("fetcher.service.build_gmail_service", lambda: object())
        monkeypatch.setattr(
            "fetcher.service.list_recent_messages",
            lambda service, max_results: [
                _message("dup-2025-04-01", subject="Existing project update"),
                _message(
                    "newsletter-2025-04-02",
                    sender_email="news@lists.example.com",
                    subject="Weekly product newsletter",
                    headers={
                        "from": "news@lists.example.com",
                        "to": "me@gmail.com",
                        "list-unsubscribe": "<mailto:unsubscribe@example.com>",
                    },
                ),
                _message(
                    "vip-2025-04-03",
                    sender_email="partner@important-client.com",
                    subject="Deadline for signed contract is tomorrow",
                    body_text="Please confirm the signed draft by noon tomorrow.",
                ),
            ],
        )

        stats = run_fetch_cycle(database_path=str(database_path))

        assert stats == {"fetched": 3, "inserted": 1, "duplicates": 1, "skipped": 1}

        connection = connect(str(database_path))
        rows = connection.execute(
            "SELECT gmail_id, is_vip FROM emails ORDER BY gmail_id"
        ).fetchall()
        assert [(row["gmail_id"], row["is_vip"]) for row in rows] == [
            ("dup-2025-04-01", 0),
            ("vip-2025-04-03", 1),
        ]
        event = connection.execute(
            """
            SELECT event_type, details
            FROM system_log
            WHERE service = 'fetcher'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        connection.close()

        assert event["event_type"] == "fetch_cycle_completed"
        assert json.loads(event["details"]) == stats

    # Mutation detected: remove the fetch_cycle_failed event write in the
    # exception handler so Gmail failures are no longer recorded for operators.
    def test_run_fetch_cycle_records_failure_before_reraising(
        self, monkeypatch, sample_config, tmp_path
    ):
        database_path = tmp_path / "fetch-cycle-failure.db"
        initialize_database(str(database_path))

        monkeypatch.setattr("fetcher.service.load_config", lambda _: sample_config)
        monkeypatch.setattr("fetcher.service.build_gmail_service", lambda: object())
        monkeypatch.setattr(
            "fetcher.service.list_recent_messages",
            lambda service, max_results: (_ for _ in ()).throw(
                RuntimeError("gmail API quota exceeded")
            ),
        )

        with pytest.raises(RuntimeError, match="gmail API quota exceeded"):
            run_fetch_cycle(database_path=str(database_path))

        connection = connect(str(database_path))
        event = connection.execute(
            """
            SELECT event_type, details
            FROM system_log
            WHERE service = 'fetcher'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        connection.close()

        assert event["event_type"] == "fetch_cycle_failed"
        assert json.loads(event["details"]) == {"error": "gmail API quota exceeded"}
