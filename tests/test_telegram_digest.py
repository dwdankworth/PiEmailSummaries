"""Tests for common/telegram_digest.py — digest building and chunking."""
from __future__ import annotations

from common.telegram_digest import _build_digest_text, _split_digest_text


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
