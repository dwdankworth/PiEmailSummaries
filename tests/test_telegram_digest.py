from __future__ import annotations

from common.telegram_digest import _build_digest_text, _split_digest_text


def _make_row(priority=3, subject="Test Subject", sender="alice@example.com",
              summary_text="A summary.", model_name="test-model", processing_seconds=1.5):
    return {
        "priority": priority,
        "subject": subject,
        "sender": sender,
        "summary_text": summary_text,
        "is_vip": 0,
        "model_name": model_name,
        "processing_seconds": processing_seconds,
    }


class TestBuildDigestText:
    def test_single_high_priority(self):
        rows = [_make_row(priority=5, subject="Urgent meeting")]
        text = _build_digest_text(rows, "fallback-model")
        assert "High priority" in text
        assert "Urgent meeting" in text
        assert "Total emails: 1" in text

    def test_single_low_priority(self):
        rows = [_make_row(priority=1, subject="FYI")]
        text = _build_digest_text(rows, "fallback-model")
        assert "Low priority" in text
        assert "FYI" in text

    def test_medium_priority(self):
        rows = [_make_row(priority=2)]
        text = _build_digest_text(rows, "fallback-model")
        assert "Medium priority" in text

    def test_mixed_priorities(self):
        rows = [
            _make_row(priority=5, subject="High"),
            _make_row(priority=3, subject="Medium"),
            _make_row(priority=1, subject="Low"),
        ]
        text = _build_digest_text(rows, "fallback-model")
        assert "High priority" in text
        assert "Medium priority" in text
        assert "Low priority" in text
        assert "Total emails: 3" in text

    def test_html_escaping(self):
        rows = [_make_row(priority=4, subject="<script>alert('xss')</script>")]
        text = _build_digest_text(rows, "model")
        assert "<script>" not in text
        assert "&lt;script&gt;" in text

    def test_stats_line(self):
        rows = [_make_row(processing_seconds=2.5)]
        text = _build_digest_text(rows, "fallback")
        assert "Stats:" in text
        assert "2.5s" in text

    def test_fallback_model_used(self):
        rows = [_make_row(model_name=None)]
        text = _build_digest_text(rows, "fallback-model")
        assert "fallback-model" in text


class TestSplitDigestText:
    def test_short_text_not_split(self):
        text = "Short message"
        chunks = _split_digest_text(text)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_long_text_split(self):
        # Build a text that exceeds the 4000 char limit
        entries = []
        for i in range(100):
            entries.append(f"• Entry {i}: {'x' * 50}")
        header = "<b>Email Digest</b> (2025-01-15 10:00 UTC)\nTotal emails: 100\n\n"
        text = header + "\n".join(entries)
        chunks = _split_digest_text(text)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 4000

    def test_part_labels_added(self):
        entries = []
        for i in range(100):
            entries.append(f"• Entry {i}: {'x' * 50}")
        header = "<b>Email Digest</b> (2025-01-15 10:00 UTC)\nTotal emails: 100\n\n"
        text = header + "\n".join(entries)
        chunks = _split_digest_text(text)
        if len(chunks) > 1:
            assert "part 1 of" in chunks[0]
            assert "part 2 of" in chunks[1]
