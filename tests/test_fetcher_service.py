from __future__ import annotations

from common.config import AppConfig
from fetcher.service import _sender_is_vip, _should_skip


class TestSenderIsVip:
    def test_exact_match(self):
        assert _sender_is_vip("boss@company.com", ["boss@company.com"]) is True

    def test_wildcard_match(self):
        assert _sender_is_vip("anyone@important.com", ["*@important.com"]) is True

    def test_no_match(self):
        assert _sender_is_vip("random@other.com", ["boss@company.com"]) is False

    def test_case_insensitive(self):
        assert _sender_is_vip("Boss@Company.COM", ["boss@company.com"]) is True

    def test_empty_patterns(self):
        assert _sender_is_vip("anyone@example.com", []) is False

    def test_whitespace_handling(self):
        assert _sender_is_vip("  boss@company.com  ", ["boss@company.com"]) is True


class TestShouldSkip:
    def _make_config(self, **overrides):
        defaults = {"skip_labels": ["CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL"]}
        defaults.update(overrides)
        return AppConfig(**defaults)

    def test_skips_by_label(self):
        config = self._make_config()
        msg = {"label_ids": ["INBOX", "CATEGORY_PROMOTIONS"], "headers": {}}
        assert _should_skip(msg, config) is True

    def test_no_skip_for_normal_labels(self):
        config = self._make_config()
        msg = {"label_ids": ["INBOX"], "headers": {}}
        assert _should_skip(msg, config) is False

    def test_skips_list_unsubscribe(self):
        config = self._make_config()
        msg = {
            "label_ids": ["INBOX"],
            "headers": {"list-unsubscribe": "<mailto:unsub@example.com>"},
        }
        assert _should_skip(msg, config) is True

    def test_empty_list_unsubscribe_not_skipped(self):
        config = self._make_config()
        msg = {"label_ids": ["INBOX"], "headers": {"list-unsubscribe": ""}}
        assert _should_skip(msg, config) is False

    def test_no_headers_key(self):
        config = self._make_config()
        msg = {"label_ids": [], "headers": {}}
        assert _should_skip(msg, config) is False
